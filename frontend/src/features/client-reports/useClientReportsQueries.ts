/**
 * Client published archive queries (`/client/reports`).
 * Sent-only list + lazy detail. No mutations.
 */

import { queryOptions, useQuery } from "@tanstack/react-query";

import { getCommunication, listClientCommunications } from "@/lib/api";
import {
  COMMUNICATIONS_DETAIL_STALE_TIME_MS,
  COMMUNICATIONS_LIST_STALE_TIME_MS,
  queryKeys,
} from "@/lib/queries/keys";

export const clientReportQueryKeys = {
  all: ["client-communications"] as const,
  lists: () => [...clientReportQueryKeys.all, "list"] as const,
  list: (limit = 30, offset = 0) => queryKeys.clientCommunicationsList({ limit, offset }),
  detail: (id: string) => queryKeys.communicationDetail(id),
};

export function clientCommunicationsListQueryOptions(limit = 30, offset = 0) {
  return queryOptions({
    queryKey: clientReportQueryKeys.list(limit, offset),
    queryFn: () => listClientCommunications({ limit, offset }),
    staleTime: COMMUNICATIONS_LIST_STALE_TIME_MS,
  });
}

export function clientCommunicationDetailQueryOptions(communicationId: string | null) {
  return queryOptions({
    queryKey: clientReportQueryKeys.detail(communicationId ?? ""),
    queryFn: () => getCommunication(communicationId!),
    enabled: Boolean(communicationId),
    staleTime: COMMUNICATIONS_DETAIL_STALE_TIME_MS,
  });
}

export function useClientReportsQueries(selectedId: string | null) {
  const listQuery = useQuery(clientCommunicationsListQueryOptions());
  const detailQuery = useQuery(clientCommunicationDetailQueryOptions(selectedId));
  return { listQuery, detailQuery };
}
