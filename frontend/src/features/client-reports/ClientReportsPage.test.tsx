import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ClientReportsPage } from "@/features/client-reports/ClientReportsPage";
import type { CommunicationDetail, CommunicationListItem } from "@/types/communications";

const mocks = vi.hoisted(() => ({
  listClientCommunications: vi.fn(),
  getCommunication: vi.fn(),
}));

vi.mock("@/lib/api", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/lib/api")>();
  return {
    ...actual,
    listClientCommunications: mocks.listClientCommunications,
    getCommunication: mocks.getCommunication,
  };
});

vi.mock("@/components/delivery/delivery-markdown", () => ({
  DeliveryMarkdown: ({ content }: { content: string }) => (
    <div data-testid="delivery-markdown">{content}</div>
  ),
}));

const listItem: CommunicationListItem = {
  id: "sent-1",
  project_id: "proj-1",
  project_name: "Helios Bank",
  org_id: "org1",
  org_name: "Helix Mobility",
  comm_type: "weekly_summary",
  subject: "Weekly Delivery Summary — Helios Bank",
  status: "sent",
  created_at: "2026-07-10T10:00:00Z",
  updated_at: "2026-07-10T16:00:00Z",
  sent_at: "2026-07-10T16:00:00Z",
  evidence_link_count: 0,
};

const detail: CommunicationDetail = {
  id: "sent-1",
  project_id: "proj-1",
  project_name: "Helios Bank",
  comm_type: "weekly_summary",
  subject: "Weekly Delivery Summary — Helios Bank",
  body_draft: "Approved public body",
  body_approved: "Approved public body",
  status: "sent",
  drafted_by_agent: "client_interaction_agent",
  reviewed_by: null,
  reviewed_at: null,
  approved_by: null,
  approved_at: null,
  sent_at: "2026-07-10T16:00:00Z",
  created_at: "2026-07-10T10:00:00Z",
  updated_at: "2026-07-10T16:00:00Z",
  evidence_links: [],
  generation_mode: null,
  generation_warning: null,
};

function renderPage() {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return render(
    <QueryClientProvider client={client}>
      <ClientReportsPage />
    </QueryClientProvider>,
  );
}

describe("ClientReportsPage", () => {
  beforeEach(() => {
    mocks.listClientCommunications.mockReset();
    mocks.getCommunication.mockReset();
    mocks.listClientCommunications.mockResolvedValue({
      data: [listItem],
      pagination: { limit: 30, offset: 0, total: 1, items: 1, has_more: false },
    });
    mocks.getCommunication.mockResolvedValue(detail);
  });

  it("loads only the client sent list and lazy detail", async () => {
    renderPage();
    await waitFor(() => expect(mocks.listClientCommunications).toHaveBeenCalled());
    expect(mocks.listClientCommunications.mock.calls[0][0]).toMatchObject({
      limit: 30,
      offset: 0,
    });
    await waitFor(() => expect(mocks.getCommunication).toHaveBeenCalledWith("sent-1"));
    expect(screen.getAllByText(/Weekly Delivery Summary — Helios Bank/i).length).toBeGreaterThan(0);
    expect(await screen.findByTestId("delivery-markdown")).toHaveTextContent(
      "Approved public body",
    );
  });

  it("shows empty state when no sent reports exist", async () => {
    mocks.listClientCommunications.mockResolvedValue({
      data: [],
      pagination: { limit: 30, offset: 0, total: 0, items: 0, has_more: false },
    });
    renderPage();
    expect(await screen.findByText("No reports yet")).toBeInTheDocument();
    expect(mocks.getCommunication).not.toHaveBeenCalled();
  });

  it("exposes no lifecycle mutation controls", async () => {
    renderPage();
    await waitFor(() => expect(screen.getByTestId("delivery-markdown")).toBeInTheDocument());
    expect(screen.queryByRole("button", { name: "Approve" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Send to client" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Generate Report" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Edit" })).not.toBeInTheDocument();
  });

  it("shows error and retry for list failures", async () => {
    const user = userEvent.setup();
    mocks.listClientCommunications.mockRejectedValueOnce(new Error("boom"));
    renderPage();
    expect(await screen.findByText(/boom|Failed to load/i)).toBeInTheDocument();
    mocks.listClientCommunications.mockResolvedValue({
      data: [listItem],
      pagination: { limit: 30, offset: 0, total: 1, items: 1, has_more: false },
    });
    await user.click(screen.getByRole("button", { name: "Retry" }));
    await waitFor(() => expect(mocks.listClientCommunications).toHaveBeenCalledTimes(2));
  });
});
