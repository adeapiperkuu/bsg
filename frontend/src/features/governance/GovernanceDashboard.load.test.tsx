import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { GovernanceDashboard } from "@/features/governance/GovernanceDashboard";
import {
  GOVERNANCE_ANALYTICS_DEFER_MS,
  GOVERNANCE_ANALYTICS_DETAIL_IDLE_MS,
} from "@/features/governance/governance-load-strategy";
import * as api from "@/lib/api";
import { useAuthStore } from "@/stores/useAuthStore";
import type { MeUser } from "@/types/auth";

const deliveryManager: MeUser = {
  id: "11111111-1111-1111-1111-111111111111",
  org_id: "22222222-2222-2222-2222-222222222222",
  email: "dm@example.com",
  full_name: "Delivery Manager",
  role: "delivery_manager",
  is_active: true,
};

const bootstrapKpis = {
  open_actions: 42,
  overdue_actions: 5,
  open_escalations: 11,
  blocking_dependencies: 6,
  at_risk_items: 8,
  sla_adherence_pct: 93.5,
};

const sampleDependency = {
  id: "dep-1",
  project_id: "proj-1",
  title: "Vendor contract review",
  dependency_type: "external",
  owner_id: null,
  due_date: "2026-07-15",
  status: "open",
  overdue_days: 0,
  project_name: "Atlas Program",
  owner_name: null,
};

const analyticsSummary = {
  generated_at: "2026-07-06T08:00:00.000Z",
  date_range_days: 30,
  kpis: {
    portfolio_score: 82,
    projects_at_risk: 1,
    leadership_attention_projects: 2,
    blocking_dependencies: 3,
    critical_escalations: 0,
    pending_scope_approvals: 0,
    upcoming_governance_meetings: 0,
    governance_sla_pct: 95,
    avg_dependency_resolution_days: null,
    avg_escalation_resolution_days: null,
    avg_action_completion_days: null,
    open_dependencies: 4,
    open_actions: 2,
    overdue_actions: 1,
    projects_red: 0,
    projects_amber: 1,
    projects_green: 3,
    weekly_trend: 0,
    monthly_trend: 0,
  },
  project_health: [],
  portfolio_risk_ranking: [],
  charts: {},
  export_sections: ["KPIs", "Governance Health"],
};

function renderDashboard() {
  const queryClient = new QueryClient({
    defaultOptions: {
      queries: {
        retry: false,
      },
    },
  });

  return render(
    <QueryClientProvider client={queryClient}>
      <GovernanceDashboard />
    </QueryClientProvider>,
  );
}

describe("GovernanceDashboard load behavior", () => {
  const fetchCalls: string[] = [];
  let detailResolve: ((value: unknown) => void) | null = null;

  beforeEach(() => {
    fetchCalls.length = 0;
    detailResolve = null;
    useAuthStore.setState({
      user: deliveryManager,
      isAuthenticated: true,
      isLoading: false,
    });

    vi.spyOn(api, "apiFetch").mockImplementation(async (path: string) => {
      fetchCalls.push(path);

      if (path.startsWith("/governance/bootstrap")) {
        return { data: { kpis: bootstrapKpis } };
      }

      if (path.startsWith("/governance/dependencies")) {
        return {
          data: [sampleDependency],
          pagination: {
            total: 1,
            limit: 6,
            offset: 0,
            items: 1,
            has_more: false,
          },
        };
      }

      if (path.startsWith("/governance/analytics/summary")) {
        return { data: analyticsSummary };
      }

      if (path.startsWith("/governance/analytics/detail")) {
        return await new Promise((resolve) => {
          detailResolve = resolve;
        });
      }

      if (path.startsWith("/projects")) {
        return { data: [{ id: "proj-1", name: "Atlas Program" }] };
      }

      throw new Error(`Unexpected apiFetch path: ${path}`);
    });
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("renders the governance table while analytics summary is still loading", async () => {
    renderDashboard();

    await waitFor(() => {
      expect(screen.getByText("Vendor contract review")).toBeInTheDocument();
    });

    expect(fetchCalls.some((path) => path.startsWith("/governance/dependencies"))).toBe(true);
    expect(fetchCalls.some((path) => path.startsWith("/governance/analytics/summary"))).toBe(
      false,
    );

    await waitFor(
      () => {
        expect(fetchCalls.some((path) => path.startsWith("/governance/analytics/summary"))).toBe(
          true,
        );
      },
      { timeout: GOVERNANCE_ANALYTICS_DEFER_MS + 500 },
    );

    expect(screen.getByText("Vendor contract review")).toBeInTheDocument();
  });

  it("loads analytics summary before detail", async () => {
    renderDashboard();

    await waitFor(
      () => {
        expect(fetchCalls.some((path) => path.startsWith("/governance/analytics/summary"))).toBe(
          true,
        );
      },
      { timeout: GOVERNANCE_ANALYTICS_DEFER_MS + 500 },
    );

    expect(fetchCalls.some((path) => path.startsWith("/governance/analytics/detail"))).toBe(false);

    await waitFor(
      () => {
        expect(fetchCalls.some((path) => path.startsWith("/governance/analytics/detail"))).toBe(
          true,
        );
      },
      { timeout: GOVERNANCE_ANALYTICS_DETAIL_IDLE_MS + 800 },
    );

    expect(detailResolve).not.toBeNull();
  });

  it("does not request projects immediately on mount", async () => {
    renderDashboard();

    await waitFor(() => {
      expect(fetchCalls.some((path) => path.startsWith("/governance/dependencies"))).toBe(true);
    });

    expect(fetchCalls.some((path) => path.startsWith("/projects"))).toBe(false);
  });

  it("shows bootstrap KPI totals instead of page-only counts", async () => {
    renderDashboard();

    const kpiSection = await screen.findByLabelText("Governance portfolio KPIs");

    expect(kpiSection).toHaveTextContent("42");
    expect(kpiSection).toHaveTextContent("11");
    expect(kpiSection).toHaveTextContent("6");
    expect(fetchCalls.some((path) => path.startsWith("/governance/bootstrap"))).toBe(true);
  });

  it("keeps executive KPIs visible while detail is pending", async () => {
    renderDashboard();

    await waitFor(
      () => {
        expect(screen.getByText("Portfolio Score")).toBeInTheDocument();
      },
      { timeout: GOVERNANCE_ANALYTICS_DEFER_MS + 800 },
    );

    expect(screen.getByText("Vendor contract review")).toBeInTheDocument();
    expect(fetchCalls.some((path) => path.startsWith("/governance/analytics/detail"))).toBe(false);
  });
});
