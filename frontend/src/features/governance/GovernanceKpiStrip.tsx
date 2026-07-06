import { KpiCard } from "@/components/bsg/widgets";
import { Skeleton } from "@/components/ui/skeleton";
import type { GovernanceKpis } from "@/types/governance";

export function GovernanceKpiStrip({
  kpis,
  isLoading,
}: {
  kpis: GovernanceKpis;
  isLoading: boolean;
}) {
  if (isLoading) {
    return (
      <section
        aria-label="Loading governance KPIs"
        className="grid gap-3 sm:grid-cols-2 xl:grid-cols-3 2xl:grid-cols-6"
      >
        {["actions", "escalations", "blocking", "risk", "overdue", "sla"].map((item) => (
          <div key={item} className="rounded-lg border border-border bg-card p-4">
            <Skeleton className="h-3 w-24" />
            <Skeleton className="mt-3 h-7 w-12" />
          </div>
        ))}
      </section>
    );
  }

  return (
    <section
      aria-label="Governance portfolio KPIs"
      className="grid gap-3 sm:grid-cols-2 xl:grid-cols-3 2xl:grid-cols-6"
    >
      <KpiCard
        label="Open actions"
        value={kpis.open_actions}
        delta={`${kpis.overdue_actions} overdue`}
        tone={kpis.overdue_actions > 0 ? "warning" : "success"}
      />
      <KpiCard
        label="Open escalations"
        value={kpis.open_escalations}
        delta="Portfolio-wide"
        tone={kpis.open_escalations > 0 ? "warning" : "success"}
      />
      <KpiCard
        label="Blocking dependencies"
        value={kpis.blocking_dependencies}
        delta="Needs resolution"
        tone={kpis.blocking_dependencies > 0 ? "danger" : "success"}
      />
      <KpiCard
        label="At-risk items"
        value={kpis.at_risk_items}
        delta="Combined signals"
        tone={kpis.at_risk_items > 0 ? "danger" : "success"}
      />
      <KpiCard
        label="Overdue actions"
        value={kpis.overdue_actions}
        delta="SLA watch"
        tone={kpis.overdue_actions > 0 ? "danger" : "success"}
      />
      <KpiCard
        label="Governance SLA"
        value={`${kpis.sla_adherence_pct}%`}
        delta="90-day adherence"
        tone={kpis.sla_adherence_pct >= 90 ? "success" : "warning"}
      />
    </section>
  );
}
