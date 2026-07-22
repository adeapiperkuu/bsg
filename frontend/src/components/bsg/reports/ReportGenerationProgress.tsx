import { Card, SectionHeader, StatusPill } from "@/components/bsg/widgets";
import { useReportJobQuery } from "@/lib/queries/reports";

export function ReportGenerationProgress({ jobId }: { jobId: string | null | undefined }) {
  const query = useReportJobQuery(jobId);
  const status = query.data?.status ?? (query.isLoading ? "loading" : "idle");
  const done = status === "succeeded" || status === "failed" || status === "cancelled";
  return (
    <Card>
      <SectionHeader
        title="Generation Progress"
        sub={jobId ? `Job ${jobId.slice(0, 8)}…` : "No active job"}
        right={
          <StatusPill
            status={
              status === "succeeded"
                ? "On Track"
                : status === "failed"
                  ? "Critical"
                  : "Warning"
            }
          />
        }
      />
      <div className="text-sm" role="status" aria-live="polite">
        {!jobId
          ? "Start a generation job to track progress."
          : done
            ? `Job ${status}${query.data?.report_instance_id ? ` · report ${query.data.report_instance_id}` : ""}`
            : `Status: ${status}. Polling until complete…`}
      </div>
    </Card>
  );
}
