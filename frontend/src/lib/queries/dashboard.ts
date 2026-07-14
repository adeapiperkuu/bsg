import { queryOptions, useQuery } from "@tanstack/react-query";

import { fetchExecutiveSummary, fetchOperationalTower } from "@/lib/api";
import { queryKeys, STALE_TIME_MS } from "@/lib/queries/keys";

export const operationalTowerQueryOptions = queryOptions({
  queryKey: queryKeys.operationalTower,
  queryFn: fetchOperationalTower,
  staleTime: STALE_TIME_MS,
});

/**
 * The executive summary is AI-authored and stored, so it can be cached longer and is
 * fetched independently of the deterministic dashboard payload — it never blocks render.
 */
export const executiveSummaryQueryOptions = queryOptions({
  queryKey: queryKeys.executiveSummary,
  queryFn: fetchExecutiveSummary,
  staleTime: 10 * 60 * 1000,
});

export function useOperationalTowerQuery() {
  return useQuery(operationalTowerQueryOptions);
}

export function useExecutiveSummaryQuery() {
  return useQuery(executiveSummaryQueryOptions);
}
