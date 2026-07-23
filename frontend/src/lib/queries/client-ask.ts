import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { createClientAskQuery, fetchClientAskQueryHistory } from "@/lib/api/client-ask";
import { queryKeys, STALE_TIME_MS } from "@/lib/queries/keys";

const CLIENT_ASK_HISTORY_LIMIT = 20;

export function useClientAskQueryHistory(projectId: string | null) {
  return useQuery({
    queryKey: queryKeys.clientAskQueryHistory(projectId ?? ""),
    queryFn: () =>
      fetchClientAskQueryHistory(projectId!, {
        limit: CLIENT_ASK_HISTORY_LIMIT,
        offset: 0,
      }),
    enabled: Boolean(projectId),
    staleTime: STALE_TIME_MS,
  });
}

export function useCreateClientAskQueryMutation() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ projectId, question }: { projectId: string; question: string }) =>
      createClientAskQuery(projectId, question),
    onSuccess: (_result, variables) => {
      void queryClient.invalidateQueries({
        queryKey: queryKeys.clientAskQueryHistory(variables.projectId),
        exact: true,
      });
    },
  });
}
