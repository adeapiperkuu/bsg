import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ReportsPage } from "@/features/reports/ReportsPage";
import { ReportWorkspacePanel } from "@/features/reports/ReportWorkspacePanel";
import { deriveCommunicationCapabilities } from "@/features/reports/reportPermissions";
import { resolveCommunicationBody } from "@/features/reports/report-utils";
import { inboxFilterToApiStatus } from "@/features/reports/report-status";
import { Route as ReportsRoute } from "@/routes/reports";
import { Route as ClientReportsRoute } from "@/routes/client.reports";
import type { FileRoutesByFullPath } from "@/routeTree.gen";
import type { CommunicationDetail, CommunicationListItem } from "@/types/communications";

const mocks = vi.hoisted(() => ({
  listCommunications: vi.fn(),
  getCommunication: vi.fn(),
  useSearch: vi.fn(() => ({})),
  navigate: vi.fn(),
  authUser: {
    id: "u1",
    email: "dm@example.com",
    full_name: "DM",
    role: "delivery_manager" as const,
    org_id: "org1",
    is_active: true,
    organisation: null,
    permissions: {
      can_manage_projects: true,
      can_approve_communications: true,
      can_manage_metric_configurations: false,
      can_view_cross_client_portfolio: false,
      can_manage_users: false,
      can_manage_organisations: false,
    },
  },
}));

vi.mock("@/lib/api", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/lib/api")>();
  return {
    ...actual,
    listCommunications: mocks.listCommunications,
    getCommunication: mocks.getCommunication,
  };
});

vi.mock("@tanstack/react-router", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@tanstack/react-router")>();
  return {
    ...actual,
    getRouteApi: () => ({
      useSearch: mocks.useSearch,
    }),
    useNavigate: () => mocks.navigate,
  };
});

vi.mock("@/stores/useAuthStore", () => ({
  useAuthStore: (selector: (s: { user: typeof mocks.authUser }) => unknown) =>
    selector({ user: mocks.authUser }),
}));

vi.mock("@/components/delivery/delivery-markdown", () => ({
  DeliveryMarkdown: ({ content }: { content: string }) => (
    <div data-testid="delivery-markdown">{content}</div>
  ),
}));

const listItem: CommunicationListItem = {
  id: "comm-1",
  project_id: "proj-1",
  project_name: "Project Alpha",
  org_id: "org1",
  org_name: "Northwind Analytics",
  comm_type: "weekly_summary",
  subject: "Weekly Delivery Summary — Project Alpha",
  status: "draft",
  created_at: "2026-07-16T10:00:00Z",
  updated_at: "2026-07-16T12:00:00Z",
  sent_at: null,
  evidence_link_count: 4,
};

const listItem2: CommunicationListItem = {
  ...listItem,
  id: "comm-2",
  project_id: "proj-2",
  subject: "Helios Bank — Schema Progress",
  project_name: "Helios Bank",
  org_id: "org2",
  org_name: "Helix Mobility",
  status: "in_review",
};

const detail: CommunicationDetail = {
  id: "comm-1",
  project_id: "proj-1",
  project_name: "Project Alpha",
  comm_type: "weekly_summary",
  subject: "Weekly Delivery Summary — Project Alpha",
  body_draft: "Draft body text",
  body_approved: "Approved body text",
  status: "draft",
  drafted_by_agent: "client_interaction_agent",
  reviewed_by: null,
  reviewed_at: null,
  approved_by: null,
  approved_at: null,
  sent_at: null,
  created_at: "2026-07-16T10:00:00Z",
  updated_at: "2026-07-16T12:00:00Z",
  evidence_links: [
    {
      source_table: "throughput_snapshots",
      source_row_id: "e1",
      description: "Throughput",
    },
  ],
};

function renderPage() {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return render(
    <QueryClientProvider client={client}>
      <ReportsPage />
    </QueryClientProvider>,
  );
}

describe("filter mapping", () => {
  it("maps UI filters to API status values", () => {
    expect(inboxFilterToApiStatus("all")).toBeUndefined();
    expect(inboxFilterToApiStatus("draft")).toBe("draft");
    expect(inboxFilterToApiStatus("in_review")).toBe("in_review");
    expect(inboxFilterToApiStatus("approved")).toBe("approved");
    expect(inboxFilterToApiStatus("sent")).toBe("sent");
    expect(inboxFilterToApiStatus("rejected")).toBe("rejected");
  });
});

describe("resolveCommunicationBody", () => {
  it("prefers non-empty body_approved over body_draft", () => {
    expect(
      resolveCommunicationBody({ body_approved: "Approved", body_draft: "Draft" }),
    ).toBe("Approved");
    expect(resolveCommunicationBody({ body_approved: "  ", body_draft: "Draft" })).toBe("Draft");
    expect(resolveCommunicationBody({ body_approved: null, body_draft: "Draft" })).toBe("Draft");
  });
});

describe("PM /reports live inbox", () => {
  beforeEach(() => {
    mocks.listCommunications.mockReset();
    mocks.getCommunication.mockReset();
    mocks.useSearch.mockReturnValue({});
    mocks.listCommunications.mockResolvedValue({
      data: [listItem, listItem2],
      pagination: { limit: 30, offset: 0, total: 2, items: 2, has_more: false },
    });
    mocks.getCommunication.mockResolvedValue(detail);
  });

  it("wires ReportsPage as the route component", () => {
    expect(ReportsRoute.options.component).toBe(ReportsPage);
  });

  it("runs list query on page load and does not fetch detail without selection settle", async () => {
    renderPage();
    await waitFor(() => expect(mocks.listCommunications).toHaveBeenCalled());
    expect(mocks.listCommunications.mock.calls[0][0]).toMatchObject({
      limit: 30,
      offset: 0,
    });
    // After auto-select, detail loads once for the first row — not for every row.
    await waitFor(() => expect(mocks.getCommunication).toHaveBeenCalledTimes(1));
    expect(mocks.getCommunication).toHaveBeenCalledWith("comm-1");
  });

  it("renders subject and project name in the inbox", async () => {
    renderPage();
    await waitFor(() => {
      expect(screen.getByText("Weekly Delivery Summary — Project Alpha")).toBeInTheDocument();
    });
    expect(screen.getByText("Project Alpha")).toBeInTheDocument();
    expect(screen.getByText(/Weekly Status/i)).toBeInTheDocument();
  });

  it("loads detail when selecting another row", async () => {
    const user = userEvent.setup();
    renderPage();
    await waitFor(() => expect(screen.getByText("Helios Bank")).toBeInTheDocument());

    // Expand the Helios project accordion, then select the report.
    await user.click(screen.getByRole("button", { name: /Helios Bank/i }));
    await waitFor(() =>
      expect(screen.getByText("Helios Bank — Schema Progress")).toBeInTheDocument(),
    );

    mocks.getCommunication.mockResolvedValue({
      ...detail,
      id: "comm-2",
      subject: "Helios Bank — Schema Progress",
      body_approved: null,
      body_draft: "Helios draft body",
      status: "in_review",
    });

    await user.click(screen.getByRole("button", { name: /Helios Bank — Schema Progress/i }));
    await waitFor(() => expect(mocks.getCommunication).toHaveBeenCalledWith("comm-2"));
    await waitFor(() => {
      expect(screen.getByTestId("delivery-markdown")).toHaveTextContent("Helios draft body");
    });
  });

  it("does not block the workspace layout while the list loads", () => {
    mocks.listCommunications.mockReturnValue(new Promise(() => {}));
    renderPage();
    expect(screen.getByText("Report workspace")).toBeInTheDocument();
    expect(
      screen.getAllByText("Select a report to review its content.").length,
    ).toBeGreaterThan(0);
    expect(screen.getByLabelText("Loading reports")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Generate Report" })).toBeInTheDocument();
  });

  it("uses approved body in the workspace and removes mock confidence badge", async () => {
    renderPage();
    await waitFor(() => {
      expect(screen.getByTestId("delivery-markdown")).toHaveTextContent("Approved body text");
    });
    expect(screen.queryByText(/91%/)).not.toBeInTheDocument();
    expect(screen.getByText(/Evidence-backed · 1 source/i)).toBeInTheDocument();
  });

  it("keeps /client/reports on a separate route", () => {
    const pmPath: keyof FileRoutesByFullPath = "/reports";
    const clientPath: keyof FileRoutesByFullPath = "/client/reports";
    expect(pmPath).not.toBe(clientPath);
    expect(ReportsRoute.options.component).toBe(ReportsPage);
    expect(ClientReportsRoute.options.component).not.toBe(ReportsPage);
  });
});

describe("workspace read-only statuses", () => {
  const caps = deriveCommunicationCapabilities(mocks.authUser);

  it("marks sent reports read-only without lifecycle placeholder", () => {
    const sent: CommunicationDetail = {
      ...detail,
      status: "sent",
      sent_at: "2026-07-10T16:00:00Z",
      body_approved: "Sent body",
    };
    render(
      <ReportWorkspacePanel
        report={sent}
        projectName="Aurora"
        isLoading={false}
        isError={false}
        errorMessage={null}
        onRetry={() => {}}
        capabilities={caps}
      />,
    );
    expect(document.querySelector('[data-readonly="true"]')).toBeTruthy();
    expect(screen.queryByTestId("lifecycle-actions-placeholder")).not.toBeInTheDocument();
    expect(screen.queryByText(/91%/)).not.toBeInTheDocument();
  });

  it("shows Generate new for rejected when user can generate", () => {
    const rejected: CommunicationDetail = { ...detail, status: "rejected" };
    render(
      <ReportWorkspacePanel
        report={rejected}
        projectName="Helios"
        isLoading={false}
        isError={false}
        errorMessage={null}
        onRetry={() => {}}
        capabilities={caps}
        onGenerateNew={() => {}}
      />,
    );
    expect(screen.getByRole("button", { name: "Generate new" })).toBeInTheDocument();
    expect(document.querySelector('[data-readonly="true"]')).toBeTruthy();
  });
});
