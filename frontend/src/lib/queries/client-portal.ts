import { queryOptions, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { fetchClientProjectDashboard, submitClientChangeRequest } from "@/lib/api";
import { queryKeys, STALE_TIME_MS } from "@/lib/queries/keys";
import type { ClientChangeRequestCreate } from "@/types/client-portal";

export function clientProjectDashboardQueryOptions(projectId: string | null) {
  return queryOptions({
    queryKey: queryKeys.clientProjectDashboard(projectId ?? ""),
    queryFn: () => fetchClientProjectDashboard(projectId!),
    enabled: Boolean(projectId),
    staleTime: STALE_TIME_MS,
  });
}

export function useClientProjectDashboardQuery(projectId: string | null) {
  return useQuery(clientProjectDashboardQueryOptions(projectId));
}

export function useSubmitClientChangeRequest(projectId: string | null) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (payload: ClientChangeRequestCreate) =>
      submitClientChangeRequest(projectId!, payload),
    onSuccess: () =>
      queryClient.invalidateQueries({
        queryKey: queryKeys.clientProjectDashboard(projectId ?? ""),
        exact: true,
      }),
  });
}
