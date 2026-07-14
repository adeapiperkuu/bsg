import { describe, expect, it } from "vitest";

import { mergeGovernanceAnalytics } from "@/lib/queries/governance";
import type {
  GovernanceAnalyticsDetail,
  GovernanceAnalyticsSummary,
} from "@/types/governance";

const summary: GovernanceAnalyticsSummary = {
  generated_at: "2026-07-13T08:00:00.000Z",
  date_range_days: 30,
  project_health: [],
  portfolio_risk_ranking: [],
  charts: { health_distribution: [{ label: "Healthy", value: 1, secondary_value: null }] },
  export_sections: ["Governance Health", "Insights KPIs"],
  portfolio_governance_score: 82,
  insights_kpis: {
    portfolio_governance_score: 82,
    projects_at_risk: 1,
    recommendation_acceptance_rate_pct: 0,
    recommendation_dismissal_rate_pct: 0,
    escalations_created: 0,
    recommendations_created: 0,
    sla_adherence_pct: 0,
  },
};

const detail: GovernanceAnalyticsDetail = {
  generated_at: "2026-07-13T08:01:00.000Z",
  date_range_days: 30,
  insights: [],
  recommendations: [],
  trends: [
    {
      date: "2026-07-13",
      open_dependencies: 1,
      resolved_dependencies: 0,
      blocking_dependencies: 0,
      escalations_created: 2,
      escalations_resolved: 0,
      critical_escalations: 0,
      actions_created: 0,
      actions_completed: 0,
      overdue_actions: 0,
      scope_revisions: 0,
      scope_approvals: 0,
      locked_scope: 0,
      portfolio_health: 82,
      sla_adherence_pct: 90,
      recommendations_created: 3,
      recommendations_accepted: 1,
      recommendations_dismissed: 1,
      escalation_suggestions_created: 1,
    },
  ],
  charts: {
    recommendation_outcomes: [{ label: "Accepted", value: 1, secondary_value: null }],
  },
  recent_activity: [],
  export_sections: ["Charts", "Executive Insights", "Evidence Appendix", "Insights KPIs"],
  insights_kpis: {
    portfolio_governance_score: 82,
    projects_at_risk: 1,
    recommendation_acceptance_rate_pct: 40,
    recommendation_dismissal_rate_pct: 20,
    escalations_created: 2,
    recommendations_created: 5,
    sla_adherence_pct: 90,
  },
  top_governance_risks: [{ label: "Alpha", count: 2, project_id: "p1" }],
  top_recurring_blockers: [{ label: "External", count: 3 }],
  top_recurring_mitigation_failures: [],
  most_affected_projects: [{ label: "Alpha", count: 4, project_id: "p1" }],
  most_affected_departments: [{ label: "Medical", count: 4, vertical: "Medical" }],
  risk_heatmap: [
    { vertical: "Medical", risk_level: "high_risk", project_count: 1, avg_score: 55 },
  ],
};

describe("mergeGovernanceAnalytics Phase 11", () => {
  it("merges insights KPIs, lists, and heatmap from detail", () => {
    const merged = mergeGovernanceAnalytics(summary, detail);
    expect(merged.insights_kpis?.recommendation_acceptance_rate_pct).toBe(40);
    expect(merged.portfolio_governance_score).toBe(82);
    expect(merged.top_governance_risks?.[0]?.label).toBe("Alpha");
    expect(merged.risk_heatmap?.[0]?.vertical).toBe("Medical");
    expect(merged.trends[0]?.recommendations_created).toBe(3);
    expect(merged.charts.recommendation_outcomes?.[0]?.label).toBe("Accepted");
  });

  it("falls back to summary KPIs when detail is missing", () => {
    const merged = mergeGovernanceAnalytics(summary, null);
    expect(merged.insights_kpis?.portfolio_governance_score).toBe(82);
    expect(merged.top_governance_risks).toEqual([]);
    expect(merged.risk_heatmap).toEqual([]);
  });
});
