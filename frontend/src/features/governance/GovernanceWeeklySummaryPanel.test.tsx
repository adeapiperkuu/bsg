import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { GovernanceWeeklySummaryPanel } from "@/features/governance/GovernanceWeeklySummaryPanel";
import { parseGovernanceSummarySections } from "@/features/governance/governance-weekly-summary";

const mocks = vi.hoisted(() => ({ apiFetch: vi.fn(), apiFetchBlob: vi.fn() }));

vi.mock("@/lib/api", () => ({
  apiFetch: mocks.apiFetch,
  apiFetchBlob: mocks.apiFetchBlob,
}));

vi.mock("sonner", () => ({
  toast: { success: vi.fn(), error: vi.fn() },
}));

const draft = {
  id: "11111111-1111-1111-1111-111111111111",
  org_id: "22222222-2222-2222-2222-222222222222",
  summary_week: "2026-07-13",
  summary_text: [
    "## 1. Executive Overview",
    "Portfolio governance remains stable.",
    "## 2. Key Governance Risks",
    "- External approval is overdue.",
    "## 3. Delivery Impact",
    "One milestone is at risk.",
    "## 4. Recommended Governance Actions",
    "- Leadership decision required Thursday.",
    "## 5. Projects Requiring Attention",
    "- Helios",
    "## 6. Evidence Section",
    "- dependency:abc",
  ].join("\n"),
  status: "draft" as const,
  generated_by_ai: true,
  approved_by: null,
  approved_at: null,
  created_at: "2026-07-14T08:00:00Z",
  updated_at: "2026-07-14T08:00:00Z",
  evidence_links: [],
};

function renderPanel(canManage = false) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return render(
    <QueryClientProvider client={client}>
      <GovernanceWeeklySummaryPanel canManage={canManage} />
    </QueryClientProvider>,
  );
}

describe("GovernanceWeeklySummaryPanel", () => {
  beforeEach(() => {
    mocks.apiFetch.mockReset();
    mocks.apiFetchBlob.mockReset();
  });

  it("parses the backend markdown contract into named sections", () => {
    const sections = parseGovernanceSummarySections(draft.summary_text);
    expect(sections).toHaveLength(6);
    expect(sections[0]).toEqual({
      heading: "Executive Overview",
      content: "Portfolio governance remains stable.",
    });
  });

  it("shows a non-blocking loading state", async () => {
    mocks.apiFetch.mockResolvedValue({ data: null });
    renderPanel();
    expect(screen.getByLabelText("Loading weekly governance summary")).toBeInTheDocument();
    expect(await screen.findByText("No weekly governance summary yet")).toBeInTheDocument();
  });

  it("shows a read-only empty state without mutation actions", async () => {
    mocks.apiFetch.mockResolvedValue({ data: null });
    renderPanel(false);
    expect(await screen.findByText("No weekly governance summary yet")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Generate summary/i })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Approve summary/i })).not.toBeInTheDocument();
  });

  it("generates and approves a draft while preventing duplicate actions", async () => {
    let generated = false;
    mocks.apiFetch.mockImplementation(
      async (path: string | undefined, options?: { method?: string }) => {
        if (!path) return { data: null };
        if (path === "/governance/weekly-summary" && !options) return { data: null };
        if (path?.endsWith("/generate")) {
          generated = true;
          return { data: draft };
        }
        if (path?.endsWith("/approve")) {
          return {
            data: {
              ...draft,
              status: "approved",
              approved_at: "2026-07-14T09:00:00Z",
              approved_by_name: "Alex Leader",
            },
          };
        }
        if (path?.startsWith("/governance/weekly-summaries")) {
          return { data: generated ? [draft] : [] };
        }
        throw new Error(`Unexpected request: ${path}`);
      },
    );
    renderPanel(true);

    const generateButtons = await screen.findAllByRole("button", { name: /Generate summary/i });
    fireEvent.click(generateButtons.at(-1)!);
    expect(await screen.findByText("Portfolio governance remains stable.")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: /Approve summary/i }));

    await waitFor(() =>
      expect(screen.getByText("Official governance summary")).toBeInTheDocument(),
    );
    expect(screen.queryByRole("button", { name: /Approve summary/i })).not.toBeInTheDocument();
    expect(mocks.apiFetch).toHaveBeenCalledWith(`/governance/weekly-summary/${draft.id}/approve`, {
      method: "POST",
    });
  });

  it("matches the charter document workflow and exports PDF and DOCX", async () => {
    mocks.apiFetch.mockImplementation(async (path?: string) => {
      if (path === "/governance/weekly-summary") return { data: draft };
      if (path?.startsWith("/governance/weekly-summaries")) return { data: [draft] };
      return { data: null };
    });
    mocks.apiFetchBlob.mockResolvedValue(new Blob(["document"]));
    const createObjectURL = vi.spyOn(URL, "createObjectURL").mockReturnValue("blob:test");
    const revokeObjectURL = vi.spyOn(URL, "revokeObjectURL").mockImplementation(() => undefined);
    const click = vi
      .spyOn(HTMLAnchorElement.prototype, "click")
      .mockImplementation(() => undefined);

    renderPanel(true);
    expect(await screen.findByText("Portfolio governance remains stable.")).toBeInTheDocument();
    expect(
      screen.getByText(/AI-generated drafts, approval workflow, version history, and exports/),
    ).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "PDF" }));
    await waitFor(() =>
      expect(mocks.apiFetchBlob).toHaveBeenCalledWith(
        `/governance/weekly-summary/${draft.id}/export.pdf`,
      ),
    );
    fireEvent.click(screen.getByRole("button", { name: "DOCX" }));
    await waitFor(() =>
      expect(mocks.apiFetchBlob).toHaveBeenCalledWith(
        `/governance/weekly-summary/${draft.id}/export.docx`,
      ),
    );

    click.mockRestore();
    revokeObjectURL.mockRestore();
    createObjectURL.mockRestore();
  });

  it("isolates a summary API failure and offers retry", async () => {
    mocks.apiFetch.mockImplementation((path?: string) =>
      path ? Promise.reject(new Error("Service unavailable")) : Promise.resolve({ data: null }),
    );
    renderPanel();
    expect(await screen.findByText("Weekly summary is unavailable")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Retry" })).toBeInTheDocument();
  });
});
