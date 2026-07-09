import type { QueryClient } from "@tanstack/react-query";

import {
  governanceAnalyticsSummaryQueryOptions,
  governanceBootstrapQueryOptions,
  governanceDependenciesQueryOptions,
} from "@/lib/queries/governance";

export const GOVERNANCE_DEFAULT_TABLE_PARAMS = {
  limit: 6,
  offset: 0,
} as const;

export const GOVERNANCE_DEFAULT_ANALYTICS_DAYS = 30;

export function prefetchGovernanceRouteData(queryClient: QueryClient): void {
  void queryClient.prefetchQuery(governanceBootstrapQueryOptions);
  void queryClient.prefetchQuery(
    governanceDependenciesQueryOptions(GOVERNANCE_DEFAULT_TABLE_PARAMS),
  );
  void queryClient.prefetchQuery(
    governanceAnalyticsSummaryQueryOptions(GOVERNANCE_DEFAULT_ANALYTICS_DAYS),
  );
}

export function prefetchGovernanceRouteModule(): void {
  void import("@/features/governance/GovernanceDashboard");
}

export function prefetchGovernanceNav(queryClient: QueryClient): void {
  prefetchGovernanceRouteData(queryClient);
  prefetchGovernanceRouteModule();
}
