import { QueryClient } from "@tanstack/react-query";
import { describe, expect, it, vi } from "vitest";

import {
  GOVERNANCE_DEFAULT_ANALYTICS_DAYS,
  GOVERNANCE_DEFAULT_TABLE_PARAMS,
  prefetchGovernanceNav,
  prefetchGovernanceRouteData,
  prefetchGovernanceRouteModule,
} from "@/features/governance/governance-prefetch";
import { queryKeys } from "@/lib/queries/keys";

describe("governance prefetch", () => {
  it("prefetches bootstrap, dependencies, and analytics summary only", async () => {
    const queryClient = new QueryClient();
    const prefetchQuery = vi.spyOn(queryClient, "prefetchQuery").mockResolvedValue(undefined);

    await prefetchGovernanceRouteData(queryClient);

    expect(prefetchQuery).toHaveBeenCalledTimes(3);
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
  });

  it("prefetches route module and data together", async () => {
    const queryClient = new QueryClient();
    vi.spyOn(queryClient, "prefetchQuery").mockResolvedValue(undefined);

    await prefetchGovernanceNav(queryClient);

    await expect(import("@/features/governance/GovernanceDashboard")).resolves.toBeDefined();
  });

  it("can prefetch the route module independently", async () => {
    prefetchGovernanceRouteModule();
    await expect(import("@/features/governance/GovernanceDashboard")).resolves.toBeDefined();
  });
});
