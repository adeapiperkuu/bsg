import { Button } from "@/components/ui/button";
import type { GovernanceJob } from "@/types/governance";

const TERMINAL = new Set(["succeeded", "failed", "cancelled"]);

function statusLabel(job: GovernanceJob): string {
  if (job.status === "queued") return "Queued";
  if (job.status === "retry_scheduled") return "Retry scheduled";
  if (job.status === "cancellation_requested") return "Stopping at a safe checkpoint";
  if (job.status === "succeeded") return "Completed";
  if (job.status === "failed") return "Failed";
  if (job.status === "cancelled") return "Cancelled";
  const stages: Record<string, string> = {
    collecting_evidence: "Collecting evidence",
    building_context: "Building context",
    generating: "Generating",
    validating: "Validating",
    persisting: "Saving",
  };
  return stages[job.progress_stage] ?? "Running";
}

export function GovernanceJobProgress({
  job,
  onCancel,
  onRetry,
  busy,
}: {
  job: GovernanceJob | undefined;
  onCancel: () => void;
  onRetry: () => void;
  busy: boolean;
}) {
  if (!job) return null;
  return (
    <div className="rounded-md border border-border bg-elevated p-3 text-xs" role="status">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <span className="font-medium">{statusLabel(job)}</span>
        {!TERMINAL.has(job.status) ? (
          <span className="text-muted-foreground">{job.progress_percent}%</span>
        ) : null}
      </div>
      {job.status === "retry_scheduled" ? (
        <p className="mt-1 text-muted-foreground">
          Attempt {job.attempt_count} of {job.max_attempts}; retrying automatically.
        </p>
      ) : null}
      {job.error_message ? <p className="mt-1 text-destructive">{job.error_message}</p> : null}
      {job.cancellable || job.retryable ? (
        <div className="mt-2 flex gap-2">
          {job.cancellable ? (
            <Button type="button" size="sm" variant="outline" disabled={busy} onClick={onCancel}>
              Cancel
            </Button>
          ) : null}
          {job.retryable ? (
            <Button type="button" size="sm" variant="outline" disabled={busy} onClick={onRetry}>
              Retry
            </Button>
          ) : null}
        </div>
      ) : null}
    </div>
  );
}
