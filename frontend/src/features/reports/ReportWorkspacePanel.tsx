import { useEffect, useState } from "react";

import { Card, SectionHeader, StatusPill } from "@/components/bsg/widgets";
import { DeliveryMarkdown } from "@/components/delivery/delivery-markdown";
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from "@/components/ui/alert-dialog";
import { Skeleton } from "@/components/ui/skeleton";
import { ReportExportButtons } from "@/components/bsg/reports";
import { ApiError } from "@/lib/api";
import { ReportEvidencePanel } from "@/features/reports/ReportEvidencePanel";
import {
  allowedActionsForStatus,
  isCommunicationReadOnly,
  statusLabel,
  statusPillFor,
  typeLabel,
} from "@/features/reports/report-status";
import {
  formatReportDate,
  resolveCommunicationBody,
} from "@/features/reports/report-utils";
import type {
  CommunicationCapabilities,
  CommunicationDetail,
} from "@/types/communications";

export interface ReportWorkspacePanelProps {
  report: CommunicationDetail | null;
  projectName?: string | null;
  isLoading: boolean;
  isError: boolean;
  errorMessage: string | null;
  onRetry: () => void;
  capabilities: CommunicationCapabilities;
  onGenerateNew?: () => void;
  isGenerating?: boolean;
  /** Persist subject/body without status change. */
  onSaveEdits?: (args: { subject: string; body: string }) => Promise<void>;
  /** Submit for review (writes body_approved, status in_review). */
  onSubmitReview?: (body: string) => Promise<void>;
  onApprove?: (body: string) => Promise<void>;
  onReject?: () => Promise<void>;
  onSend?: () => Promise<void>;
  actionPending?: boolean;
  /** Banner after approve succeeded but send failed. */
  sendPartialFailure?: string | null;
  onDismissSendPartialFailure?: () => void;
  /** Optional linked Phase 18.3 platform report for shared exports. */
  platformReportId?: string | null;
}

type ConfirmKind = "approve" | "reject" | "send" | null;

function WorkspaceSkeleton() {
  return (
    <Card className="lg:col-span-2" aria-busy="true" aria-label="Loading report">
      <Skeleton className="h-4 w-2/3" />
      <Skeleton className="mt-2 h-3 w-1/3" />
      <div className="mt-4 space-y-3 rounded-md border border-border bg-elevated p-5">
        <Skeleton className="h-3 w-full" />
        <Skeleton className="h-3 w-11/12" />
        <Skeleton className="h-3 w-4/5" />
      </div>
    </Card>
  );
}

function EvidenceIndicator({ count }: { count: number }) {
  if (count <= 0) return null;
  const noun = count === 1 ? "source" : "sources";
  return (
    <span className="inline-flex items-center gap-1 rounded-full border border-border bg-secondary px-2 py-0.5 text-[10px] font-medium text-muted-foreground">
      Evidence-backed · {count} {noun}
    </span>
  );
}

function actionErrorMessage(error: unknown): string {
  if (error instanceof ApiError) {
    if (error.status === 409 && error.code === "INVALID_COMMUNICATION_TRANSITION") {
      return "This report’s status changed. Refreshing details.";
    }
    if (error.status === 403) {
      return "You do not have permission for this action.";
    }
    return error.message;
  }
  if (error instanceof Error) return error.message;
  return "Action failed.";
}

/**
 * Report workspace — governed human review: edit, review, approve, reject, send.
 */
export function ReportWorkspacePanel({
  report,
  projectName,
  isLoading,
  isError,
  errorMessage,
  onRetry,
  capabilities,
  onGenerateNew,
  isGenerating = false,
  onSaveEdits,
  onSubmitReview,
  onApprove,
  onReject,
  onSend,
  actionPending = false,
  sendPartialFailure = null,
  onDismissSendPartialFailure,
  platformReportId = null,
}: ReportWorkspacePanelProps) {
  const [editing, setEditing] = useState(false);
  const [draftSubject, setDraftSubject] = useState("");
  const [draftBody, setDraftBody] = useState("");
  const [confirm, setConfirm] = useState<ConfirmKind>(null);
  const [localError, setLocalError] = useState<string | null>(null);

  useEffect(() => {
    if (!report) {
      setEditing(false);
      return;
    }
    setDraftSubject(report.subject);
    setDraftBody(resolveCommunicationBody(report));
    setEditing(false);
    setLocalError(null);
  }, [report?.id, report?.status, report?.updated_at]);

  if (!report && !isLoading && !isError) {
    return (
      <Card className="lg:col-span-2">
        <SectionHeader title="Report workspace" sub="Select a report to review its content." />
        <div className="rounded-md border border-border bg-elevated p-5 text-sm text-muted-foreground">
          Select a report to review its content.
        </div>
      </Card>
    );
  }

  if (isLoading && !report) return <WorkspaceSkeleton />;

  if (isError && !report) {
    return (
      <Card className="lg:col-span-2">
        <SectionHeader title="Report workspace" />
        <div className="rounded-md border border-border bg-elevated p-5 text-sm">
          <p className="text-muted-foreground">{errorMessage ?? "Failed to load this report."}</p>
          <button
            type="button"
            onClick={onRetry}
            className="mt-3 rounded border border-border px-2.5 py-1 text-[11px] font-medium"
          >
            Retry
          </button>
        </div>
      </Card>
    );
  }

  if (!report) return <WorkspaceSkeleton />;

  const actions = allowedActionsForStatus(report.status);
  const readOnly = isCommunicationReadOnly(report.status);
  const project = projectName ?? report.project_name ?? "Project";
  const body = resolveCommunicationBody(report);
  const evidenceCount = report.evidence_links?.length ?? 0;
  const busy = actionPending;

  const canEdit = actions.has("edit") && capabilities.canReviewCommunications;
  const canSubmit =
    actions.has("submit_review") && capabilities.canReviewCommunications && Boolean(onSubmitReview);
  const canApprove =
    actions.has("approve") && capabilities.canApproveCommunications && Boolean(onApprove);
  const canReject =
    actions.has("reject") && capabilities.canRejectCommunications && Boolean(onReject);
  const canSend = actions.has("send") && capabilities.canSendCommunications && Boolean(onSend);
  const canGenerateNew =
    actions.has("generate_new") && capabilities.canGenerateCommunications && Boolean(onGenerateNew);

  const metaParts = [
    typeLabel(report.comm_type),
    `Created ${formatReportDate(report.created_at)}`,
    `Updated ${formatReportDate(report.updated_at)}`,
  ];
  if (report.sent_at) metaParts.push(`Sent ${formatReportDate(report.sent_at)}`);

  async function runAction(fn: () => Promise<void>) {
    setLocalError(null);
    try {
      await fn();
      setConfirm(null);
      setEditing(false);
    } catch (error) {
      setLocalError(actionErrorMessage(error));
      if (
        error instanceof ApiError &&
        error.status === 409 &&
        error.code === "INVALID_COMMUNICATION_TRANSITION"
      ) {
        onRetry();
      }
      throw error;
    }
  }

  return (
    <Card className="lg:col-span-2">
      <SectionHeader
        title={editing ? draftSubject || report.subject : report.subject}
        sub={`${project} · ${metaParts.join(" · ")}`}
        right={
          <div className="flex flex-wrap items-center gap-2">
            <StatusPill status={statusPillFor(report.status)} />
            <span className="text-[10px] text-muted-foreground">{statusLabel(report.status)}</span>
            <EvidenceIndicator count={evidenceCount} />
            {report.status === "sent" ? (
              <span className="text-[10px] font-medium text-muted-foreground">Sent to client</span>
            ) : null}
          </div>
        }
      />

      {editing ? (
        <label className="mb-3 block text-xs">
          <span className="text-muted-foreground">Subject</span>
          <input
            className="mt-1 w-full rounded border border-border bg-elevated px-2 py-1.5 text-sm"
            value={draftSubject}
            disabled={busy}
            onChange={(e) => setDraftSubject(e.target.value)}
          />
        </label>
      ) : null}

      {isGenerating ? (
        <div
          className="mb-3 rounded border border-border bg-elevated px-3 py-2 text-[11px] text-muted-foreground"
          data-testid="workspace-generating"
        >
          Generating report…
        </div>
      ) : null}

      {report.generation_warning || report.generation_mode === "fallback" ? (
        <div
          className="mb-3 rounded border border-[color:var(--warning,theme(colors.amber.500))] bg-elevated px-3 py-2 text-[11px] text-muted-foreground"
          data-testid="generation-warning"
          role="status"
        >
          <p className="font-medium text-foreground">Evidence-backed draft (AI unavailable)</p>
          <p className="mt-1">
            {report.generation_warning ??
              "The AI provider was unavailable or timed out. A temporary draft was created from available evidence."}{" "}
            Review this content carefully before approval — it is not a fully AI-generated narrative.
          </p>
        </div>
      ) : null}

      {sendPartialFailure ? (
        <div
          className="mb-3 rounded border border-border bg-elevated px-3 py-2 text-[11px]"
          data-testid="send-partial-failure"
          role="alert"
        >
          <p>{sendPartialFailure}</p>
          <button
            type="button"
            className="mt-1 underline"
            onClick={onDismissSendPartialFailure}
          >
            Dismiss
          </button>
        </div>
      ) : null}

      {localError ? (
        <p className="mb-3 text-[11px] text-[color:var(--danger)]" role="alert">
          {localError}
        </p>
      ) : null}

      {!readOnly && !capabilities.isReportsReadOnly ? (
        <div
          className="mb-3 flex flex-wrap gap-2"
          data-testid="lifecycle-actions"
        >
          {canEdit && !editing ? (
            <button
              type="button"
              disabled={busy}
              onClick={() => {
                setDraftSubject(report.subject);
                setDraftBody(resolveCommunicationBody(report));
                setEditing(true);
                setLocalError(null);
              }}
              className="rounded border border-border px-2.5 py-1 text-[11px] font-medium disabled:opacity-50"
            >
              Edit
            </button>
          ) : null}
          {editing ? (
            <>
              <button
                type="button"
                disabled={busy || !draftSubject.trim() || !draftBody.trim()}
                onClick={() =>
                  void runAction(async () => {
                    if (!onSaveEdits) return;
                    await onSaveEdits({
                      subject: draftSubject.trim(),
                      body: draftBody.trim(),
                    });
                  }).catch(() => undefined)
                }
                className="rounded border border-border px-2.5 py-1 text-[11px] font-medium disabled:opacity-50"
              >
                {busy ? "Saving…" : "Save"}
              </button>
              <button
                type="button"
                disabled={busy}
                onClick={() => {
                  setEditing(false);
                  setDraftSubject(report.subject);
                  setDraftBody(resolveCommunicationBody(report));
                  setLocalError(null);
                }}
                className="rounded border border-border px-2.5 py-1 text-[11px] disabled:opacity-50"
              >
                Cancel
              </button>
            </>
          ) : null}
          {canSubmit ? (
            <button
              type="button"
              disabled={busy || !(editing ? draftBody.trim() : body.trim())}
              onClick={() =>
                void runAction(async () => {
                  const content = editing ? draftBody.trim() : body.trim();
                  await onSubmitReview!(content);
                }).catch(() => undefined)
              }
              className="rounded border border-border px-2.5 py-1 text-[11px] font-medium disabled:opacity-50"
            >
              {report.status === "draft" ? "Submit for review" : "Update review"}
            </button>
          ) : null}
          {canApprove ? (
            <button
              type="button"
              disabled={busy}
              onClick={() => setConfirm("approve")}
              className="rounded bg-[color:var(--brand)] px-2.5 py-1 text-[11px] font-medium text-[color:var(--brand-foreground)] disabled:opacity-50"
            >
              Approve
            </button>
          ) : null}
          {canReject ? (
            <button
              type="button"
              disabled={busy}
              onClick={() => setConfirm("reject")}
              className="rounded border border-border px-2.5 py-1 text-[11px] font-medium disabled:opacity-50"
            >
              Reject
            </button>
          ) : null}
          {canSend ? (
            <button
              type="button"
              disabled={busy}
              onClick={() => setConfirm("send")}
              className="rounded bg-[color:var(--brand)] px-2.5 py-1 text-[11px] font-medium text-[color:var(--brand-foreground)] disabled:opacity-50"
            >
              Send to client
            </button>
          ) : null}
          {canGenerateNew ? (
            <button
              type="button"
              disabled={busy}
              onClick={onGenerateNew}
              className="rounded bg-[color:var(--brand)] px-2.5 py-1 text-[11px] font-medium text-[color:var(--brand-foreground)] disabled:opacity-50"
            >
              Generate new
            </button>
          ) : null}
        </div>
      ) : canGenerateNew ? (
        <div className="mb-3">
          <button
            type="button"
            onClick={onGenerateNew}
            className="rounded bg-[color:var(--brand)] px-2.5 py-1 text-[11px] font-medium text-[color:var(--brand-foreground)]"
          >
            Generate new
          </button>
        </div>
      ) : null}

      {editing ? (
        <textarea
          className="min-h-[240px] w-full rounded-md border border-border bg-elevated p-5 text-sm leading-6"
          value={draftBody}
          disabled={busy}
          onChange={(e) => setDraftBody(e.target.value)}
          aria-label="Report body"
        />
      ) : (
        <div
          className="prose-invert max-w-none rounded-md border border-border bg-elevated p-5 text-sm leading-6"
          data-readonly={readOnly ? "true" : "false"}
        >
          {body ? (
            <DeliveryMarkdown content={body} />
          ) : (
            <p className="text-muted-foreground">This report has no body content yet.</p>
          )}
        </div>
      )}

      <ReportEvidencePanel links={report.evidence_links ?? []} />
      {platformReportId ? <ReportExportButtons reportId={platformReportId} /> : null}

      <AlertDialog open={confirm === "approve"} onOpenChange={(open) => !open && setConfirm(null)}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>Approve this report?</AlertDialogTitle>
            <AlertDialogDescription>
              Approval marks the report as ready. It will not be visible to the client until you
              explicitly send it.
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel disabled={busy}>Cancel</AlertDialogCancel>
            <AlertDialogAction
              disabled={busy}
              onClick={(e) => {
                e.preventDefault();
                void runAction(async () => {
                  const content = editing ? draftBody.trim() : body.trim();
                  await onApprove!(content);
                }).catch(() => undefined);
              }}
            >
              {busy ? "Approving…" : "Approve"}
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>

      <AlertDialog open={confirm === "reject"} onOpenChange={(open) => !open && setConfirm(null)}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>Reject this report?</AlertDialogTitle>
            <AlertDialogDescription>
              The report will move to rejected and remain unavailable to clients. You can generate a
              new draft afterward.
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel disabled={busy}>Cancel</AlertDialogCancel>
            <AlertDialogAction
              disabled={busy}
              onClick={(e) => {
                e.preventDefault();
                void runAction(async () => {
                  await onReject!();
                }).catch(() => undefined);
              }}
            >
              {busy ? "Rejecting…" : "Reject"}
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>

      <AlertDialog open={confirm === "send"} onOpenChange={(open) => !open && setConfirm(null)}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>Send to client?</AlertDialogTitle>
            <AlertDialogDescription>
              This will publish the report to the client’s reports area. Sending is separate from
              approval and cannot be undone from this workflow.
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel disabled={busy}>Cancel</AlertDialogCancel>
            <AlertDialogAction
              disabled={busy}
              onClick={(e) => {
                e.preventDefault();
                void runAction(async () => {
                  await onSend!();
                }).catch(() => undefined);
              }}
            >
              {busy ? "Sending…" : "Send to client"}
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </Card>
  );
}
