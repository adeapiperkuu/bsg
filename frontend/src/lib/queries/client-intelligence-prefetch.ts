import type { QueryClient } from "@tanstack/react-query";

import {
  QUERY_HISTORY_PAGE_SIZE,
  clientIntelligenceCommunicationsQueryOptions,
  clientIntelligenceDeliveryConfidenceHistoryQueryOptions,
  clientIntelligenceOverviewQueryOptions,
  clientIntelligenceProjectSummaryQueryOptions,
} from "@/lib/queries/client-intelligence";
import { queryKeys, STALE_TIME_MS } from "@/lib/queries/keys";
import {
  fetchClientIntelligenceQueryHistory,
  fetchClientIntelligenceReportHistory,
} from "@/lib/api";

const REPORT_HISTORY_PAGE_SIZE = 20;
const PREFETCH_HOVER_DELAY_MS = 250;

const pendingPrefetchTimers = new Map<string, ReturnType<typeof setTimeout>>();

/**
 * Warm Client Intelligence project caches after a short intentional hover.
 * Delayed so click-without-dwell does not double-fetch with selection.
 */
export function scheduleClientIntelligenceProjectPrefetch(
  queryClient: QueryClient,
  projectId: string,
): void {
  if (!projectId) return;
  cancelClientIntelligenceProjectPrefetch(projectId);
  const timer = setTimeout(() => {
    pendingPrefetchTimers.delete(projectId);
    prefetchClientIntelligenceProject(queryClient, projectId);
  }, PREFETCH_HOVER_DELAY_MS);
  pendingPrefetchTimers.set(projectId, timer);
}

export function cancelClientIntelligenceProjectPrefetch(projectId: string): void {
  const timer = pendingPrefetchTimers.get(projectId);
  if (!timer) return;
  clearTimeout(timer);
  pendingPrefetchTimers.delete(projectId);
}

export function clearClientIntelligenceProjectPrefetchTimers(): void {
  for (const timer of pendingPrefetchTimers.values()) {
    clearTimeout(timer);
  }
  pendingPrefetchTimers.clear();
}

export function prefetchClientIntelligenceProject(
  queryClient: QueryClient,
  projectId: string,
): void {
  if (!projectId) return;

  void queryClient.prefetchQuery(clientIntelligenceOverviewQueryOptions(projectId));
  void queryClient.prefetchQuery(
    clientIntelligenceDeliveryConfidenceHistoryQueryOptions(projectId),
  );
  void queryClient.prefetchQuery(clientIntelligenceCommunicationsQueryOptions(projectId));
  void queryClient.prefetchQuery(clientIntelligenceProjectSummaryQueryOptions(projectId));
  void queryClient.prefetchInfiniteQuery({
    queryKey: queryKeys.clientIntelligenceReportHistory(projectId, "all"),
    queryFn: ({ pageParam }) =>
      fetchClientIntelligenceReportHistory(projectId, {
        limit: REPORT_HISTORY_PAGE_SIZE,
        offset: pageParam,
        status: "all",
      }),
    initialPageParam: 0,
    staleTime: STALE_TIME_MS,
  });
  void queryClient.prefetchInfiniteQuery({
    queryKey: queryKeys.clientIntelligenceQueryHistory(projectId),
    queryFn: ({ pageParam }) =>
      fetchClientIntelligenceQueryHistory(projectId, {
        limit: QUERY_HISTORY_PAGE_SIZE,
        offset: pageParam,
      }),
    initialPageParam: 0,
    staleTime: STALE_TIME_MS,
  });
}
