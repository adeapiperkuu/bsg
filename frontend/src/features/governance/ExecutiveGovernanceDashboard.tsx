import { Download, RefreshCw } from "lucide-react";

import { Card, KpiCard, SectionHeader, StatusPill } from "@/components/bsg/widgets";
import { Button } from "@/components/ui/button";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { cn } from "@/lib/utils";
import type {
  GovernanceAnalytics,
  GovernanceAnalyticsEvidence,
  GovernanceHealthProject,
} from "@/types/governance";

function formatRiskLevel(level: string): string {
  if (level === "excellent") return "Excellent";
  if (level === "healthy") return "Healthy";
  if (level === "moderate_risk") return "Moderate Risk";
  if (level === "high_risk") return "High Risk";
  if (level === "critical") return "Critical";
  return level;
}

function scoreStatus(score: number): string {
  if (score >= 90) return "Excellent";
  if (score >= 75) return "Healthy";
  if (score >= 60) return "Moderate Risk";
  if (score >= 40) return "High Risk";
  return "Critical";
}

function formatPriority(priority: string): string {
  if (priority === "critical") return "Critical";
  if (priority === "high") return "High";
  if (priority === "medium") return "Medium";
  return priority;
}

function csvEscape(value: string | number | null | undefined): string {
  const text = value === null || value === undefined ? "" : String(value);
  return `"${text.replace(/"/g, '""')}"`;
}

function exportAnalyticsCsv(analytics: GovernanceAnalytics) {
  const rows = [
    ["Section", "Project", "Metric", "Value", "Evidence"],
    ...analytics.portfolio_risk_ranking.map((project) => [
      "Portfolio Risk Ranking",
      project.project_name,
      "Governance Health Score",
      project.score,
      project.evidence.map((item) => item.label).join("; "),
    ]),
    ...analytics.insights.map((insight) => [
      "Executive Insight",
      "",
      insight.title,
      insight.detail,
      insight.evidence.map((item) => item.label).join("; "),
    ]),
    ...analytics.recommendations.map((recommendation) => [
      "Recommendation",
      recommendation.project_name ?? "",
      recommendation.title,
      recommendation.detail,
      recommendation.evidence.map((item) => item.label).join("; "),
    ]),
  ];
  const csv = rows.map((row) => row.map(csvEscape).join(",")).join("\n");
  const url = URL.createObjectURL(new Blob([csv], { type: "text/csv;charset=utf-8" }));
  const link = document.createElement("a");
  link.href = url;
  link.download = `governance-analytics-${analytics.date_range_days}d.csv`;
  link.click();
  URL.revokeObjectURL(url);
}

function EvidenceList({ evidence }: { evidence: GovernanceAnalyticsEvidence[] }) {
  if (evidence.length === 0) return null;
  return (
    <ul className="mt-2 space-y-1 text-[11px] text-muted-foreground">
      {evidence.slice(0, 3).map((item, index) => (
        <li key={`${item.source_type}-${item.source_id ?? index}`} className="truncate">
          {item.project_name ? `${item.project_name}: ` : ""}
          {item.label}
          {item.detail ? ` · ${item.detail}` : ""}
        </li>
      ))}
    </ul>
  );
}

function RiskRanking({
  rows,
  onOpenProject,
}: {
  rows: GovernanceHealthProject[];
  onOpenProject: (projectId: string) => void;
}) {
  return (
    <Card>
      <SectionHeader title="Portfolio Risk Ranking" sub="Sorted by governance priority" />
      <div className="space-y-2">
        {rows.slice(0, 8).map((project, index) => (
          <button
            key={project.project_id}
            type="button"
            className="flex w-full items-center gap-3 rounded-md border border-border bg-elevated px-3 py-2 text-left text-xs hover:bg-secondary/60"
            onClick={() => onOpenProject(project.project_id)}
          >
            <span className="w-5 text-muted-foreground">{index + 1}</span>
            <div className="min-w-0 flex-1">
              <div className="truncate font-medium">{project.project_name}</div>
              <div className="mt-1 flex flex-wrap gap-2 text-[10px] text-muted-foreground">
                {project.blocking_dependencies > 0 && (
                  <span>{project.blocking_dependencies} blocking dep.</span>
                )}
                {project.critical_escalations > 0 && (
                  <span>{project.critical_escalations} critical esc.</span>
                )}
                {project.overdue_actions > 0 && <span>{project.overdue_actions} overdue</span>}
                {project.delivery_traffic_light && (
                  <span>Delivery {project.delivery_traffic_light}</span>
                )}
              </div>
            </div>
            <StatusPill status={scoreStatus(project.score)} />
            <span className="w-9 text-right font-semibold">{project.score}</span>
          </button>
        ))}
      </div>
    </Card>
  );
}

export function ExecutiveGovernanceDashboard({
  analytics,
  isFetching,
  rangeDays,
  onRangeChange,
  onRefresh,
  onOpenProject,
}: {
  analytics: GovernanceAnalytics;
  isFetching: boolean;
  rangeDays: number;
  onRangeChange: (days: number) => void;
  onRefresh: () => void;
  onOpenProject: (projectId: string) => void;
}) {
  return (
    <section className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <SectionHeader
          title="Executive Governance Intelligence"
          sub="Portfolio health, trends, risks, and evidence-backed recommendations"
        />
        <div className="flex flex-wrap items-center gap-2">
          <Tabs value={String(rangeDays)} onValueChange={(value) => onRangeChange(Number(value))}>
            <TabsList className="h-8">
              {[7, 30, 90, 365].map((days) => (
                <TabsTrigger key={days} value={String(days)} className="text-xs">
                  {days === 365 ? "12M" : `${days}D`}
                </TabsTrigger>
              ))}
            </TabsList>
          </Tabs>
          <Button
            type="button"
            variant="outline"
            size="sm"
            className="shadow-none"
            onClick={onRefresh}
          >
            <RefreshCw className={cn("h-4 w-4", isFetching && "animate-spin")} />
            Refresh
          </Button>
          <Button
            type="button"
            variant="outline"
            size="sm"
            className="shadow-none"
            onClick={() => exportAnalyticsCsv(analytics)}
          >
            <Download className="h-4 w-4" />
            Export
          </Button>
        </div>
      </div>

      <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-4">
        <KpiCard
          label="Portfolio Score"
          value={`${analytics.kpis.portfolio_score}`}
          delta={`${analytics.kpis.weekly_trend >= 0 ? "+" : ""}${analytics.kpis.weekly_trend} weekly`}
          tone={
            analytics.kpis.portfolio_score >= 75
              ? "success"
              : analytics.kpis.portfolio_score >= 60
                ? "warning"
                : "danger"
          }
        />
        <KpiCard
          label="Projects at Risk"
          value={analytics.kpis.projects_at_risk}
          delta={`${analytics.kpis.leadership_attention_projects} need leadership`}
          tone={analytics.kpis.projects_at_risk > 0 ? "danger" : "success"}
        />
        <KpiCard
          label="Blocking Dependencies"
          value={analytics.kpis.blocking_dependencies}
          delta={`${analytics.kpis.open_dependencies} open dependencies`}
          tone={analytics.kpis.blocking_dependencies > 0 ? "warning" : "success"}
        />
        <KpiCard
          label="Governance SLA"
          value={`${analytics.kpis.governance_sla_pct}%`}
          delta={`${analytics.kpis.overdue_actions} overdue actions`}
          tone={analytics.kpis.governance_sla_pct >= 90 ? "success" : "warning"}
        />
      </div>

      <div className="grid gap-4 xl:grid-cols-[1fr_1fr]">
        <RiskRanking rows={analytics.portfolio_risk_ranking} onOpenProject={onOpenProject} />
        <Card>
          <SectionHeader title="AI Recommendations" sub="Evidence-backed next actions" />
          <div className="space-y-3">
            {analytics.recommendations.length === 0 ? (
              <p className="py-6 text-sm text-muted-foreground">
                No recommendations were generated from current evidence.
              </p>
            ) : (
              analytics.recommendations.slice(0, 5).map((recommendation) => (
                <div
                  key={`${recommendation.project_id ?? "portfolio"}-${recommendation.title}`}
                  className="rounded-md border border-border bg-elevated p-3"
                >
                  <div className="flex items-start justify-between gap-3">
                    <div>
                      <p className="text-sm font-medium">{recommendation.title}</p>
                      <p className="mt-1 text-xs text-muted-foreground">{recommendation.detail}</p>
                    </div>
                    <StatusPill status={formatPriority(recommendation.priority)} />
                  </div>
                  <EvidenceList evidence={recommendation.evidence} />
                </div>
              ))
            )}
          </div>
        </Card>
      </div>
    </section>
  );
}
