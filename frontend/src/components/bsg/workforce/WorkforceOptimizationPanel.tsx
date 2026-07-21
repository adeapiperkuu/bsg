import { useMemo, useState } from "react";

import { AiBadge, Card, SectionHeader, StatusPill } from "@/components/bsg/widgets";
import { cn } from "@/lib/utils";
import type {
  RecommendationLineage,
  ResourcePlanningRecommendation,
  SkillMatchRecommendation,
  SmeCoverageRecommendation,
  UtilizationForecastPoint,
  WorkloadRebalanceRecommendation,
  WorkforceOptimizationRead,
  WorkforcePriorityAction,
  WorkforceSkillShortage,
} from "@/types/workforce";

const CAPACITY_THRESHOLD = 85;

function pct(score: number): number {
  return Math.round(Math.max(0, Math.min(1, score)) * 100);
}

function severityLabel(value: string): string {
  const normalized = value.toLowerCase();
  if (normalized === "critical") return "Critical";
  if (normalized === "high") return "High";
  if (normalized === "medium") return "Medium";
  if (normalized === "low") return "Low";
  return value;
}

function coverageLabel(available: number, required: number): string {
  return `${available} / ${required}`;
}

function LineageDetails({ lineage }: { lineage: RecommendationLineage }) {
  return (
    <details className="mt-2 text-xs text-muted-foreground">
      <summary className="cursor-pointer select-none text-[11px] font-medium text-foreground/80">
        Data lineage · {lineage.source_entities.length} sources ·{" "}
        {lineage.calculations.length} calculations
      </summary>
      <div className="mt-2 space-y-2 border-l border-border pl-3">
        {lineage.evidence.slice(0, 4).map((item) => (
          <div key={item.evidence_id}>
            <p className="font-medium text-foreground/90">{item.summary}</p>
            {item.source_entities[0] ? (
              <p className="text-[10px] uppercase tracking-wide text-muted-foreground">
                {item.source_entities[0].source_table}
                {item.source_entities[0].label ? ` · ${item.source_entities[0].label}` : ""}
              </p>
            ) : null}
          </div>
        ))}
        {lineage.calculations.slice(0, 2).map((calc) => (
          <p key={calc.name}>
            <span className="font-medium text-foreground/80">{calc.name}:</span> {calc.description}
            {calc.formula ? ` (${calc.formula})` : ""}
          </p>
        ))}
        {lineage.metrics_involved.length > 0 ? (
          <p>Metrics: {lineage.metrics_involved.join(", ")}</p>
        ) : null}
      </div>
    </details>
  );
}

function PriorityActions({ actions }: { actions: WorkforcePriorityAction[] }) {
  if (actions.length === 0) {
    return (
      <p className="rounded-md border border-dashed border-border px-3 py-3 text-center text-xs text-muted-foreground">
        No critical optimization actions right now.
      </p>
    );
  }
  return (
    <div className="space-y-2">
      {actions.map((action) => (
        <div
          key={action.action_id}
          className="flex items-start gap-3 rounded-md border border-border/70 bg-elevated/40 px-3 py-2.5"
        >
          <span
            className={cn(
              "mt-1.5 h-2 w-2 shrink-0 rounded-full",
              action.urgency === "critical" || action.urgency === "high"
                ? "bg-[color:var(--danger)]"
                : action.urgency === "medium"
                  ? "bg-[color:var(--warning)]"
                  : "bg-muted-foreground",
            )}
          />
          <div className="min-w-0 flex-1">
            <div className="flex flex-wrap items-center gap-2">
              <p className="text-sm font-medium text-foreground">{action.title}</p>
              <StatusPill status={severityLabel(action.urgency)} />
              <AiBadge confidence={pct(action.confidence_score)} source="formula" />
            </div>
            <p className="mt-0.5 text-xs text-muted-foreground">{action.detail}</p>
          </div>
        </div>
      ))}
    </div>
  );
}

function SkillMatchingSection({ rows }: { rows: SkillMatchRecommendation[] }) {
  const prioritized = rows
    .filter((row) => row.headcount_shortfall > 0 || row.candidates.length > 0)
    .slice(0, 5);

  if (prioritized.length === 0) {
    return (
      <p className="text-xs text-muted-foreground">
        No staffing shortfalls to match — skill coverage meets requirements.
      </p>
    );
  }

  return (
    <div className="space-y-3">
      {prioritized.map((row) => {
        const available = Math.max(0, row.required_headcount - row.headcount_shortfall);
        return (
          <div key={row.skill_id} className="rounded-md border border-border/60 p-3">
            <div className="flex flex-wrap items-center justify-between gap-2">
              <div>
                <p className="text-sm font-medium text-foreground">{row.skill_name}</p>
                <p className="text-[11px] text-muted-foreground">
                  Coverage {coverageLabel(available, row.required_headcount)} ·{" "}
                  {row.required_proficiency_level} · SMEs need {row.required_sme_count}
                </p>
              </div>
              <StatusPill status={severityLabel(row.priority)} />
            </div>
            {row.candidates.length === 0 ? (
              <p className="mt-2 text-[11px] text-[color:var(--warning)]">
                No internal candidates scored above the match threshold — hiring may be required.
              </p>
            ) : (
              <div className="mt-2 space-y-2">
                {row.candidates.slice(0, 3).map((candidate) => (
                  <div key={candidate.annotator_id} className="rounded bg-elevated/50 px-2.5 py-2">
                    <div className="flex flex-wrap items-center gap-2">
                      <p className="text-xs font-medium text-foreground">{candidate.annotator_name}</p>
                      {candidate.team_name ? (
                        <span className="text-[10px] text-muted-foreground">{candidate.team_name}</span>
                      ) : null}
                      <AiBadge
                        confidence={pct(candidate.match_score)}
                        label="Match"
                        source="formula"
                      />
                      <AiBadge
                        confidence={pct(candidate.confidence_score)}
                        label="Conf"
                        source="formula"
                      />
                    </div>
                    <p className="mt-1 text-[11px] text-muted-foreground">{candidate.reasoning}</p>
                    {candidate.strengths.length > 0 ? (
                      <p className="mt-1 text-[11px] text-[color:var(--success)]">
                        Strengths: {candidate.strengths.slice(0, 3).join("; ")}
                      </p>
                    ) : null}
                    {candidate.missing_skills.length > 0 ? (
                      <p className="mt-0.5 text-[11px] text-[color:var(--warning)]">
                        Missing: {candidate.missing_skills.slice(0, 3).join("; ")}
                      </p>
                    ) : null}
                    <LineageDetails lineage={candidate.lineage} />
                  </div>
                ))}
              </div>
            )}
          </div>
        );
      })}
    </div>
  );
}

function RebalancingSection({
  rows,
  currentUtilization,
}: {
  rows: WorkloadRebalanceRecommendation[];
  currentUtilization: number | null;
}) {
  if (rows.length === 0) {
    const overloaded =
      currentUtilization !== null && currentUtilization >= CAPACITY_THRESHOLD;
    return (
      <p className="text-xs text-muted-foreground">
        {overloaded
          ? `Utilization is ${currentUtilization.toFixed(0)}% (at/above ${CAPACITY_THRESHOLD}%), but there is no underutilized destination team to transfer into. Add capacity or a second team before rebalancing applies.`
          : "No transfer suggestions — teams are within utilization bands."}
      </p>
    );
  }
  return (
    <div className="space-y-2">
      {rows.slice(0, 5).map((row) => (
        <div key={row.recommendation_id} className="rounded-md border border-border/60 p-3">
          <div className="flex flex-wrap items-center gap-2">
            <p className="text-sm font-medium text-foreground">
              {row.annotator_name}: {row.source_team_name} → {row.destination_team_name}
            </p>
            <AiBadge confidence={pct(row.confidence_score)} source="formula" />
          </div>
          <p className="mt-1 text-xs text-muted-foreground">{row.reasoning}</p>
          <p className="mt-1 text-[11px] text-foreground/80">
            Est. improvement {row.estimated_utilization_improvement.toFixed(1)} pts ·{" "}
            {row.expected_business_impact}
          </p>
          {row.risks.length > 0 ? (
            <p className="mt-1 text-[11px] text-[color:var(--warning)]">
              Risks: {row.risks.join("; ")}
            </p>
          ) : null}
          <LineageDetails lineage={row.lineage} />
        </div>
      ))}
    </div>
  );
}

function ResourcePlanningSection({ rows }: { rows: ResourcePlanningRecommendation[] }) {
  if (rows.length === 0) {
    return <p className="text-xs text-muted-foreground">No hiring recommendations right now.</p>;
  }
  return (
    <div className="space-y-2">
      {rows.slice(0, 6).map((row) => {
        const required = row.current_available + row.current_shortfall;
        return (
          <div key={row.recommendation_id} className="rounded-md border border-border/60 p-3">
            <div className="flex flex-wrap items-center gap-2">
              <p className="text-sm font-medium text-foreground">
                {row.estimated_headcount}× {row.role}
              </p>
              <StatusPill status={severityLabel(row.urgency)} />
              <AiBadge confidence={pct(row.confidence_score)} source="formula" />
            </div>
            {row.current_shortfall > 0 ? (
              <p className="mt-1 text-[11px] text-muted-foreground">
                Coverage {coverageLabel(row.current_available, required || row.current_available)}
                {row.sme_shortfall > 0 ? ` · SME shortfall ${row.sme_shortfall}` : ""}
                {row.required_proficiency_level ? ` · ${row.required_proficiency_level}` : ""}
              </p>
            ) : row.sme_shortfall > 0 ? (
              <p className="mt-1 text-[11px] text-muted-foreground">
                Headcount met · SME shortfall {row.sme_shortfall}
                {row.required_proficiency_level ? ` · ${row.required_proficiency_level}` : ""}
              </p>
            ) : null}
            <p className="mt-1 text-xs text-muted-foreground">{row.reasoning}</p>
            {row.affected_projects.length > 0 ? (
              <p className="mt-1 text-[11px] text-muted-foreground">
                Affects: {row.affected_projects.slice(0, 3).join(", ")}
              </p>
            ) : null}
            <LineageDetails lineage={row.lineage} />
          </div>
        );
      })}
    </div>
  );
}

function SmeCoverageSection({ rows }: { rows: SmeCoverageRecommendation[] }) {
  if (rows.length === 0) {
    return <p className="text-xs text-muted-foreground">No SME coverage risks detected.</p>;
  }
  return (
    <div className="space-y-2">
      {rows.slice(0, 5).map((row) => (
        <div key={row.recommendation_id} className="rounded-md border border-border/60 p-3">
          <div className="flex flex-wrap items-center gap-2">
            <p className="text-sm font-medium text-foreground">{row.skill_name}</p>
            <StatusPill status={severityLabel(row.severity)} />
            <AiBadge confidence={pct(row.confidence_score)} source="formula" />
          </div>
          <p className="mt-1 text-[11px] text-foreground/80">
            SMEs {coverageLabel(row.sme_count, row.required_sme_count)} · backups{" "}
            {row.backup_candidate_count}
          </p>
          <p className="mt-1 text-xs text-muted-foreground">{row.reasoning}</p>
          {row.recommended_actions.length > 0 ? (
            <p className="mt-1 text-[11px] text-[color:var(--warning)]">
              Actions: {row.recommended_actions.join(" · ")}
            </p>
          ) : null}
          <LineageDetails lineage={row.lineage} />
        </div>
      ))}
    </div>
  );
}

function ForecastAndShortages({
  forecast,
  shortages,
}: {
  forecast: UtilizationForecastPoint[];
  shortages: WorkforceSkillShortage[];
}) {
  const nowUtil = forecast[0]?.projected_utilization_pct ?? null;
  const utilTone =
    nowUtil !== null && nowUtil >= CAPACITY_THRESHOLD
      ? "text-[color:var(--danger)]"
      : "text-foreground";

  return (
    <div className="grid gap-3 sm:grid-cols-2">
      <div className="rounded-md border border-border/60 p-3">
        <p className="text-[11px] font-semibold uppercase tracking-wider text-muted-foreground">
          Utilization forecast
        </p>
        <p className="mt-1 text-[10px] text-muted-foreground">
          Capacity threshold {CAPACITY_THRESHOLD}% (same as Workforce Utilization)
        </p>
        {forecast.length === 0 ? (
          <p className="mt-2 text-xs text-muted-foreground">Insufficient utilization history.</p>
        ) : (
          <ul className="mt-2 space-y-1">
            {forecast.map((point) => (
              <li
                key={point.week_offset}
                className="flex items-center justify-between text-xs text-foreground"
              >
                <span>
                  {point.week_offset === 0 ? "Now" : `W+${point.week_offset}`} ·{" "}
                  {point.forecast_date}
                </span>
                <span
                  className={cn(
                    "font-medium",
                    point.week_offset === 0 ? utilTone : "text-foreground",
                  )}
                >
                  {point.projected_utilization_pct.toFixed(0)}%
                </span>
              </li>
            ))}
          </ul>
        )}
      </div>
      <div className="rounded-md border border-border/60 p-3">
        <p className="text-[11px] font-semibold uppercase tracking-wider text-muted-foreground">
          Skill shortages
        </p>
        <p className="mt-1 text-[10px] text-muted-foreground">
          Coverage available / required (matches Skill Coverage Matrix)
        </p>
        {shortages.length === 0 ? (
          <p className="mt-2 text-xs text-muted-foreground">No open shortfalls.</p>
        ) : (
          <ul className="mt-2 space-y-1.5">
            {shortages.slice(0, 5).map((item) => (
              <li key={item.skill_id} className="flex items-center justify-between gap-2 text-xs">
                <span className="min-w-0 truncate text-foreground">{item.skill_name}</span>
                <span className="shrink-0 tabular-nums text-muted-foreground">
                  {coverageLabel(item.available_headcount, item.required_headcount)}
                  <span className="ml-2 text-[color:var(--danger)]">−{item.shortfall}</span>
                </span>
              </li>
            ))}
          </ul>
        )}
      </div>
    </div>
  );
}

type TabId = "matching" | "rebalancing" | "planning" | "sme";

export function WorkforceOptimizationPanel({
  optimization,
  loading,
  error,
}: {
  optimization: WorkforceOptimizationRead | null | undefined;
  loading?: boolean;
  error?: boolean;
}) {
  const [tab, setTab] = useState<TabId>("planning");

  const currentUtilization = optimization?.utilization_forecast[0]?.projected_utilization_pct ?? null;

  const tabs = useMemo(() => {
    if (!optimization) return [];
    return [
      {
        id: "planning" as const,
        label: "Hiring",
        count: optimization.resource_planning.length,
      },
      {
        id: "matching" as const,
        label: "Skill match",
        count: optimization.skill_matches.filter((row) => row.headcount_shortfall > 0).length,
      },
      {
        id: "sme" as const,
        label: "SME risks",
        count: optimization.sme_coverage.length,
      },
      {
        id: "rebalancing" as const,
        label: "Rebalance",
        count: optimization.rebalancing.length,
      },
    ];
  }, [optimization]);

  return (
    <Card id="workforce-optimization">
      <SectionHeader
        title="Workforce Optimization"
        sub="Actionable staffing recommendations from live coverage, utilization, and roadmap data"
        right={
          optimization && optimization.priority_actions[0] ? (
            <AiBadge
              confidence={pct(optimization.priority_actions[0].confidence_score)}
              source="formula"
            />
          ) : null
        }
      />

      {loading ? (
        <div className="space-y-2">
          <div className="h-16 animate-pulse rounded-md bg-elevated" />
          <div className="h-24 animate-pulse rounded-md bg-elevated" />
        </div>
      ) : error ? (
        <p className="text-sm text-[color:var(--danger)]">Unable to load optimization insights.</p>
      ) : !optimization ? (
        <p className="rounded-md border border-dashed border-border px-3 py-4 text-center text-xs text-muted-foreground">
          Optimization engine has no payload for this project yet.
        </p>
      ) : (
        <div className="space-y-4">
          <div>
            <p className="mb-2 text-[11px] font-semibold uppercase tracking-wider text-muted-foreground">
              Needs attention
            </p>
            <PriorityActions actions={optimization.priority_actions} />
          </div>

          <ForecastAndShortages
            forecast={optimization.utilization_forecast}
            shortages={optimization.skill_shortages}
          />

          <div className="flex flex-wrap gap-1 border-b border-border pb-2">
            {tabs.map((item) => (
              <button
                key={item.id}
                type="button"
                onClick={() => setTab(item.id)}
                className={cn(
                  "rounded-md px-2.5 py-1 text-xs font-medium transition-colors",
                  tab === item.id
                    ? "bg-foreground text-background"
                    : "text-muted-foreground hover:bg-elevated hover:text-foreground",
                )}
              >
                {item.label}
                {item.count > 0 ? (
                  <span className="ml-1 opacity-70">({item.count})</span>
                ) : null}
              </button>
            ))}
          </div>

          {tab === "matching" ? (
            <SkillMatchingSection rows={optimization.skill_matches} />
          ) : null}
          {tab === "rebalancing" ? (
            <RebalancingSection
              rows={optimization.rebalancing}
              currentUtilization={currentUtilization}
            />
          ) : null}
          {tab === "planning" ? (
            <ResourcePlanningSection rows={optimization.resource_planning} />
          ) : null}
          {tab === "sme" ? <SmeCoverageSection rows={optimization.sme_coverage} /> : null}
        </div>
      )}
    </Card>
  );
}
