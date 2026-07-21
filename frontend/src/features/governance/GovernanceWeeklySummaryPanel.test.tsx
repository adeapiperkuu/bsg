import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { GovernanceWeeklySummaryPanel } from "@/features/governance/GovernanceWeeklySummaryPanel";
import { parseGovernanceSummarySections } from "@/features/governance/governance-weekly-summary";

const mocks = vi.hoisted(() => ({ apiFetch: vi.fn(), apiFetchBlob: vi.fn() }));

vi.mock("@/lib/api", () => ({
  apiFetch: mocks.apiFetch,
  apiFetchBlob: mocks.apiFetchBlob,
}));

vi.mock("sonner", () => ({
  toast: { success: vi.fn(), error: vi.fn(), message: vi.fn() },
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
  evidence_link_count: 0,
};

const olderListSummary = {
  id: "33333333-3333-3333-3333-333333333333",
  org_id: draft.org_id,
  summary_week: "2026-07-06",
  status: "approved" as const,
  generated_by_ai: true,
  approved_by: "44444444-4444-4444-4444-444444444444",
  approved_at: "2026-07-07T09:00:00Z",
  created_at: "2026-07-07T08:00:00Z",
  updated_at: "2026-07-07T09:00:00Z",
  evidence_link_count: 2,
  approved_by_name: "Alex Leader",
};

const olderDetailSummary = {
  ...olderListSummary,
  summary_text: "## 1. Executive Overview\nOlder approved summary",
  evidence_links: [
    {
      id: "55555555-5555-5555-5555-555555555555",
      org_id: draft.org_id,
      summary_id: olderListSummary.id,
      charter_id: null,
      source_type: "dependency",
      source_id: "66666666-6666-6666-6666-666666666666",
      created_at: "2026-07-07T08:10:00Z",
      label: "Older dependency",
      detail: "blocking",
      project_name: "Helios",
    },
    {
      id: "77777777-7777-7777-7777-777777777777",
      org_id: draft.org_id,
      summary_id: olderListSummary.id,
      charter_id: null,
      source_type: "action",
      source_id: "88888888-8888-8888-8888-888888888888",
      created_at: "2026-07-07T08:11:00Z",
      label: "Older action",
      detail: "open",
      project_name: "Helios",
    },
  ],
};

function renderPanel(canManage = false) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  const view = render(
    <QueryClientProvider client={client}>
      <GovernanceWeeklySummaryPanel canManage={canManage} />
    </QueryClientProvider>,
  );
  return { ...view, client };
}

function requestedPaths(): string[] {
  return mocks.apiFetch.mock.calls
    .map(([path]) => path)
    .filter((path): path is string => typeof path === "string");
}

function openVersionSelector() {
  fireEvent.mouseDown(screen.getByRole("combobox"), { button: 0, ctrlKey: false });
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

  it("fetches only the latest weekly summary on initial render", async () => {
    mocks.apiFetch.mockImplementation(async (path?: string) => {
      if (path === "/governance/weekly-summary") return { data: draft };
      throw new Error(`Unexpected request: ${path}`);
    });

    renderPanel();

    expect(await screen.findByText("Portfolio governance remains stable.")).toBeInTheDocument();
    expect(requestedPaths()).toEqual(["/governance/weekly-summary"]);
    expect(requestedPaths().some((path) => path.startsWith("/governance/weekly-summaries"))).toBe(
      false,
    );
  });

  it("loads weekly summary history once when the version selector is opened", async () => {
    const user = userEvent.setup();
    mocks.apiFetch.mockImplementation(async (path?: string) => {
      if (path === "/governance/weekly-summary") return { data: draft };
      if (path === "/governance/weekly-summaries?limit=12&include_detail=false") {
        return { data: [draft, olderListSummary] };
      }
      throw new Error(`Unexpected request: ${path}`);
    });

    renderPanel();
    expect(await screen.findByText("Portfolio governance remains stable.")).toBeInTheDocument();
    expect(requestedPaths().some((path) => path.startsWith("/governance/weekly-summaries"))).toBe(
      false,
    );

    openVersionSelector();

    await waitFor(() =>
      expect(
        requestedPaths().filter((path) => path.startsWith("/governance/weekly-summaries")),
      ).toHaveLength(1),
    );

    await user.keyboard("{Escape}");
    openVersionSelector();

    expect(
      requestedPaths().filter((path) => path.startsWith("/governance/weekly-summaries")),
    ).toHaveLength(1);
  });

  it("loads selected older weekly summary detail once while fresh", async () => {
    const user = userEvent.setup();
    mocks.apiFetch.mockImplementation(async (path?: string) => {
      if (path === "/governance/weekly-summary") return { data: draft };
      if (path === "/governance/weekly-summaries?limit=12&include_detail=false") {
        return { data: [draft, olderListSummary] };
      }
      if (path === `/governance/weekly-summary/${olderListSummary.id}`) {
        return { data: olderDetailSummary };
      }
      throw new Error(`Unexpected request: ${path}`);
    });

    renderPanel();
    expect(await screen.findByText("Portfolio governance remains stable.")).toBeInTheDocument();

    openVersionSelector();
    await waitFor(() =>
      expect(
        requestedPaths().filter((path) => path.startsWith("/governance/weekly-summaries")),
      ).toHaveLength(1),
    );
    await screen.findByRole("option", { name: /Jul 6, 2026/ });
    await user.selectOptions(screen.getByRole("combobox"), olderListSummary.id);

    expect(await screen.findByText("Older approved summary")).toBeInTheDocument();
    expect(
      requestedPaths().filter(
        (path) => path === `/governance/weekly-summary/${olderListSummary.id}`,
      ),
    ).toHaveLength(1);

    openVersionSelector();
    await user.selectOptions(screen.getByRole("combobox"), draft.id);
    openVersionSelector();
    await screen.findByRole("option", { name: /Jul 6, 2026/ });
    await user.selectOptions(screen.getByRole("combobox"), olderListSummary.id);

    expect(await screen.findByText("Older approved summary")).toBeInTheDocument();
    expect(
      requestedPaths().filter(
        (path) => path === `/governance/weekly-summary/${olderListSummary.id}`,
      ),
    ).toHaveLength(1);
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
    let approved = false;
    mocks.apiFetch.mockImplementation(
      async (path: string | undefined, options?: { method?: string }) => {
        if (!path) return { data: null };
        if (path.startsWith("/governance/jobs?")) return { data: [] };
        if (path === "/governance/jobs/job-weekly") {
          generated = true;
          return {
            data: {
              id: "job-weekly",
              status: "succeeded",
              progress_stage: "completed",
              progress_percent: 100,
              attempt_count: 1,
              max_attempts: 3,
              retryable: false,
              cancellable: false,
              error_message: null,
              result_record_type: "governance_weekly_summary",
              result_record_id: draft.id,
            },
          };
        }
        if (path === `/governance/weekly-summary/${draft.id}` && !options) {
          return { data: draft };
        }
        if (path === "/governance/weekly-summary" && !options) {
          if (!generated) return { data: null };
          return {
            data: approved
              ? {
                  ...draft,
                  status: "approved",
                  approved_at: "2026-07-14T09:00:00Z",
                  approved_by_name: "Alex Leader",
                }
              : draft,
          };
        }
        if (path?.endsWith("/generate")) {
          return {
            data: {
              job_id: "job-weekly",
              job_type: "weekly_summary_generate",
              status: "queued",
              deduplicated: false,
            },
          };
        }
        if (path?.endsWith("/approve")) {
          approved = true;
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
    const { client } = renderPanel(true);
    const invalidateSpy = vi.spyOn(client, "invalidateQueries");

    const generateButtons = await screen.findAllByRole("button", { name: /Generate summary/i });
    const generateButton = generateButtons.at(-1)!;
    await waitFor(() => expect(generateButton).toBeEnabled());
    fireEvent.click(generateButton);
    expect(await screen.findByText("Portfolio governance remains stable.")).toBeInTheDocument();
    expect(mocks.apiFetch).toHaveBeenCalledWith(`/governance/weekly-summary/${draft.id}`);
    fireEvent.click(screen.getByRole("button", { name: /Approve summary/i }));

    await waitFor(() =>
      expect(screen.getByText("Official governance summary")).toBeInTheDocument(),
    );
    expect(screen.queryByRole("button", { name: /Approve summary/i })).not.toBeInTheDocument();
    expect(mocks.apiFetch).toHaveBeenCalledWith(`/governance/weekly-summary/${draft.id}/approve`, {
      method: "POST",
    });
    expect(invalidateSpy).toHaveBeenCalledWith({
      queryKey: ["governance", "weekly-summary", "latest"],
    });
    expect(invalidateSpy).toHaveBeenCalledWith({
      queryKey: ["governance", "weekly-summary", "history"],
    });
    expect(invalidateSpy).toHaveBeenCalledWith({
      queryKey: ["governance", "weekly-summary", "detail", draft.id],
    });
  });

  it("matches the charter document workflow and exports PDF and DOCX", async () => {
    mocks.apiFetch.mockImplementation(async (path?: string) => {
      if (path === "/governance/weekly-summary") return { data: draft };
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
