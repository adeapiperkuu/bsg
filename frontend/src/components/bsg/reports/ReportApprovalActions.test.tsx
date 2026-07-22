import { describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import { ReportApprovalActions } from "@/components/bsg/reports/ReportApprovalActions";
import { queryKeys } from "@/lib/queries/keys";
import type { ReportInstance } from "@/types/reports";

const baseReport: ReportInstance = {
  id: "r1",
  org_id: "o1",
  project_id: null,
  template_id: "t1",
  template_key: "client.weekly_status",
  template_version: "1.0.0",
  audience: "client",
  domain: "client",
  status: "in_review",
  title: "Weekly",
  body_markdown: "Body",
  content_payload: {},
  provenance: {},
  limitations: [],
  period_start: null,
  period_end: null,
  has_ai_sections: true,
  evidence_fingerprint: null,
  generation_mode: "hybrid",
  generated_by_user_id: null,
  generated_by_job_id: null,
  reviewed_by: null,
  reviewed_at: null,
  approved_by: null,
  approved_at: null,
  rejected_by: null,
  rejected_at: null,
  rejection_reason: null,
  distributed_at: null,
  created_at: new Date().toISOString(),
  updated_at: new Date().toISOString(),
};

describe("report query keys", () => {
  it("namespaces platform report keys", () => {
    expect(queryKeys.reportDetail("abc")[0]).toBe("reports");
    expect(queryKeys.reportTemplates({ domain: "client" })[1]).toBe("templates");
    expect(queryKeys.reportJob("job-1")).toEqual(["reports", "jobs", "job-1"]);
  });
});

describe("ReportApprovalActions", () => {
  it("approve does not call distribute", async () => {
    const user = userEvent.setup();
    const onApprove = vi.fn();
    const onDistribute = vi.fn();
    render(
      <ReportApprovalActions
        report={baseReport}
        onApprove={onApprove}
        onDistribute={onDistribute}
      />,
    );
    await user.click(screen.getByRole("button", { name: "Approve" }));
    expect(onApprove).toHaveBeenCalledTimes(1);
    expect(onDistribute).not.toHaveBeenCalled();
    expect(screen.getByText(/Approve does not distribute/i)).toBeInTheDocument();
  });
});
