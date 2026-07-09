import { AiBadge, Card, SectionHeader, StatusPill } from "@/components/bsg/widgets";
import type { CalibrationBrief } from "@/lib/api";

export function CalibrationBriefCard({ brief }: { brief: CalibrationBrief }) {
  if (brief.candidates.length === 0) return null;

  return (
    <Card id="calibration-brief">
      <SectionHeader
        title="Calibration Brief"
        sub="UC-03 reviewer calibration candidates"
        right={<AiBadge />}
      />
      {brief.brief_text && <p className="mb-3 text-sm text-foreground/90">{brief.brief_text}</p>}
      <ul className="space-y-2 text-xs">
        {brief.candidates.map((c) => (
          <li key={c.annotator_id} className="rounded border border-border bg-elevated p-2">
            <div className="flex items-center gap-2">
              <StatusPill status={c.priority === "immediate" ? "Critical" : "Warning"} />
              <span className="font-medium">Reviewer {c.annotator_id.slice(0, 8)}…</span>
              <span className="text-muted-foreground">
                {c.accuracy_pct?.toFixed(1)}% · {c.items_evaluated} items
              </span>
            </div>
            <div className="mt-1 text-muted-foreground">{c.reason}</div>
          </li>
        ))}
      </ul>
    </Card>
  );
}
