import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import { Suspense } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { GovernanceDashboard } from "@/features/governance/GovernanceDashboard";
import {
  GOVERNANCE_ANALYTICS_DEFER_MS,
  GOVERNANCE_ANALYTICS_DETAIL_IDLE_MS,
} from "@/features/governance/governance-load-strategy";
import * as api from "@/lib/api";
import { useAuthStore } from "@/stores/useAuthStore";
import type { MeUser } from "@/types/auth";

const { navigateMock } = vi.hoisted(() => ({ navigateMock: vi.fn() }));

vi.mock("@tanstack/react-router", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@tanstack/react-router")>()),
  useNavigate: () => navigateMock,
}));

vi.mock("@/routes/governance", () => ({
  Route: {
    fullPath: "/governance",
    useSearch: () => ({}),
  },
}));

class ResizeObserverMock {
  observe() {}
  unobserve() {}
  disconnect() {}
}

vi.stubGlobal("ResizeObserver", ResizeObserverMock);

const deliveryManager: MeUser = {
  id: "11111111-1111-1111-1111-111111111111",
  org_id: "22222222-2222-2222-2222-222222222222",
  email: "dm@example.com",
  full_name: "Delivery Manager",
  role: "delivery_manager",
  is_active: true,
};

const clientUser: MeUser = {
  ...deliveryManager,
  id: "33333333-3333-3333-3333-333333333333",
  email: "client@example.com",
  full_name: "Client User",
  role: "client",
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
  project_health: [],
  portfolio_risk_ranking: [],
  charts: {},
  export_sections: ["Governance Health"],
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
      <Suspense fallback={null}>
        <GovernanceDashboard />
      </Suspense>
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

      if (path.startsWith("/governance/ai-recommendations/generate")) {
        throw new Error("AI generate must not run during dashboard load");
      }

      if (path.startsWith("/governance/ai-recommendations")) {
        return {
          data: {
            items: [],
            rule_based: [],
            total: 0,
            ai_enabled: false,
            can_generate: false,
          },
        };
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
    expect(fetchCalls.some((path) => path.startsWith("/governance/analytics/summary"))).toBe(false);

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

  it("requests dependencies with the dashboard first-page limit of 6", async () => {
    renderDashboard();

    await waitFor(() => {
      expect(fetchCalls.some((path) => path.includes("/governance/dependencies?limit=6"))).toBe(
        true,
      );
    });

    expect(fetchCalls.some((path) => path.includes("limit=50"))).toBe(false);
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

    await waitFor(() => {
      expect(kpiSection).toHaveTextContent("42");
      expect(kpiSection).toHaveTextContent("11");
      expect(kpiSection).toHaveTextContent("6");
    });
    expect(fetchCalls.some((path) => path.startsWith("/governance/bootstrap"))).toBe(true);
  });

  it("keeps executive analytics visible while detail is pending", async () => {
    renderDashboard();

    await waitFor(
      () => {
        expect(fetchCalls.some((path) => path.startsWith("/governance/analytics/summary"))).toBe(
          true,
        );
        expect(screen.getByText("Portfolio Risk Ranking")).toBeInTheDocument();
      },
      { timeout: GOVERNANCE_ANALYTICS_DEFER_MS + 800 },
    );

    expect(fetchCalls.some((path) => path.startsWith("/governance/analytics/detail"))).toBe(false);
  });

  it("does not invoke AI recommendation generation during dashboard load", async () => {
    renderDashboard();

    await waitFor(
      () => {
        expect(fetchCalls.some((path) => path.startsWith("/governance/analytics/summary"))).toBe(
          true,
        );
      },
      { timeout: GOVERNANCE_ANALYTICS_DEFER_MS + 800 },
    );

    expect(
      fetchCalls.some((path) => path.startsWith("/governance/ai-recommendations/generate")),
    ).toBe(false);
  });

  it("always shows the governance tools tabs and opens the agent by default", async () => {
    renderDashboard();

    await waitFor(() => {
      expect(screen.getByText("Ask a governance question")).toBeInTheDocument();
    });

    expect(screen.getByRole("tab", { name: /Ask Governance Agent/i })).toHaveAttribute(
      "data-state",
      "active",
    );
    expect(screen.getByRole("tab", { name: /Project Charters/i })).toBeVisible();
    expect(screen.getByRole("tab", { name: /Governance This Week/i })).toBeVisible();
  });

  it("keeps all governance tools tabs visible for client users", async () => {
    useAuthStore.setState({ user: clientUser });
    renderDashboard();

    await waitFor(() => {
      expect(screen.getByText("Ask a governance question")).toBeInTheDocument();
    });

    expect(screen.getByRole("tab", { name: /Ask Governance Agent/i })).toBeVisible();
    expect(screen.getByRole("tab", { name: /Project Charters/i })).toBeVisible();
    expect(screen.getByRole("tab", { name: /Governance This Week/i })).toBeVisible();
  });
});
