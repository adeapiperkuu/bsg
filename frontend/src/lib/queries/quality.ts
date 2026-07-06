import { keepPreviousData, queryOptions, useQuery } from "@tanstack/react-query";
import { fetchQualityPage } from "@/lib/api";
import { queryKeys, STALE_TIME_MS } from "@/lib/queries/keys";

export function qualityPageQueryOptions(projectId: string | null | undefined) {
  return queryOptions({
    queryKey: queryKeys.qualityPage(projectId ?? ""),
    queryFn: () => fetchQualityPage(projectId!),
    enabled: Boolean(projectId),
    staleTime: STALE_TIME_MS,
    placeholderData: keepPreviousData,
  });
}

export function useQualityPageQuery(projectId: string | null | undefined) {
  return useQuery(qualityPageQueryOptions(projectId));
}
