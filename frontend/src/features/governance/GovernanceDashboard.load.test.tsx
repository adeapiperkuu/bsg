import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
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

vi.mock("@/lib/api", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/lib/api")>()),
  apiFetch: vi.fn(),
  listProjects: vi.fn(),
  listUsers: vi.fn(),
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

    vi.mocked(api.listProjects).mockImplementation(async () => {
      fetchCalls.push("/projects?limit=100");
      return [];
    });
    vi.mocked(api.listUsers).mockResolvedValue([]);

    vi.mocked(api.apiFetch).mockImplementation(async (path: string) => {
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

      if (path.startsWith("/governance/register")) {
        return {
          data: [
            {
              project_id: "proj-1",
              project_name: "Atlas Program",
              scope_status: "approved",
              scope_version: "v2",
              open_dependencies: 7,
              blocking_dependencies: 1,
              open_actions: 2,
              open_escalations: 1,
              health: "amber",
            },
          ],
          pagination: { total: 1, limit: 6, offset: 0, items: 1, has_more: false },
        };
      }

      if (path.startsWith("/governance/project-sheet/proj-1")) {
        return {
          data: {
            project: {
              id: "proj-1",
              name: "Atlas Program",
              description: "Bounded composite sheet",
              vertical: "Retail",
              status: "active",
              start_date: "2026-01-01",
              target_end_date: "2026-12-31",
            },
            summary: {
              scope_status: "approved",
              scope_version: "v2",
              open_dependencies: 7,
              blocking_dependencies: 1,
              overdue_actions: 0,
              open_actions: 2,
              open_escalations: 1,
              critical_escalations: 0,
              health: "amber",
            },
            scope: null,
            dependencies: {
              items: [{ ...sampleDependency, title: "Composite dependency" }],
              total: 7,
              has_more: true,
            },
            actions: { items: [], total: 0, has_more: false },
            escalations: { items: [], total: 0, has_more: false },
            delivery_risks: { items: [], total: 0, has_more: false },
            permissions: {
              can_write: true,
              can_view_internal: true,
              can_view_delivery_risks: true,
            },
            generated_at: "2026-07-14T12:00:00Z",
          },
        };
      }

      if (path.startsWith("/delivery/portfolio")) {
        return { projects: [] };
      }

      if (path.startsWith("/governance/escalations")) {
        return {
          data: [],
          pagination: { total: 0, limit: 6, offset: 0, items: 0, has_more: false },
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

      if (path.startsWith("/governance/project-charters/panel")) {
        return {
          data: {
            charters: [],
            selected_charter: null,
            limit: 5,
            offset: 0,
            has_more: false,
          },
        };
      }

      if (path.startsWith("/governance/weekly-summary")) {
        return { data: null };
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

  it("keeps deferred register and recommendation requests out of first paint", async () => {
    renderDashboard();

    await waitFor(() => {
      expect(fetchCalls.some((path) => path.startsWith("/governance/dependencies"))).toBe(true);
    });

    expect(screen.queryByText("Loading governance tables...")).not.toBeInTheDocument();
    expect(fetchCalls.some((path) => path.startsWith("/governance/register"))).toBe(false);
    expect(fetchCalls.some((path) => path.startsWith("/projects"))).toBe(false);
    expect(fetchCalls.some((path) => path.startsWith("/governance/ai-recommendations"))).toBe(
      false,
    );
  });

  it("loads the register on activation and reuses its cached result", async () => {
    const user = userEvent.setup();
    renderDashboard();

    expect(fetchCalls.some((path) => path.startsWith("/governance/register"))).toBe(false);
    await user.click(await screen.findByRole("tab", { name: /Governance Register/i }));
    await waitFor(() => {
      expect(fetchCalls.some((path) => path.startsWith("/governance/register"))).toBe(true);
    });
    const firstRequestCount = fetchCalls.filter((path) =>
      path.startsWith("/governance/register"),
    ).length;

    await user.click(screen.getByRole("tab", { name: /Dependency Tracker/i }));
    await user.click(screen.getByRole("tab", { name: /Governance Register/i }));

    expect(fetchCalls.filter((path) => path.startsWith("/governance/register"))).toHaveLength(
      firstRequestCount,
    );
  });

  it("opens a project sheet with one composite request and no section fan-out", async () => {
    const user = userEvent.setup();
    renderDashboard();

    await user.click(await screen.findByRole("tab", { name: /Governance Register/i }));
    const project = await screen.findByText("Atlas Program");
    const before = fetchCalls.length;
    await user.click(project);

    await screen.findByText("Bounded composite sheet");
    expect(screen.getByText("Composite dependency")).toBeInTheDocument();

    const openedCalls = fetchCalls.slice(before);
    expect(
      openedCalls.filter((path) => path.startsWith("/governance/project-sheet/proj-1")),
    ).toHaveLength(1);
    expect(openedCalls.some((path) => path.startsWith("/governance/dependencies"))).toBe(false);
    expect(openedCalls.some((path) => path.startsWith("/governance/actions"))).toBe(false);
    expect(openedCalls.some((path) => path.startsWith("/governance/escalations"))).toBe(false);
    expect(openedCalls.some((path) => path.startsWith("/governance/scope-states"))).toBe(false);
    expect(openedCalls.some((path) => path.includes("/risk-alerts"))).toBe(false);

    await user.click(screen.getByRole("button", { name: "Edit" }));
    await screen.findByText("Edit dependency");
    expect(await screen.findByDisplayValue("Composite dependency")).toBeInTheDocument();
    await user.keyboard("{Escape}");

    await user.click(screen.getByRole("button", { name: "View all" }));
    await waitFor(() => {
      expect(
        fetchCalls.some(
          (path) =>
            path.startsWith("/governance/dependencies") && path.includes("project_id=proj-1"),
        ),
      ).toBe(true);
    });
  }, 10_000);

  it("loads projects only after a project-dependent workflow is opened", async () => {
    const user = userEvent.setup();
    renderDashboard();

    await waitFor(() => {
      expect(fetchCalls.some((path) => path.startsWith("/governance/dependencies"))).toBe(true);
    });
    expect(fetchCalls.some((path) => path.startsWith("/projects"))).toBe(false);

    await user.click(screen.getByRole("button", { name: "Dependency" }));

    await waitFor(() => {
      expect(fetchCalls.some((path) => path.startsWith("/projects"))).toBe(true);
    });
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
    expect(fetchCalls.some((path) => path.startsWith("/governance/project-charters/panel"))).toBe(
      false,
    );
    expect(fetchCalls.some((path) => path.startsWith("/governance/weekly-summary"))).toBe(false);
  });

  it("prefetches charter panel data on charter tab hover without first-paint fetch", async () => {
    const user = userEvent.setup();
    vi.mocked(api.listProjects).mockImplementation(async () => {
      fetchCalls.push("/projects?limit=100");
      return [{ id: "proj-1", name: "Atlas Program" }] as Awaited<
        ReturnType<typeof api.listProjects>
      >;
    });
    renderDashboard();

    await waitFor(() => {
      expect(screen.getByRole("tab", { name: /Project Charters/i })).toBeVisible();
    });
    expect(fetchCalls.some((path) => path.startsWith("/governance/project-charters/panel"))).toBe(
      false,
    );

    await user.hover(screen.getByRole("tab", { name: /Project Charters/i }));

    await waitFor(() =>
      expect(fetchCalls.some((path) => path.startsWith("/governance/project-charters/panel"))).toBe(
        true,
      ),
    );
  });

  it("prefetches weekly summary on weekly tab hover without first-paint fetch", async () => {
    const user = userEvent.setup();
    renderDashboard();

    await waitFor(() => {
      expect(screen.getByRole("tab", { name: /Governance This Week/i })).toBeVisible();
    });
    expect(fetchCalls.some((path) => path.startsWith("/governance/weekly-summary"))).toBe(false);

    await user.hover(screen.getByRole("tab", { name: /Governance This Week/i }));

    await waitFor(() =>
      expect(fetchCalls.some((path) => path.startsWith("/governance/weekly-summary"))).toBe(true),
    );
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
    expect(fetchCalls.some((path) => path.startsWith("/governance/escalations"))).toBe(true);
  });
});
