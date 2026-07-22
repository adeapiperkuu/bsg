import { useState } from "react";
import { Button } from "@/components/ui/button";
import { Card, SectionHeader } from "@/components/bsg/widgets";
import type { ReportInstance } from "@/types/reports";

export function ReportApprovalActions({
  report,
  onSubmit,
  onApprove,
  onReject,
  onDistribute,
  busy,
}: {
  report: ReportInstance | null | undefined;
  onSubmit?: () => Promise<void> | void;
  onApprove?: () => Promise<void> | void;
  onReject?: (reason: string) => Promise<void> | void;
  onDistribute?: () => Promise<void> | void;
  busy?: boolean;
}) {
  const [reason, setReason] = useState("");
  if (!report) {
    return (
      <Card>
        <SectionHeader title="Approval" sub="No report selected" />
      </Card>
    );
  }
  return (
    <Card>
      <SectionHeader
        title="Approval Workflow"
        sub="Approve does not distribute. Distribution is a separate step."
      />
      <div className="flex flex-wrap gap-2">
        {report.status === "draft" ? (
          <Button disabled={busy} onClick={() => void onSubmit?.()}>
            Submit for review
          </Button>
        ) : null}
        {report.status === "in_review" ? (
          <>
            <Button disabled={busy} onClick={() => void onApprove?.()}>
              Approve
            </Button>
            <Button
              variant="destructive"
              disabled={busy || reason.trim().length === 0}
              onClick={() => void onReject?.(reason.trim())}
            >
              Reject
            </Button>
            <input
              className="min-w-[220px] flex-1 rounded-md border border-[color:var(--border)] bg-transparent px-2 py-1 text-sm"
              placeholder="Rejection reason"
              value={reason}
              onChange={(e) => setReason(e.target.value)}
              aria-label="Rejection reason"
            />
          </>
        ) : null}
        {report.status === "approved" ? (
          <Button disabled={busy} onClick={() => void onDistribute?.()}>
            Mark distributed
          </Button>
        ) : null}
      </div>
    </Card>
  );
}
