import { Card, SectionHeader, StatusPill } from "@/components/bsg/widgets";
import type { ReportInstanceListItem } from "@/types/reports";

function statusPill(status: string): "On Track" | "Warning" | "Critical" {
  if (status === "approved" || status === "distributed") return "On Track";
  if (status === "rejected" || status === "failed") return "Critical";
  return "Warning";
}

export function ReportHistoryList({
  reports,
  selectedId,
  onSelect,
  loading,
}: {
  reports: ReportInstanceListItem[];
  selectedId?: string | null;
  onSelect?: (id: string) => void;
  loading?: boolean;
}) {
  return (
    <Card>
      <SectionHeader title="Report History" sub={`${reports.length} reports`} />
      {loading ? (
        <div className="py-8 text-center text-sm text-muted-foreground" role="status">
          Loading reports…
        </div>
      ) : reports.length === 0 ? (
        <div className="py-8 text-center text-sm text-muted-foreground" role="status">
          No platform reports yet.
        </div>
      ) : (
        <ul className="space-y-2" aria-label="Report history">
          {reports.map((report) => (
            <li key={report.id}>
              <button
                type="button"
                className={`flex w-full items-center justify-between rounded-lg border px-3 py-2 text-left text-sm ${
                  selectedId === report.id
                    ? "border-[color:var(--accent)] bg-[color:var(--panel-2)]"
                    : "border-[color:var(--border)]"
                }`}
                onClick={() => onSelect?.(report.id)}
              >
                <span>
                  <span className="font-medium">{report.title}</span>
                  <span className="mt-0.5 block text-[11px] text-muted-foreground">
                    {report.template_key} · {report.domain}
                  </span>
                </span>
                <StatusPill status={statusPill(report.status)} />
              </button>
            </li>
          ))}
        </ul>
      )}
    </Card>
  );
}
