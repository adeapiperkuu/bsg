import { Card, SectionHeader, StatusPill } from "@/components/bsg/widgets";
import { fmtIaa, fmtPct } from "./format";
import type { QualityDashboard as QualityDashboardData } from "@/lib/api";

export function TeamScorecardCard({ dashboard }: { dashboard: QualityDashboardData }) {
  return (
    <Card id="team-scorecard">
      <SectionHeader title="Team Quality Scorecard" />
      {dashboard.data_gap_teams.length > 0 && (
        <div className="mb-3 flex items-center gap-2 rounded-md border border-amber-500/40 bg-amber-500/10 px-3 py-2 text-xs text-amber-400">
          <span>⚠</span>
          <span>
            {dashboard.data_gap_teams.length} team{dashboard.data_gap_teams.length !== 1 ? "s" : ""}{" "}
            below minimum sample size (&lt;30 evaluated items):{" "}
            <span className="font-medium">{dashboard.data_gap_teams.join(", ")}</span>
          </span>
        </div>
      )}
      <div className="overflow-x-auto">
        <table className="w-full text-xs">
          <thead className="text-left text-muted-foreground">
            <tr className="border-b border-border">
              <th className="py-2 pr-3 font-medium">Team</th>
              <th className="py-2 pr-3 font-medium">Gold Acc</th>
              <th className="py-2 pr-3 font-medium">IAA</th>
              <th className="py-2 pr-3 font-medium">Rework</th>
              <th className="py-2 pr-3 font-medium">Status</th>
            </tr>
          </thead>
          <tbody>
            {dashboard.team_scorecard.map((t) => (
              <tr key={t.team_id} className="border-b border-border/50">
                <td className="py-2.5 pr-3 font-medium">
                  {t.team_name}
                  {t.has_data_gap && (
                    <span className="ml-2 rounded border border-amber-500/40 bg-amber-500/10 px-1.5 py-0.5 text-[10px] text-amber-400">
                      Data gap
                    </span>
                  )}
                </td>
                <td className="py-2.5 pr-3">{fmtPct(t.gold_set_accuracy_pct)}</td>
                <td className="py-2.5 pr-3">{fmtIaa(t.iaa_krippendorff_alpha)}</td>
                <td className="py-2.5 pr-3">{fmtPct(t.rework_rate_pct)}</td>
                <td className="py-2.5 pr-3">
                  <StatusPill status={t.status as "On Track" | "Warning" | "Critical"} />
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </Card>
  );
}
