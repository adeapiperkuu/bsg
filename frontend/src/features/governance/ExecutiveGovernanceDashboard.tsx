import { Download } from "lucide-react";
import { useState, type RefObject } from "react";

import { Card, SectionHeader, StatusPill } from "@/components/bsg/widgets";
import { Button } from "@/components/ui/button";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Skeleton } from "@/components/ui/skeleton";
import { Tabs, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { GovernanceRecommendationsSection } from "@/features/governance/GovernanceRecommendationsSection";
import { GovernanceKpiStrip } from "@/features/governance/GovernanceKpiStrip";
import { exportGovernanceAnalytics } from "@/lib/queries/governance";
import type {
  GovernanceAnalytics,
  GovernanceKpis,
  GovernanceHealthProject,
} from "@/types/governance";

function scoreStatus(score: number): string {
  if (score >= 90) return "Excellent";
  if (score >= 75) return "Healthy";
  if (score >= 60) return "Moderate Risk";
  if (score >= 40) return "High Risk";
  return "Critical";
}

async function exportAnalyticsCsv(filters: {
  days: number;
  projectId?: string | null;
  vertical?: string | null;
}) {
  const blob = await exportGovernanceAnalytics(filters, "csv");
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = `governance-analytics-${filters.days}d.csv`;
  link.click();
  URL.revokeObjectURL(url);
}

function RiskRanking({
  rows,
  onOpenProject,
  isLoading,
  selectedProjectId,
}: {
  rows: GovernanceHealthProject[];
  onOpenProject: (projectId: string) => void;
  isLoading?: boolean;
  selectedProjectId?: string | null;
}) {
  return (
    <Card className="flex h-[520px] flex-col overflow-hidden">
      <SectionHeader title="Portfolio Risk Ranking" sub="Sorted by governance priority" />
      {isLoading && rows.length === 0 ? (
        <div className="mt-4 space-y-2">
          {[0, 1, 2, 3].map((row) => (
            <Skeleton key={row} className="h-12 w-full" />
          ))}
        </div>
      ) : (
        <div className="mt-4 min-h-0 flex-1 space-y-2 overflow-y-auto pr-1">
          {rows.slice(0, 8).map((project, index) => (
            <button
              key={project.project_id}
              type="button"
              className={`flex w-full items-center gap-3 rounded-md border px-3 py-2 text-left text-xs hover:bg-secondary/60 ${
                selectedProjectId === project.project_id
                  ? "border-primary bg-secondary/40"
                  : "border-border bg-elevated"
              }`}
              onClick={() => onOpenProject(project.project_id)}
            >
              <span className="w-5 text-muted-foreground">{index + 1}</span>
              <div className="min-w-0 flex-1">
                <div className="truncate font-medium">{project.project_name}</div>
                <div className="mt-1 flex flex-wrap gap-2 text-[10px] text-muted-foreground">
                  {project.vertical && <span>{project.vertical}</span>}
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
      )}
    </Card>
  );
}

export function ExecutiveAnalyticsDetailSkeleton() {
  return (
    <div
      className="grid gap-4 xl:grid-cols-[1fr_1fr]"
      aria-label="Loading executive analytics detail"
    >
      <Card>
        <Skeleton className="h-4 w-40" />
        <Skeleton className="mt-2 h-3 w-56" />
        <div className="mt-5 space-y-2">
          {[0, 1, 2, 3].map((row) => (
            <Skeleton key={row} className="h-12 w-full" />
          ))}
        </div>
      </Card>
      <Card>
        <Skeleton className="h-4 w-40" />
        <Skeleton className="mt-2 h-3 w-56" />
        <div className="mt-5 space-y-2">
          {[0, 1, 2].map((row) => (
            <Skeleton key={row} className="h-16 w-full" />
          ))}
        </div>
      </Card>
    </div>
  );
}

export function ExecutiveGovernanceDashboard({
  analytics,
  kpis,
  summaryLoading,
  rangeDays,
  onRangeChange,
  projectFilter,
  onProjectFilterChange,
  verticalFilter,
  onVerticalFilterChange,
  projectOptions = [],
  verticalOptions = [],
  onOpenProject,
  detailSectionRef,
  canWrite = false,
}: {
  analytics: GovernanceAnalytics | null;
  kpis: GovernanceKpis;
  summaryLoading: boolean;
  rangeDays: number;
  onRangeChange: (days: number) => void;
  projectFilter?: string | null;
  onProjectFilterChange?: (projectId: string | null) => void;
  verticalFilter?: string | null;
  onVerticalFilterChange?: (vertical: string | null) => void;
  projectOptions?: Array<{ id: string; name: string }>;
  verticalOptions?: string[];
  onOpenProject: (projectId: string) => void;
  detailSectionRef?: RefObject<HTMLElement | null>;
  canWrite?: boolean;
}) {
  const ranking = analytics?.portfolio_risk_ranking ?? [];
  const [focusProjectId, setFocusProjectId] = useState<string | null>(
    ranking[0]?.project_id ?? null,
  );
  const handleOpenProject = (projectId: string) => {
    setFocusProjectId(projectId);
    onOpenProject(projectId);
  };

  const effectiveFocus = focusProjectId ?? ranking[0]?.project_id ?? null;

  return (
    <section className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <SectionHeader
          title="Executive Governance Intelligence"
          sub="Portfolio health, risks, and evidence-backed recommendations"
        />
        <div className="flex flex-wrap items-center gap-2">
          <Select
            value={projectFilter ?? "all"}
            onValueChange={(value) => onProjectFilterChange?.(value === "all" ? null : value)}
          >
            <SelectTrigger className="h-8 w-[160px] text-xs">
              <SelectValue placeholder="All projects" />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="all">All projects</SelectItem>
              {projectOptions.map((project) => (
                <SelectItem key={project.id} value={project.id}>
                  {project.name}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
          <Select
            value={verticalFilter ?? "all"}
            onValueChange={(value) => onVerticalFilterChange?.(value === "all" ? null : value)}
          >
            <SelectTrigger className="h-8 w-[160px] text-xs">
              <SelectValue placeholder="All departments" />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="all">All departments</SelectItem>
              {verticalOptions.map((vertical) => (
                <SelectItem key={vertical} value={vertical}>
                  {vertical}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
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
            disabled={!analytics}
            onClick={() => {
              if (analytics) {
                void exportAnalyticsCsv({
                  days: analytics.date_range_days,
                  projectId: projectFilter,
                  vertical: verticalFilter,
                });
              }
            }}
          >
            <Download className="h-4 w-4" />
            Export
          </Button>
        </div>
      </div>

      <GovernanceKpiStrip kpis={kpis} isLoading={summaryLoading && !analytics} />

      <div
        ref={detailSectionRef as RefObject<HTMLDivElement>}
        className="grid gap-4 xl:grid-cols-[1fr_1fr]"
      >
        <RiskRanking
          rows={ranking}
          onOpenProject={handleOpenProject}
          isLoading={summaryLoading && ranking.length === 0}
          selectedProjectId={effectiveFocus}
        />
        <GovernanceRecommendationsSection focusProjectId={effectiveFocus} canWrite={canWrite} />
      </div>
    </section>
  );
}
