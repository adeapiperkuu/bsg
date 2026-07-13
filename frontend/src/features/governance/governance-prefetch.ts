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

function throwIfAborted(signal: AbortSignal): void {
  if (signal.aborted) {
    throw new DOMException("The operation was aborted.", "AbortError");
  }
}

export async function prefetchGovernanceRouteData(
  queryClient: QueryClient,
  signal: AbortSignal = new AbortController().signal,
): Promise<void> {
  throwIfAborted(signal);
  await queryClient.prefetchQuery(governanceBootstrapQueryOptions);
  throwIfAborted(signal);
  await queryClient.prefetchQuery(
    governanceDependenciesQueryOptions(GOVERNANCE_DEFAULT_TABLE_PARAMS),
  );
  throwIfAborted(signal);
  await queryClient.prefetchQuery(
    governanceAnalyticsSummaryQueryOptions(GOVERNANCE_DEFAULT_ANALYTICS_DAYS),
  );
}

export function prefetchGovernanceRouteModule(): void {
  void import("@/features/governance/GovernanceDashboard");
}

export async function prefetchGovernanceNav(
  queryClient: QueryClient,
  signal: AbortSignal = new AbortController().signal,
): Promise<void> {
  prefetchGovernanceRouteModule();
  await prefetchGovernanceRouteData(queryClient, signal);
}
