/**
 * TanStack Query hooks for PM communications (Phase 3).
 *
 * List: GET /communications (lightweight, no bodies)
 * Detail: GET /communications/{id} (lazy, selection-only)
 */

import { keepPreviousData, queryOptions, useQuery } from "@tanstack/react-query";

import { getCommunication, listCommunications } from "@/lib/api";
import {
  COMMUNICATIONS_DETAIL_STALE_TIME_MS,
  COMMUNICATIONS_LIST_STALE_TIME_MS,
  queryKeys,
} from "@/lib/queries/keys";
import type { CommunicationStatus } from "@/types/communications";

export type CommunicationsListFilters = {
  status?: CommunicationStatus | null;
  projectId?: string | null;
  limit?: number;
  offset?: number;
};

export const reportQueryKeys = {
  all: ["communications"] as const,
  lists: () => [...reportQueryKeys.all, "list"] as const,
  list: (filters: CommunicationsListFilters) =>
    queryKeys.communicationsList({
      status: filters.status ?? null,
      projectId: filters.projectId ?? null,
      limit: filters.limit ?? 30,
      offset: filters.offset ?? 0,
    }),
  details: () => [...reportQueryKeys.all, "detail"] as const,
  detail: (communicationId: string) => queryKeys.communicationDetail(communicationId),
};

export function communicationsListQueryOptions(filters: CommunicationsListFilters = {}) {
  const limit = filters.limit ?? 30;
  const offset = filters.offset ?? 0;
  return queryOptions({
    queryKey: reportQueryKeys.list({ ...filters, limit, offset }),
    queryFn: () =>
      listCommunications({
        status: filters.status ?? undefined,
        project_id: filters.projectId ?? undefined,
        limit,
        offset,
      }),
    staleTime: COMMUNICATIONS_LIST_STALE_TIME_MS,
    placeholderData: keepPreviousData,
  });
}

export function communicationDetailQueryOptions(communicationId: string | null) {
  return queryOptions({
    queryKey: reportQueryKeys.detail(communicationId ?? ""),
    queryFn: () => getCommunication(communicationId!),
    enabled: Boolean(communicationId),
    staleTime: COMMUNICATIONS_DETAIL_STALE_TIME_MS,
  });
}

export function useCommunicationsListQuery(filters: CommunicationsListFilters = {}) {
  return useQuery(communicationsListQueryOptions(filters));
}

export function useCommunicationDetailQuery(communicationId: string | null) {
  return useQuery(communicationDetailQueryOptions(communicationId));
}

/** Convenience bundle used by ReportsPage. */
export function useReportsQueries(args: {
  status?: CommunicationStatus | null;
  selectedId: string | null;
  limit?: number;
  offset?: number;
}) {
  const listQuery = useCommunicationsListQuery({
    status: args.status,
    limit: args.limit ?? 30,
    offset: args.offset ?? 0,
  });
  const detailQuery = useCommunicationDetailQuery(args.selectedId);
  return { listQuery, detailQuery, reportQueryKeys };
}
