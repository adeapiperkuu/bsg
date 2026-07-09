import { Card, SectionHeader } from "@/components/bsg/widgets";
import type { ReviewerScorecard } from "@/lib/api";

export function ReviewerScorecardsCard({ scorecards }: { scorecards: ReviewerScorecard[] }) {
  if (scorecards.length === 0) return null;

  return (
    <Card>
      <SectionHeader title="Reviewer Scorecards" sub="Per-reviewer weekly accuracy" />
      <div className="overflow-x-auto">
        <table className="w-full text-xs">
          <thead className="text-left text-muted-foreground">
            <tr className="border-b border-border">
              <th className="py-2 pr-3 font-medium">Reviewer</th>
              <th className="py-2 pr-3 font-medium">Week</th>
              <th className="py-2 pr-3 font-medium">Items</th>
              <th className="py-2 pr-3 font-medium">Accuracy</th>
            </tr>
          </thead>
          <tbody>
            {scorecards.map((r) => (
              <tr key={r.id} className="border-b border-border/50">
                <td className="py-2 pr-3 font-mono">{r.annotator_id.slice(0, 8)}…</td>
                <td className="py-2 pr-3">
                  W{r.iso_week}/{r.iso_year}
                </td>
                <td className="py-2 pr-3">{r.items_evaluated}</td>
                <td className="py-2 pr-3">{r.accuracy_pct != null ? `${r.accuracy_pct}%` : "—"}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </Card>
  );
}
