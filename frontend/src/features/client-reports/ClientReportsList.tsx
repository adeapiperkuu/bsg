import { Card, SectionHeader, StatusPill } from "@/components/bsg/widgets";
import { Skeleton } from "@/components/ui/skeleton";
import { typeLabel } from "@/features/reports/report-status";
import { formatReportDate, reportProjectLabel } from "@/features/reports/report-utils";
import type { CommunicationListItem } from "@/types/communications";

export interface ClientReportsListProps {
  reports: CommunicationListItem[];
  selectedId: string | null;
  onSelect: (id: string) => void;
  isLoading: boolean;
  isError: boolean;
  errorMessage: string | null;
  onRetry: () => void;
  /** Mobile: hide list when detail is open. */
  hiddenOnMobile?: boolean;
}

export function ClientReportsList({
  reports,
  selectedId,
  onSelect,
  isLoading,
  isError,
  errorMessage,
  onRetry,
  hiddenOnMobile = false,
}: ClientReportsListProps) {
  return (
    <Card className={`lg:col-span-1 ${hiddenOnMobile ? "hidden lg:block" : ""}`}>
      <SectionHeader title="Reports" sub="Sent reports for your organisation" />

      {isError ? (
        <div className="rounded-md border border-border bg-elevated p-4 text-xs" role="alert">
          <p className="text-muted-foreground">{errorMessage ?? "Failed to load reports."}</p>
          <button
            type="button"
            onClick={onRetry}
            className="mt-2 rounded border border-border px-2.5 py-1 text-[11px] font-medium"
          >
            Retry
          </button>
        </div>
      ) : isLoading && reports.length === 0 ? (
        <ul className="space-y-1.5" aria-busy="true" aria-label="Loading reports">
          {Array.from({ length: 5 }).map((_, i) => (
            <li key={i} className="rounded border border-border px-2.5 py-2">
              <Skeleton className="h-3 w-48" />
              <Skeleton className="mt-2 h-2.5 w-28" />
            </li>
          ))}
        </ul>
      ) : reports.length === 0 ? (
        <div className="rounded-md border border-border bg-elevated p-4 text-xs text-muted-foreground">
          <p className="font-medium text-foreground">No reports yet</p>
          <p className="mt-1">Sent reports from your delivery team will appear here.</p>
        </div>
      ) : (
        <ul className="space-y-1.5 text-xs" role="listbox" aria-label="Sent reports">
          {reports.map((r) => {
            const selected = selectedId === r.id;
            return (
              <li key={r.id} role="option" aria-selected={selected}>
                <button
                  type="button"
                  onClick={() => onSelect(r.id)}
                  className={`flex w-full items-center justify-between gap-2 rounded border border-border px-2.5 py-2 text-left ${
                    selected ? "bg-elevated ring-1 ring-[color:var(--brand)]" : ""
                  }`}
                >
                  <span className="min-w-0">
                    <div className="truncate font-medium">{r.subject}</div>
                    <div className="truncate text-[10px] text-muted-foreground">
                      {reportProjectLabel(r)} · {typeLabel(r.comm_type)} · Sent{" "}
                      {formatReportDate(r.sent_at ?? r.updated_at)}
                    </div>
                  </span>
                  <span className="flex shrink-0 items-center gap-1">
                    <StatusPill status="On Track" />
                    <span className="sr-only">Sent</span>
                    <span className="text-[10px] text-muted-foreground" aria-hidden>
                      Sent
                    </span>
                  </span>
                </button>
              </li>
            );
          })}
        </ul>
      )}
    </Card>
  );
}
