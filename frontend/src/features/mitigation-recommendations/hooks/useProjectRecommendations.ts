import {
  useMutation,
  useQuery,
  useQueryClient,
  type QueryClient,
} from "@tanstack/react-query";
import {
  acceptRecommendation,
  assignRecommendationOwner,
  fetchProjectRecommendations,
  rejectRecommendation,
} from "@/features/mitigation-recommendations/api/recommendations";
import type {
  AssignOwnerPayload,
  MitigationRecommendation,
  ProjectRecommendationsResponse,
  RecommendationStatus,
} from "@/features/mitigation-recommendations/types";
import { queryKeys, STALE_TIME_MS } from "@/lib/queries/keys";

function updateRecommendationInCache(
  queryClient: QueryClient,
  projectId: string,
  recommendationId: string,
  updater: (item: MitigationRecommendation) => MitigationRecommendation,
) {
  queryClient.setQueryData<ProjectRecommendationsResponse>(
    queryKeys.projectRecommendations(projectId),
    (current) => {
      if (!current) return current;
      return {
        ...current,
        data: current.data.map((item) =>
          item.id === recommendationId ? updater(item) : item,
        ),
      };
    },
  );
}

export function useProjectRecommendationsQuery(projectId: string | null) {
  return useQuery({
    queryKey: queryKeys.projectRecommendations(projectId ?? ""),
    queryFn: () => fetchProjectRecommendations(projectId!),
    enabled: Boolean(projectId),
    staleTime: STALE_TIME_MS,
  });
}

export function useAcceptRecommendationMutation(projectId: string | null) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: acceptRecommendation,
    onMutate: async (recommendationId) => {
      if (!projectId) return;
      await queryClient.cancelQueries({
        queryKey: queryKeys.projectRecommendations(projectId),
      });
      const previous = queryClient.getQueryData<ProjectRecommendationsResponse>(
        queryKeys.projectRecommendations(projectId),
      );
      updateRecommendationInCache(queryClient, projectId, recommendationId, (item) => ({
        ...item,
        status: "accepted" as RecommendationStatus,
      }));
      return { previous };
    },
    onError: (_error, _id, context) => {
      if (!projectId || !context?.previous) return;
      queryClient.setQueryData(queryKeys.projectRecommendations(projectId), context.previous);
    },
    onSettled: () => {
      if (!projectId) return;
      void queryClient.invalidateQueries({
        queryKey: queryKeys.projectRecommendations(projectId),
      });
    },
  });
}

export function useRejectRecommendationMutation(projectId: string | null) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: rejectRecommendation,
    onMutate: async (recommendationId) => {
      if (!projectId) return;
      await queryClient.cancelQueries({
        queryKey: queryKeys.projectRecommendations(projectId),
      });
      const previous = queryClient.getQueryData<ProjectRecommendationsResponse>(
        queryKeys.projectRecommendations(projectId),
      );
      updateRecommendationInCache(queryClient, projectId, recommendationId, (item) => ({
        ...item,
        status: "rejected" as RecommendationStatus,
      }));
      return { previous };
    },
    onError: (_error, _id, context) => {
      if (!projectId || !context?.previous) return;
      queryClient.setQueryData(queryKeys.projectRecommendations(projectId), context.previous);
    },
    onSettled: () => {
      if (!projectId) return;
      void queryClient.invalidateQueries({
        queryKey: queryKeys.projectRecommendations(projectId),
      });
    },
  });
}

export function useAssignRecommendationOwnerMutation(projectId: string | null) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({
      recommendationId,
      payload,
    }: {
      recommendationId: string;
      payload: AssignOwnerPayload;
    }) => assignRecommendationOwner(recommendationId, payload),
    onMutate: async ({ recommendationId, payload }) => {
      if (!projectId) return;
      await queryClient.cancelQueries({
        queryKey: queryKeys.projectRecommendations(projectId),
      });
      const previous = queryClient.getQueryData<ProjectRecommendationsResponse>(
        queryKeys.projectRecommendations(projectId),
      );
      const ownerLabel =
        payload.owner_id == null
          ? null
          : previous?.assignable_owners.find(
              (owner) =>
                owner.owner_id === payload.owner_id &&
                owner.owner_type === payload.owner_type,
            )?.label ?? "Assigned";
      updateRecommendationInCache(queryClient, projectId, recommendationId, (item) => ({
        ...item,
        owner_type: payload.owner_type,
        owner_id: payload.owner_id,
        owner_label: ownerLabel,
      }));
      return { previous };
    },
    onError: (_error, _vars, context) => {
      if (!projectId || !context?.previous) return;
      queryClient.setQueryData(queryKeys.projectRecommendations(projectId), context.previous);
    },
    onSettled: () => {
      if (!projectId) return;
      void queryClient.invalidateQueries({
        queryKey: queryKeys.projectRecommendations(projectId),
      });
    },
  });
}
