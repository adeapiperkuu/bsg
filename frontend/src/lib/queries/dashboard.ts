import { queryOptions, useQuery, type QueryClient } from "@tanstack/react-query";

import {
  fetchExecutiveSummary,
  fetchTowerActivity,
  fetchTowerEscalations,
  fetchTowerHealth,
  fetchTowerPulse,
  fetchTowerWork,
} from "@/lib/api";
import { queryKeys, STALE_TIME_MS } from "@/lib/queries/keys";

/**
 * The Operational Tower's sections are separate queries so the browser requests them in
 * parallel and each section of the page paints as its own data lands. Their server costs are
 * very uneven — pulse is the cheapest and health (which runs the scoring pipeline over every
 * in-flight project) is roughly twice as slow — so a single query made the entire dashboard
 * wait on its slowest part.
 */

export const towerPulseQueryOptions = queryOptions({
  queryKey: queryKeys.towerPulse,
  queryFn: fetchTowerPulse,
  staleTime: STALE_TIME_MS,
});

export const towerEscalationsQueryOptions = queryOptions({
  queryKey: queryKeys.towerEscalations,
  queryFn: fetchTowerEscalations,
  staleTime: STALE_TIME_MS,
});

export const towerHealthQueryOptions = queryOptions({
  queryKey: queryKeys.towerHealth,
  queryFn: fetchTowerHealth,
  staleTime: STALE_TIME_MS,
});

export const towerWorkQueryOptions = queryOptions({
  queryKey: queryKeys.towerWork,
  queryFn: fetchTowerWork,
  staleTime: STALE_TIME_MS,
});

export const towerActivityQueryOptions = queryOptions({
  queryKey: queryKeys.towerActivity,
  queryFn: fetchTowerActivity,
  staleTime: STALE_TIME_MS,
});

/**
 * Kick off every tower section at once, without awaiting: the route renders immediately and
 * each section paints as its own request lands.
 */
export function prefetchTowerSections(queryClient: QueryClient): void {
  void queryClient.prefetchQuery(towerPulseQueryOptions);
  void queryClient.prefetchQuery(towerEscalationsQueryOptions);
  void queryClient.prefetchQuery(towerHealthQueryOptions);
  void queryClient.prefetchQuery(towerWorkQueryOptions);
  void queryClient.prefetchQuery(towerActivityQueryOptions);
}

/**
 * The executive summary is AI-authored and stored, so it can be cached longer and is
 * fetched independently of the deterministic dashboard payload — it never blocks render.
 */
export const executiveSummaryQueryOptions = queryOptions({
  queryKey: queryKeys.executiveSummary,
  queryFn: fetchExecutiveSummary,
  staleTime: 10 * 60 * 1000,
});

export function useTowerPulseQuery() {
  return useQuery(towerPulseQueryOptions);
}

export function useTowerEscalationsQuery() {
  return useQuery(towerEscalationsQueryOptions);
}

export function useTowerHealthQuery() {
  return useQuery(towerHealthQueryOptions);
}

export function useTowerWorkQuery() {
  return useQuery(towerWorkQueryOptions);
}

export function useTowerActivityQuery() {
  return useQuery(towerActivityQueryOptions);
}

export function useExecutiveSummaryQuery() {
  return useQuery(executiveSummaryQueryOptions);
}
