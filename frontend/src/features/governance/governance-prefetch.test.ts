import { QueryClient } from "@tanstack/react-query";
import { afterEach, describe, expect, it, vi } from "vitest";

import {
  GOVERNANCE_DEFAULT_ANALYTICS_DAYS,
  GOVERNANCE_DEFAULT_TABLE_PARAMS,
  prefetchGovernanceNav,
  prefetchGovernanceRouteData,
  prefetchGovernanceRouteModule,
} from "@/features/governance/governance-prefetch";
import {
  governanceAnalyticsSummaryQueryOptions,
  governanceBootstrapQueryOptions,
  governanceDependenciesQueryOptions,
  governanceEscalationsQueryOptions,
} from "@/lib/queries/governance";
import { queryKeys } from "@/lib/queries/keys";
import { useAuthStore } from "@/stores/useAuthStore";

function deferred<T = void>() {
  let resolve!: (value: T | PromiseLike<T>) => void;
  let reject!: (reason?: unknown) => void;
  const promise = new Promise<T>((res, rej) => {
    resolve = res;
    reject = rej;
  });
  return { promise, resolve, reject };
}

describe("governance prefetch", () => {
  afterEach(() => {
    vi.restoreAllMocks();
    useAuthStore.setState({ user: null, isAuthenticated: false, isLoading: false });
  });

  it("uses dashboard first-page table params of limit 6", () => {
    expect(GOVERNANCE_DEFAULT_TABLE_PARAMS).toEqual({ limit: 6, offset: 0 });
    expect(GOVERNANCE_DEFAULT_ANALYTICS_DAYS).toBe(30);
  });

  it("reuses the same query factories as the mounted dashboard", () => {
    expect(governanceBootstrapQueryOptions.queryKey).toEqual(queryKeys.governanceBootstrap);
    expect(governanceDependenciesQueryOptions(GOVERNANCE_DEFAULT_TABLE_PARAMS).queryKey).toEqual(
      queryKeys.governanceDependencies(GOVERNANCE_DEFAULT_TABLE_PARAMS),
    );
    expect(governanceEscalationsQueryOptions(GOVERNANCE_DEFAULT_TABLE_PARAMS).queryKey).toEqual(
      queryKeys.governanceEscalations(GOVERNANCE_DEFAULT_TABLE_PARAMS),
    );
    expect(
      governanceAnalyticsSummaryQueryOptions(GOVERNANCE_DEFAULT_ANALYTICS_DAYS).queryKey,
    ).toEqual(queryKeys.governanceAnalyticsSummary(GOVERNANCE_DEFAULT_ANALYTICS_DAYS));
  });

  it("starts internal bootstrap, dependencies, and summary concurrently", async () => {
    const queryClient = new QueryClient();
    const bootstrap = deferred();
    const callOrder: string[] = [];

    const prefetchQuery = vi
      .spyOn(queryClient, "prefetchQuery")
      .mockImplementation(async (opts) => {
        const key = JSON.stringify(opts.queryKey);
        if (key.includes("bootstrap") || opts.queryKey === queryKeys.governanceBootstrap) {
          callOrder.push("bootstrap");
          await bootstrap.promise;
          return;
        }
        if (String(opts.queryKey).includes("dependencies") || key.includes("dependencies")) {
          callOrder.push("dependencies");
          return;
        }
        if (String(opts.queryKey).includes("summary") || key.includes("summary")) {
          callOrder.push("summary");
          return;
        }
        callOrder.push("other");
      });

    const pending = prefetchGovernanceRouteData(queryClient, undefined, "delivery_manager");

    // Flush microtasks so all prefetchQuery calls from Promise.allSettled setup run.
    await Promise.resolve();
    await Promise.resolve();

    expect(prefetchQuery).toHaveBeenCalledTimes(3);
    expect(callOrder).toEqual(["bootstrap", "dependencies", "summary"]);
    expect(prefetchQuery.mock.calls[0]?.[0]?.queryKey).toEqual(queryKeys.governanceBootstrap);
    expect(prefetchQuery.mock.calls[1]?.[0]?.queryKey).toEqual(
      queryKeys.governanceDependencies(GOVERNANCE_DEFAULT_TABLE_PARAMS),
    );
    expect(prefetchQuery.mock.calls[2]?.[0]?.queryKey).toEqual(
      queryKeys.governanceAnalyticsSummary(GOVERNANCE_DEFAULT_ANALYTICS_DAYS),
    );
    expect(
      prefetchQuery.mock.calls.some((call) => String(call[0]?.queryKey).includes("detail")),
    ).toBe(false);

    bootstrap.resolve();
    await pending;
  });

  it("starts client bootstrap and escalations concurrently without deps or summary", async () => {
    const queryClient = new QueryClient();
    const bootstrap = deferred();
    const callOrder: string[] = [];

    const prefetchQuery = vi
      .spyOn(queryClient, "prefetchQuery")
      .mockImplementation(async (opts) => {
        const key = JSON.stringify(opts.queryKey);
        if (opts.queryKey === queryKeys.governanceBootstrap) {
          callOrder.push("bootstrap");
          await bootstrap.promise;
          return;
        }
        if (key.includes("escalations")) {
          callOrder.push("escalations");
          return;
        }
        callOrder.push("other");
      });

    const pending = prefetchGovernanceRouteData(queryClient, undefined, "client");
    await Promise.resolve();
    await Promise.resolve();

    expect(prefetchQuery).toHaveBeenCalledTimes(2);
    expect(callOrder).toEqual(["bootstrap", "escalations"]);
    expect(prefetchQuery.mock.calls[1]?.[0]?.queryKey).toEqual(
      queryKeys.governanceEscalations(GOVERNANCE_DEFAULT_TABLE_PARAMS),
    );
    expect(
      prefetchQuery.mock.calls.some((call) => String(call[0]?.queryKey).includes("dependencies")),
    ).toBe(false);
    expect(
      prefetchQuery.mock.calls.some((call) => String(call[0]?.queryKey).includes("summary")),
    ).toBe(false);

    bootstrap.resolve();
    await pending;
  });

  it("does not fail the bundle when one internal task rejects", async () => {
    const queryClient = new QueryClient();
    vi.spyOn(queryClient, "prefetchQuery").mockImplementation(async (opts) => {
      if (opts.queryKey === queryKeys.governanceBootstrap) {
        throw new Error("bootstrap failed");
      }
    });

    await expect(
      prefetchGovernanceRouteData(queryClient, undefined, "delivery_manager"),
    ).resolves.toBeUndefined();
  });

  it("surfaces failure when every prefetch task rejects", async () => {
    const queryClient = new QueryClient();
    vi.spyOn(queryClient, "prefetchQuery").mockRejectedValue(new Error("network down"));

    await expect(
      prefetchGovernanceRouteData(queryClient, undefined, "delivery_manager"),
    ).rejects.toThrow("network down");
  });

  it("propagates abort without treating it as a soft failure", async () => {
    const queryClient = new QueryClient();
    const controller = new AbortController();
    vi.spyOn(queryClient, "prefetchQuery").mockResolvedValue(undefined);
    controller.abort();

    await expect(
      prefetchGovernanceRouteData(queryClient, controller.signal, "delivery_manager"),
    ).rejects.toMatchObject({ name: "AbortError" });
  });

  it("prefetches route module and data together", async () => {
    const queryClient = new QueryClient();
    vi.spyOn(queryClient, "prefetchQuery").mockResolvedValue(undefined);

    await prefetchGovernanceNav(queryClient, undefined, "delivery_manager");

    await expect(import("@/features/governance/GovernanceDashboard")).resolves.toBeDefined();
  });

  it("can prefetch the route module independently", async () => {
    prefetchGovernanceRouteModule();
    await expect(import("@/features/governance/GovernanceDashboard")).resolves.toBeDefined();
  });
});
