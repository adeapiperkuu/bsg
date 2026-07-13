import type { QueryClient } from "@tanstack/react-query";

import { fetchProjectRecommendations } from "@/features/mitigation-recommendations/api/recommendations";
import {
  deliveryPortfolioQueryOptions,
  organisationsQueryOptions,
  projectDeliveryConfidenceQueryOptions,
  projectsQueryOptions,
} from "@/lib/queries/delivery";
import { queryKeys, STALE_TIME_MS } from "@/lib/queries/keys";
import type { ProjectRead } from "@/lib/api";

function throwIfAborted(signal: AbortSignal): void {
  if (signal.aborted) {
    throw new DOMException("The operation was aborted.", "AbortError");
  }
}

/**
 * Warm Delivery cache sequentially so we do not open many DB sessions at once.
 */
export async function prefetchDeliveryRouteData(
  queryClient: QueryClient,
  signal: AbortSignal = new AbortController().signal,
): Promise<void> {
  throwIfAborted(signal);
  await queryClient.prefetchQuery(projectsQueryOptions);
  throwIfAborted(signal);
  await queryClient.prefetchQuery(organisationsQueryOptions);
  throwIfAborted(signal);
  await queryClient.prefetchQuery(deliveryPortfolioQueryOptions);
  throwIfAborted(signal);

  const projects =
    queryClient.getQueryData<ProjectRead[]>(projectsQueryOptions.queryKey) ??
    (await queryClient.ensureQueryData(projectsQueryOptions));
  const firstProjectId = resolvePrefetchProjectId(projects);
  if (!firstProjectId) return;

  throwIfAborted(signal);
  await queryClient.prefetchQuery(projectDeliveryConfidenceQueryOptions(firstProjectId));
  throwIfAborted(signal);
  await queryClient.prefetchQuery({
    queryKey: queryKeys.projectRecommendations(firstProjectId),
    queryFn: () => fetchProjectRecommendations(firstProjectId),
    staleTime: STALE_TIME_MS,
  });
}

export function prefetchDeliveryNav(
  queryClient: QueryClient,
  signal?: AbortSignal,
): Promise<void> {
  return prefetchDeliveryRouteData(queryClient, signal ?? new AbortController().signal);
}

function resolvePrefetchProjectId(projects: ProjectRead[]): string | null {
  if (typeof window !== "undefined") {
    const fromUrl = new URLSearchParams(window.location.search).get("projectId");
    if (fromUrl && projects.some((project) => project.id === fromUrl)) {
      return fromUrl;
    }
  }
  return projects[0]?.id ?? null;
}
