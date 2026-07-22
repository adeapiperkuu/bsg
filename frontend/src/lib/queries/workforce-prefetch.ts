import type { QueryClient } from "@tanstack/react-query";

import { projectsQueryOptions } from "@/lib/queries/delivery";
import {
  projectCapabilityGapsQueryOptions,
  projectSkillMatrixQueryOptions,
  projectTrainingGapsQueryOptions,
  projectUtilizationQueryOptions,
  projectWorkforceOptimizationQueryOptions,
  projectWorkforceSummaryQueryOptions,
} from "@/lib/queries/workforce";
import { queryKeys, WORKFORCE_PROJECT_STALE_TIME_MS } from "@/lib/queries/keys";
import { fetchProjectRecommendations } from "@/features/mitigation-recommendations/api/recommendations";

/**
 * Warm Workforce route data without awaiting in the router loader.
 *
 * Prefetches in two waves so above-the-fold sections (summary / matrix / util)
 * can paint before heavier gaps / recommendations / optimization finish.
 */
export async function loadWorkforceRouteData(
  queryClient: QueryClient,
  projectId?: string | null,
): Promise<void> {
  await queryClient.ensureQueryData(projectsQueryOptions).catch(() => undefined);
  if (!projectId) return;

  // Wave 1 — KPIs + matrix (paint first)
  await Promise.all([
    queryClient
      .ensureQueryData(projectWorkforceSummaryQueryOptions(projectId, true))
      .catch(() => undefined),
    queryClient
      .ensureQueryData(projectSkillMatrixQueryOptions(projectId, true))
      .catch(() => undefined),
    queryClient
      .ensureQueryData(projectUtilizationQueryOptions(projectId, true))
      .catch(() => undefined),
  ]);

  // Wave 2 — remaining sections (fire-and-forget; page already has first content)
  void Promise.all([
    queryClient
      .ensureQueryData(projectTrainingGapsQueryOptions(projectId, true))
      .catch(() => undefined),
    queryClient
      .ensureQueryData(projectCapabilityGapsQueryOptions(projectId, true))
      .catch(() => undefined),
    queryClient
      .ensureQueryData({
        queryKey: queryKeys.projectRecommendations(projectId),
        queryFn: () => fetchProjectRecommendations(projectId),
        staleTime: WORKFORCE_PROJECT_STALE_TIME_MS,
      })
      .catch(() => undefined),
    queryClient
      .ensureQueryData(projectWorkforceOptimizationQueryOptions(projectId, true))
      .catch(() => undefined),
  ]);
}
