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
  draftClientReportPackage,
  exportClientReportPackage,
  fetchClientDashboard,
  fetchClientIntelligenceOverview,
  fetchClientIntelligenceQueryHistory,
  fetchClientIntelligenceReportHistory,
  fetchClientIntelligenceSummary,
  fetchClientMaster,
  fetchDeliveryConfidenceHistory,
  listClientIntelligenceCommunications,
  listClientReportApprovals,
  listClientReportDeliveries,
  listClientReportPackages,
  listClientReportSchedules,
  runDueClientReportSchedules,
  transitionClientReportGovernance,
  updateClientReportSchedule,
  upsertClientReportSchedule,
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
  ClientReportCadence,
  ReportExportFormat,
  ReportGovernanceAction,
  ReportHistoryStatusFilter,
  ReportSectionConfig,
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

export function clientIntelligenceDashboardQueryOptions(projectId: string | null) {
  return queryOptions({
    queryKey: queryKeys.clientIntelligenceDashboard(projectId ?? ""),
    queryFn: () => fetchClientDashboard(projectId!),
    enabled: Boolean(projectId),
    staleTime: STALE_TIME_MS,
  });
}

export function useClientIntelligenceDashboardQuery(projectId: string | null) {
  return useQuery(clientIntelligenceDashboardQueryOptions(projectId));
}

export function clientReportSchedulesQueryOptions(projectId: string | null) {
  return queryOptions({
    queryKey: queryKeys.clientIntelligenceReportSchedules(projectId ?? ""),
    queryFn: () => listClientReportSchedules(projectId!),
    enabled: Boolean(projectId),
    staleTime: STALE_TIME_MS,
  });
}

export function useClientReportSchedulesQuery(projectId: string | null) {
  return useQuery(clientReportSchedulesQueryOptions(projectId));
}

export function clientReportPackagesQueryOptions(projectId: string | null) {
  return queryOptions({
    queryKey: queryKeys.clientIntelligenceReportPackages(projectId ?? ""),
    queryFn: () => listClientReportPackages(projectId!),
    enabled: Boolean(projectId),
    staleTime: STALE_TIME_MS,
  });
}

export function useClientReportPackagesQuery(projectId: string | null) {
  return useQuery(clientReportPackagesQueryOptions(projectId));
}

export function useClientReportApprovalsQuery(packageId: string | null) {
  return useQuery({
    queryKey: queryKeys.clientIntelligenceReportApprovals(packageId ?? ""),
    queryFn: () => listClientReportApprovals(packageId!),
    enabled: Boolean(packageId),
    staleTime: STALE_TIME_MS,
  });
}

export function useClientReportDeliveriesQuery(packageId: string | null) {
  return useQuery({
    queryKey: queryKeys.clientIntelligenceReportDeliveries(packageId ?? ""),
    queryFn: () => listClientReportDeliveries(packageId!),
    enabled: Boolean(packageId),
    staleTime: STALE_TIME_MS,
  });
}

function invalidateReportingReads(queryClient: ReturnType<typeof useQueryClient>, projectId: string) {
  return Promise.all([
    queryClient.invalidateQueries({
      queryKey: queryKeys.clientIntelligenceReportSchedules(projectId),
      exact: true,
    }),
    queryClient.invalidateQueries({
      queryKey: queryKeys.clientIntelligenceReportPackages(projectId),
      exact: true,
    }),
    queryClient.invalidateQueries({
      queryKey: queryKeys.clientIntelligenceDashboard(projectId),
      exact: true,
    }),
    queryClient.invalidateQueries({
      queryKey: queryKeys.clientIntelligenceOverview(projectId),
    }),
  ]);
}

export function useUpsertClientReportScheduleMutation(projectId: string | null) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (payload: {
      cadence: ClientReportCadence;
      enabled?: boolean;
      next_run_at?: string | null;
      sections?: ReportSectionConfig[];
    }) => upsertClientReportSchedule(projectId!, payload),
    onSuccess: async () => {
      if (projectId) await invalidateReportingReads(queryClient, projectId);
    },
  });
}

export function useUpdateClientReportScheduleMutation(projectId: string | null) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({
      scheduleId,
      payload,
    }: {
      scheduleId: string;
      payload: {
        enabled?: boolean;
        next_run_at?: string | null;
        sections?: ReportSectionConfig[];
      };
    }) => updateClientReportSchedule(scheduleId, payload),
    onSuccess: async () => {
      if (projectId) await invalidateReportingReads(queryClient, projectId);
    },
  });
}

export function useDraftClientReportPackageMutation(projectId: string | null) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (payload: {
      cadence?: ClientReportCadence;
      title?: string | null;
      sections?: ReportSectionConfig[];
      schedule_id?: string | null;
    }) => draftClientReportPackage(projectId!, payload),
    onSuccess: async () => {
      if (projectId) await invalidateReportingReads(queryClient, projectId);
    },
  });
}

export function useRunDueClientReportSchedulesMutation(projectId: string | null) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: () => runDueClientReportSchedules(projectId!),
    onSuccess: async () => {
      if (projectId) await invalidateReportingReads(queryClient, projectId);
    },
  });
}

export function useTransitionClientReportGovernanceMutation(projectId: string | null) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({
      packageId,
      action,
      comment,
      rejection_reason,
    }: {
      packageId: string;
      action: ReportGovernanceAction;
      comment?: string | null;
      rejection_reason?: string | null;
    }) =>
      transitionClientReportGovernance(packageId, {
        action,
        comment,
        rejection_reason,
      }),
    onSuccess: async (pkg) => {
      if (projectId) await invalidateReportingReads(queryClient, projectId);
      await Promise.all([
        queryClient.invalidateQueries({
          queryKey: queryKeys.clientIntelligenceReportApprovals(pkg.id),
          exact: true,
        }),
        queryClient.invalidateQueries({
          queryKey: queryKeys.clientIntelligenceReportDeliveries(pkg.id),
          exact: true,
        }),
      ]);
    },
  });
}

export function useExportClientReportPackageMutation() {
  return useMutation({
    mutationFn: ({
      packageId,
      exportFormat,
    }: {
      packageId: string;
      exportFormat: ReportExportFormat;
    }) => exportClientReportPackage(packageId, exportFormat),
  });
}
