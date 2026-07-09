import { describe, expect, it } from "vitest";

import {
  GOVERNANCE_ANALYTICS_DEFER_MS,
  GOVERNANCE_ANALYTICS_DETAIL_IDLE_MS,
  resolveGovernanceTabTotals,
  shouldEnableGovernanceAnalyticsDetail,
  shouldEnableGovernanceAnalyticsSummary,
  shouldEnableGovernanceProjects,
} from "@/features/governance/governance-load-strategy";

describe("governance load strategy", () => {
  it("defers analytics summary until the executive section is ready", () => {
    expect(shouldEnableGovernanceAnalyticsSummary(true, false)).toBe(false);
    expect(shouldEnableGovernanceAnalyticsSummary(true, true)).toBe(true);
    expect(shouldEnableGovernanceAnalyticsSummary(false, true)).toBe(false);
  });

  it("waits for summary completion before enabling detail", () => {
    expect(
      shouldEnableGovernanceAnalyticsDetail({
        showExecutiveAnalytics: true,
        analyticsDeferredReady: true,
        summaryReady: false,
        detailTriggerReady: true,
      }),
    ).toBe(false);
    expect(
      shouldEnableGovernanceAnalyticsDetail({
        showExecutiveAnalytics: true,
        analyticsDeferredReady: true,
        summaryReady: true,
        detailTriggerReady: true,
      }),
    ).toBe(true);
  });

  it("uses a short analytics defer window", () => {
    expect(GOVERNANCE_ANALYTICS_DEFER_MS).toBeGreaterThanOrEqual(100);
    expect(GOVERNANCE_ANALYTICS_DEFER_MS).toBeLessThanOrEqual(300);
    expect(GOVERNANCE_ANALYTICS_DETAIL_IDLE_MS).toBeGreaterThanOrEqual(200);
  });

  it("lazy-loads projects only when UI needs options", () => {
    expect(
      shouldEnableGovernanceProjects({
        filtersOpen: false,
        dialogOpen: false,
        agentNeedsProjects: false,
        chartersTabActive: false,
      }),
    ).toBe(false);

    expect(
      shouldEnableGovernanceProjects({
        filtersOpen: true,
        dialogOpen: false,
        agentNeedsProjects: false,
        chartersTabActive: false,
      }),
    ).toBe(true);
  });

  it("uses bootstrap KPI totals when list totals are unavailable", () => {
    const totals = resolveGovernanceTabTotals({
      bootstrapKpis: {
        open_actions: 18,
        overdue_actions: 2,
        open_escalations: 9,
        blocking_dependencies: 3,
        at_risk_items: 5,
        sla_adherence_pct: 91,
      },
      dependenciesTotal: 4,
    });

    expect(totals.dependencies).toBe(4);
    expect(totals.actions).toBe(18);
    expect(totals.escalations).toBe(9);
  });
});
