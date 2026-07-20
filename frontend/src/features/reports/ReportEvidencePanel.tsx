import { useState } from "react";

import type { CommunicationEvidenceLink } from "@/types/communications";

const SOURCE_TABLE_LABELS: Record<string, string> = {
  throughput_snapshots: "Throughput",
  milestones: "Milestone",
  risk_alerts: "Risk alert",
  quality_snapshots: "Quality snapshot",
  quality_summaries: "Quality summary",
  delivery_confidence_scores: "Delivery confidence",
};

function sourceTypeLabel(sourceTable: string): string {
  return SOURCE_TABLE_LABELS[sourceTable] ?? sourceTable.replace(/_/g, " ");
}

function formatEvidenceWhen(iso: string | null | undefined): string | null {
  if (!iso) return null;
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return null;
  return date.toLocaleString("en-US", {
    month: "short",
    day: "numeric",
    year: "numeric",
    hour: "numeric",
    minute: "2-digit",
  });
}

export interface ReportEvidencePanelProps {
  links: CommunicationEvidenceLink[];
}

/**
 * Collapsible evidence panel — human labels only (no raw DB IDs as primary text).
 */
export function ReportEvidencePanel({ links }: ReportEvidencePanelProps) {
  const [open, setOpen] = useState(false);
  const count = links.length;

  return (
    <div className="mt-3 rounded-md border border-border bg-elevated" data-testid="evidence-panel">
      <button
        type="button"
        className="flex w-full items-center justify-between px-3 py-2 text-left text-[11px] font-medium"
        aria-expanded={open}
        onClick={() => setOpen((value) => !value)}
      >
        <span>
          Evidence ({count} {count === 1 ? "source" : "sources"})
        </span>
        <span className="text-muted-foreground">{open ? "Hide" : "Show"}</span>
      </button>

      {open ? (
        <div className="border-t border-border px-3 py-2">
          {count === 0 ? (
            <p className="text-[11px] text-muted-foreground" data-testid="evidence-empty">
              No evidence links are attached to this report.
            </p>
          ) : (
            <ul className="space-y-2">
              {links.map((link, index) => {
                const when = formatEvidenceWhen(link.created_at);
                const title =
                  link.description?.trim() ||
                  `${sourceTypeLabel(link.source_table)} evidence`;
                return (
                  <li
                    key={link.id ?? `${link.source_table}-${link.source_row_id}-${index}`}
                    className="rounded border border-border bg-card px-2.5 py-2 text-[11px]"
                  >
                    <div className="font-medium text-foreground">{title}</div>
                    <div className="mt-0.5 text-muted-foreground">
                      {sourceTypeLabel(link.source_table)}
                      {when ? ` · ${when}` : null}
                    </div>
                  </li>
                );
              })}
            </ul>
          )}
        </div>
      ) : null}
    </div>
  );
}
