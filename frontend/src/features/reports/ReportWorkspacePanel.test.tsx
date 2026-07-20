import type { ComponentProps } from "react";
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { ReportEvidencePanel } from "@/features/reports/ReportEvidencePanel";
import { ReportWorkspacePanel } from "@/features/reports/ReportWorkspacePanel";
import { deriveCommunicationCapabilities } from "@/features/reports/reportPermissions";
import { ApiError } from "@/lib/api";
import type { MeUser as AuthMeUser } from "@/types/auth";
import type { CommunicationDetail } from "@/types/communications";

const dmCaps = deriveCommunicationCapabilities({
  id: "u1",
  email: "dm@example.com",
  full_name: "DM",
  role: "delivery_manager",
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
} as AuthMeUser);

const leadershipCaps = deriveCommunicationCapabilities({
  id: "u2",
  email: "lead@example.com",
  full_name: "Lead",
  role: "bsg_leadership",
  org_id: "org1",
  is_active: true,
  organisation: null,
  permissions: {
    can_manage_projects: false,
    can_approve_communications: false,
    can_manage_metric_configurations: false,
    can_view_cross_client_portfolio: true,
    can_manage_users: false,
    can_manage_organisations: false,
  },
} as AuthMeUser);

function detail(overrides: Partial<CommunicationDetail> = {}): CommunicationDetail {
  return {
    id: "comm-1",
    project_id: "proj-1",
    project_name: "Project Alpha",
    comm_type: "weekly_summary",
    subject: "Weekly Delivery Summary — Project Alpha",
    body_draft: "Draft body text",
    body_approved: null,
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
        description: "Latest throughput snapshot",
        created_at: "2026-07-16T09:00:00Z",
      },
    ],
    ...overrides,
  };
}

function renderWorkspace(
  report: CommunicationDetail,
  props: Partial<ComponentProps<typeof ReportWorkspacePanel>> = {},
) {
  const onApprove = props.onApprove ?? vi.fn().mockResolvedValue(undefined);
  const onReject = props.onReject ?? vi.fn().mockResolvedValue(undefined);
  const onSend = props.onSend ?? vi.fn().mockResolvedValue(undefined);
  const onSubmitReview = props.onSubmitReview ?? vi.fn().mockResolvedValue(undefined);
  const onSaveEdits = props.onSaveEdits ?? vi.fn().mockResolvedValue(undefined);
  const onGenerateNew = props.onGenerateNew ?? vi.fn();
  const onRetry = props.onRetry ?? vi.fn();

  render(
    <ReportWorkspacePanel
      report={report}
      projectName={report.project_name}
      isLoading={false}
      isError={false}
      errorMessage={null}
      onRetry={onRetry}
      capabilities={props.capabilities ?? dmCaps}
      onApprove={onApprove}
      onReject={onReject}
      onSend={onSend}
      onSubmitReview={onSubmitReview}
      onSaveEdits={onSaveEdits}
      onGenerateNew={onGenerateNew}
      sendPartialFailure={props.sendPartialFailure}
      {...props}
    />,
  );

  return { onApprove, onReject, onSend, onSubmitReview, onSaveEdits, onGenerateNew, onRetry };
}

describe("ReportWorkspacePanel lifecycle actions", () => {
  it("shows edit / submit / approve / reject for draft", () => {
    renderWorkspace(detail({ status: "draft" }));
    const actions = screen.getByTestId("lifecycle-actions");
    expect(within(actions).getByRole("button", { name: "Edit" })).toBeInTheDocument();
    expect(within(actions).getByRole("button", { name: "Submit for review" })).toBeInTheDocument();
    expect(within(actions).getByRole("button", { name: "Approve" })).toBeInTheDocument();
    expect(within(actions).getByRole("button", { name: "Reject" })).toBeInTheDocument();
  });

  it("shows send only for approved", () => {
    renderWorkspace(detail({ status: "approved", body_approved: "Approved body" }));
    const actions = screen.getByTestId("lifecycle-actions");
    expect(within(actions).getByRole("button", { name: "Send to client" })).toBeInTheDocument();
    expect(within(actions).queryByRole("button", { name: "Edit" })).not.toBeInTheDocument();
    expect(within(actions).queryByRole("button", { name: "Approve" })).not.toBeInTheDocument();
  });

  it("sent is read-only with Sent to client label", () => {
    renderWorkspace(
      detail({
        status: "sent",
        body_approved: "Published",
        sent_at: "2026-07-16T15:00:00Z",
      }),
    );
    expect(screen.getByText("Sent to client")).toBeInTheDocument();
    expect(screen.queryByTestId("lifecycle-actions")).not.toBeInTheDocument();
  });

  it("rejected shows Generate new and is read-only", async () => {
    const user = userEvent.setup();
    const { onGenerateNew } = renderWorkspace(detail({ status: "rejected" }));
    expect(screen.queryByRole("button", { name: "Edit" })).not.toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Generate new" }));
    expect(onGenerateNew).toHaveBeenCalled();
  });

  it("approve confirmation calls onApprove", async () => {
    const user = userEvent.setup();
    const { onApprove } = renderWorkspace(detail({ status: "in_review", body_approved: "Ready" }));
    await user.click(screen.getByRole("button", { name: "Approve" }));
    expect(screen.getByText(/Approval marks the report as ready/i)).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Approve" }));
    expect(onApprove).toHaveBeenCalledWith("Ready");
  });

  it("send confirmation explains client publish", async () => {
    const user = userEvent.setup();
    const { onSend } = renderWorkspace(
      detail({ status: "approved", body_approved: "Ready to send" }),
    );
    await user.click(screen.getByRole("button", { name: "Send to client" }));
    expect(
      screen.getByText(/publish the report to the client’s reports area/i),
    ).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Send to client" }));
    expect(onSend).toHaveBeenCalled();
  });

  it("preserves editor content when save fails", async () => {
    const user = userEvent.setup();
    const onSaveEdits = vi.fn().mockRejectedValue(new Error("network"));
    renderWorkspace(detail({ status: "draft" }), { onSaveEdits });
    await user.click(screen.getByRole("button", { name: "Edit" }));
    const textarea = screen.getByLabelText("Report body");
    await user.clear(textarea);
    await user.type(textarea, "Unsaved recovery text");
    await user.click(screen.getByRole("button", { name: "Save" }));
    expect(screen.getByDisplayValue("Unsaved recovery text")).toBeInTheDocument();
  });

  it("invalid transition refreshes detail", async () => {
    const user = userEvent.setup();
    const onRetry = vi.fn();
    const onApprove = vi
      .fn()
      .mockRejectedValue(new ApiError(409, "INVALID_COMMUNICATION_TRANSITION", "bad"));
    renderWorkspace(detail({ status: "draft" }), { onApprove, onRetry });
    await user.click(screen.getByRole("button", { name: "Approve" }));
    await user.click(screen.getByRole("button", { name: "Approve" }));
    expect(onRetry).toHaveBeenCalled();
    expect(screen.getByText(/status changed/i)).toBeInTheDocument();
  });

  it("shows approve-success/send-failure banner", () => {
    renderWorkspace(detail({ status: "approved", body_approved: "Ready" }), {
      sendPartialFailure: "Report approved, but sending failed. You can retry sending.",
    });
    expect(screen.getByTestId("send-partial-failure")).toHaveTextContent(
      "Report approved, but sending failed",
    );
  });

  it("hides lifecycle actions for leadership read-only", () => {
    renderWorkspace(detail({ status: "draft" }), { capabilities: leadershipCaps });
    expect(screen.queryByTestId("lifecycle-actions")).not.toBeInTheDocument();
  });
});

describe("ReportEvidencePanel", () => {
  it("expands and collapses evidence without showing raw IDs as primary labels", async () => {
    const user = userEvent.setup();
    render(
      <ReportEvidencePanel
        links={[
          {
            source_table: "throughput_snapshots",
            source_row_id: "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee",
            description: "Latest throughput snapshot",
          },
        ]}
      />,
    );
    expect(screen.queryByText(/Latest throughput snapshot/i)).not.toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: /Evidence \(1 source\)/i }));
    expect(screen.getByText("Latest throughput snapshot")).toBeInTheDocument();
    expect(screen.getByText("Throughput")).toBeInTheDocument();
    expect(
      screen.queryByText("aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"),
    ).not.toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: /Evidence \(1 source\)/i }));
    expect(screen.queryByText("Latest throughput snapshot")).not.toBeInTheDocument();
  });
});
