import {
  queryOptions,
  useInfiniteQuery,
  useMutation,
  useQuery,
  useQueryClient,
  type InfiniteData,
} from "@tanstack/react-query";

import {
  createClientIntelligenceQuery,
  fetchClientIntelligenceOverview,
  fetchClientIntelligenceQueryHistory,
  fetchClientIntelligenceReportHistory,
  fetchClientIntelligenceSummary,
  fetchClientMaster,
  fetchDeliveryConfidenceHistory,
  listClientIntelligenceCommunications,
} from "@/lib/api";
import {
  insertPersistedQueryIntoHistoryCache,
  localPendingQueryHistory,
  localUnavailableQueryHistory,
  mergeServerHistoryPageWithPersistedQuery,
  QUERY_HISTORY_PAGE_SIZE,
} from "@/lib/queries/client-intelligence-query-history";
import { queryKeys, STALE_TIME_MS } from "@/lib/queries/keys";
import type {
  ClientIntelligenceQueryHistory,
  ReportHistoryStatusFilter,
} from "@/types/client-intelligence";

export {
  insertPersistedQueryIntoHistoryCache,
  localPendingQueryHistory,
  localUnavailableQueryHistory,
  mergeServerHistoryPageWithPersistedQuery,
  QUERY_HISTORY_PAGE_SIZE,
} from "@/lib/queries/client-intelligence-query-history";

const REPORT_HISTORY_PAGE_SIZE = 20;

export function clientIntelligenceOverviewQueryOptions(projectId: string | null, asOf?: string) {
  return queryOptions({
    queryKey: queryKeys.clientIntelligenceOverview(projectId ?? "", asOf),
    queryFn: () => fetchClientIntelligenceOverview(projectId!, asOf),
    enabled: Boolean(projectId),
    staleTime: STALE_TIME_MS,
  });
}

export function useClientIntelligenceOverviewQuery(projectId: string | null, asOf?: string) {
  return useQuery(clientIntelligenceOverviewQueryOptions(projectId, asOf));
}

export function clientIntelligenceDeliveryConfidenceHistoryQueryOptions(projectId: string | null) {
  return queryOptions({
    queryKey: queryKeys.clientIntelligenceDeliveryConfidenceHistory(projectId ?? ""),
    queryFn: () => fetchDeliveryConfidenceHistory(projectId!),
    enabled: Boolean(projectId),
    staleTime: STALE_TIME_MS,
  });
}

export function useClientIntelligenceDeliveryConfidenceHistoryQuery(projectId: string | null) {
  return useQuery(clientIntelligenceDeliveryConfidenceHistoryQueryOptions(projectId));
}

export function clientIntelligenceSummaryQueryOptions() {
  return queryOptions({
    queryKey: queryKeys.clientIntelligenceSummary,
    queryFn: () => fetchClientIntelligenceSummary(),
    staleTime: STALE_TIME_MS,
  });
}

export function useClientIntelligenceSummaryQuery() {
  return useQuery(clientIntelligenceSummaryQueryOptions());
}

export function clientMasterQueryOptions() {
  return queryOptions({
    queryKey: queryKeys.clientIntelligenceMaster,
    queryFn: fetchClientMaster,
    staleTime: STALE_TIME_MS,
  });
}

export function useClientMasterQuery() {
  return useQuery(clientMasterQueryOptions());
}

export function clientIntelligenceCommunicationsQueryOptions(projectId: string | null) {
  return queryOptions({
    queryKey: queryKeys.clientIntelligenceCommunications(projectId ?? ""),
    queryFn: () => listClientIntelligenceCommunications(projectId!),
    enabled: Boolean(projectId),
    staleTime: STALE_TIME_MS,
  });
}

export function useClientIntelligenceCommunicationsQuery(projectId: string | null) {
  return useQuery(clientIntelligenceCommunicationsQueryOptions(projectId));
}

export function useClientIntelligenceReportHistoryQuery(
  projectId: string | null,
  status: ReportHistoryStatusFilter = "all",
) {
  return useInfiniteQuery({
    queryKey: queryKeys.clientIntelligenceReportHistory(projectId ?? "", status),
    queryFn: ({ pageParam }) =>
      fetchClientIntelligenceReportHistory(projectId!, {
        limit: REPORT_HISTORY_PAGE_SIZE,
        offset: pageParam,
        status,
      }),
    initialPageParam: 0,
    getNextPageParam: (lastPage) =>
      lastPage.has_more ? lastPage.offset + lastPage.items.length : undefined,
    enabled: Boolean(projectId),
    staleTime: STALE_TIME_MS,
  });
}

export function clientIntelligenceProjectSummaryQueryOptions(projectId: string | null) {
  return queryOptions({
    queryKey: queryKeys.clientIntelligenceProjectSummary(projectId ?? ""),
    queryFn: () => fetchClientIntelligenceSummary(projectId!),
    enabled: Boolean(projectId),
    staleTime: STALE_TIME_MS,
  });
}

export function useClientIntelligenceProjectSummaryQuery(projectId: string | null) {
  return useQuery(clientIntelligenceProjectSummaryQueryOptions(projectId));
}

export function useClientIntelligenceQueryHistoryQuery(projectId: string | null) {
  return useInfiniteQuery({
    queryKey: queryKeys.clientIntelligenceQueryHistory(projectId ?? ""),
    queryFn: ({ pageParam }) =>
      fetchClientIntelligenceQueryHistory(projectId!, {
        limit: QUERY_HISTORY_PAGE_SIZE,
        offset: pageParam,
      }),
    initialPageParam: 0,
    getNextPageParam: (lastPage) =>
      lastPage.has_more ? lastPage.offset + lastPage.items.length : undefined,
    enabled: Boolean(projectId),
    staleTime: STALE_TIME_MS,
  });
}

/**
 * Asks a Client Intelligence question and, on success, inserts the returned
 * persisted query into that project's history cache with page-limit integrity,
 * then invalidates summary for the asked project only.
 */
export function useCreateClientIntelligenceQueryMutation() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ projectId, question }: { projectId: string; question: string }) =>
      createClientIntelligenceQuery(projectId, question),
    onSuccess: (result, variables) => {
      const historyKey = queryKeys.clientIntelligenceQueryHistory(variables.projectId);
      const previous =
        queryClient.getQueryData<InfiniteData<ClientIntelligenceQueryHistory>>(historyKey);

      if (previous?.pages?.length) {
        const next = insertPersistedQueryIntoHistoryCache(previous, result, variables.projectId);
        if (next) {
          queryClient.setQueryData(historyKey, next);
        }
      } else {
        // Do not fabricate total=1 as authoritative history. Keep the persisted
        // result visible, then reconcile with the exact-project first page.
        queryClient.setQueryData(historyKey, localPendingQueryHistory(variables.projectId, result));
        void fetchClientIntelligenceQueryHistory(variables.projectId, {
          limit: QUERY_HISTORY_PAGE_SIZE,
          offset: 0,
        })
          .then((page) => {
            queryClient.setQueryData(historyKey, {
              pages: [mergeServerHistoryPageWithPersistedQuery(page, result)],
              pageParams: [0],
            } satisfies InfiniteData<ClientIntelligenceQueryHistory>);
          })
          .catch(() => {
            queryClient.setQueryData(
              historyKey,
              localUnavailableQueryHistory(variables.projectId, result),
            );
          });
      }

      void Promise.all([
        queryClient.invalidateQueries({
          queryKey: queryKeys.clientIntelligenceProjectSummary(variables.projectId),
          exact: true,
        }),
        queryClient.invalidateQueries({
          queryKey: queryKeys.clientIntelligenceSummary,
          exact: true,
        }),
        // Mark history stale without an immediate infinite refetch that could
        // wipe the just-inserted persisted result before the list catches up.
        queryClient.invalidateQueries({
          queryKey: historyKey,
          exact: true,
          refetchType: "none",
        }),
      ]);
    },
  });
}
