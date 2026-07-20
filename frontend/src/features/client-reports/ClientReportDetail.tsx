import { Card, SectionHeader, StatusPill } from "@/components/bsg/widgets";
import { DeliveryMarkdown } from "@/components/delivery/delivery-markdown";
import { Skeleton } from "@/components/ui/skeleton";
import { typeLabel } from "@/features/reports/report-status";
import {
  formatReportDate,
  resolveCommunicationBody,
} from "@/features/reports/report-utils";
import type { CommunicationDetail } from "@/types/communications";

export interface ClientReportDetailProps {
  report: CommunicationDetail | null;
  projectName?: string | null;
  isLoading: boolean;
  isError: boolean;
  errorMessage: string | null;
  onRetry: () => void;
  onBack?: () => void;
  showBack?: boolean;
}

export function ClientReportDetail({
  report,
  projectName,
  isLoading,
  isError,
  errorMessage,
  onRetry,
  onBack,
  showBack = false,
}: ClientReportDetailProps) {
  if (!report && !isLoading && !isError) {
    return (
      <Card className="lg:col-span-2">
        <SectionHeader title="Report" sub="Select a report to read its content." />
        <div className="rounded-md border border-border bg-elevated p-5 text-sm text-muted-foreground">
          Select a report to read its content.
        </div>
      </Card>
    );
  }

  if (isLoading && !report) {
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

  if (isError && !report) {
    return (
      <Card className="lg:col-span-2">
        <SectionHeader title="Report" />
        <div className="rounded-md border border-border bg-elevated p-5 text-sm" role="alert">
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

  if (!report) return null;

  const project = projectName ?? report.project_name ?? "Project";
  const body = resolveCommunicationBody(report);
  const meta = [
    typeLabel(report.comm_type),
    report.sent_at ? `Sent ${formatReportDate(report.sent_at)}` : null,
  ]
    .filter(Boolean)
    .join(" · ");

  return (
    <Card className="lg:col-span-2">
      {showBack && onBack ? (
        <button
          type="button"
          onClick={onBack}
          className="mb-3 rounded border border-border px-2.5 py-1 text-[11px] font-medium lg:hidden"
        >
          Back to list
        </button>
      ) : null}
      <SectionHeader
        title={report.subject}
        sub={`${project} · ${meta}`}
        right={
          <div className="flex items-center gap-2">
            <StatusPill status="On Track" />
            <span className="text-[10px] text-muted-foreground">Sent</span>
          </div>
        }
      />
      <div
        className="prose-invert max-w-none rounded-md border border-border bg-elevated p-5 text-sm leading-6"
        data-readonly="true"
      >
        {body ? (
          <DeliveryMarkdown content={body} />
        ) : (
          <p className="text-muted-foreground">This report has no body content.</p>
        )}
      </div>
    </Card>
  );
}
