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

/**
 * Warm the Delivery page React Query cache before navigation.
 * Called on nav hover/focus so KPIs/table can paint from cache on click.
 */
export function prefetchDeliveryRouteData(queryClient: QueryClient): void {
  void queryClient.prefetchQuery(projectsQueryOptions);
  void queryClient.prefetchQuery(organisationsQueryOptions);
  void queryClient.prefetchQuery(deliveryPortfolioQueryOptions);

  void (async () => {
    const projects = await queryClient.ensureQueryData(projectsQueryOptions);
    const firstProjectId = resolvePrefetchProjectId(projects);
    if (!firstProjectId) return;

    void queryClient.prefetchQuery(projectDeliveryConfidenceQueryOptions(firstProjectId));
    void queryClient.prefetchQuery({
      queryKey: queryKeys.projectRecommendations(firstProjectId),
      queryFn: () => fetchProjectRecommendations(firstProjectId),
      staleTime: STALE_TIME_MS,
    });
  })();
}

export function prefetchDeliveryNav(queryClient: QueryClient): void {
  prefetchDeliveryRouteData(queryClient);
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
