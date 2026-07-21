import { keepPreviousData, queryOptions, useQuery } from "@tanstack/react-query";
import type { QueryClient } from "@tanstack/react-query";
import { fetchQualityPage } from "@/lib/api";
import { projectsQueryOptions } from "@/lib/queries/delivery";
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

/**
 * Warms the /quality route's data in parallel: `projects` (needed to resolve
 * which project to show) and, once a projectId is known, that project's
 * quality-page. Both requests are kicked off together instead of the
 * previous waterfall -- projects only began after auth resolved, and
 * quality-page only after projects resolved, adding several seconds of pure
 * serialization on a cold load (PERF_IMPLEMENTATION_PLAN.md Phase 1B).
 *
 * Called from two places (both matter):
 * - The `/quality` route's `loader`, for SSR and for plain client-side (SPA)
 *   navigations into the route.
 * - A mount effect in `QualityPage` itself. This app's root route gates
 *   rendering on a client-only auth bootstrap (AuthProvider), not a router
 *   `beforeLoad`/loader, and there is no query-dehydration bridge from the
 *   server's request-scoped QueryClient to the client's. That means on a
 *   cold/hard load, TanStack Start's hydration reuses the SSR match without
 *   re-invoking the loader against the *client* QueryClient -- confirmed via
 *   resource timing while building this fix, the loader alone left
 *   quality-page waiting on projects to finish. The mount effect is what
 *   actually guarantees the overlap in that scenario.
 * Calling this twice in short succession is harmless: `ensureQueryData`
 * dedupes against the same in-flight/cached query per queryKey.
 *
 * Failures are swallowed on purpose: this is a background warm-up, not the
 * page's source of truth for data or errors -- `useProjectsQuery` /
 * `useQualityPageQuery` (rendered via `QualityDashboard`) own that already.
 * Letting a rejection (e.g. a 401 on an unauthenticated direct hit) escape
 * would reject the route loader and show the route's generic
 * `errorComponent` instead of `AuthProvider`'s normal login redirect.
 */
export async function loadQualityRouteData(
  queryClient: QueryClient,
  projectId: string | undefined,
): Promise<void> {
  await Promise.all([
    queryClient.ensureQueryData(projectsQueryOptions).catch(() => undefined),
    projectId
      ? queryClient.ensureQueryData(qualityPageQueryOptions(projectId)).catch(() => undefined)
      : Promise.resolve(),
  ]);
}

/**
 * Warms the QI page's data for whichever project `/quality` would show
 * first (same resolution as its own route: the first entry in `projects`),
 * WITHOUT warming any other project -- project-switching is already fast
 * post-Phase-2A, so there's no need to pay for the other ~27 projects'
 * quality-page queries on the offchance they're visited
 * (PERF_IMPLEMENTATION_PLAN.md Phase 4).
 *
 * Intentionally separate from `loadQualityRouteData` above: that function's
 * contract is "warm exactly the projectId I was given" (used by the
 * `/quality` route itself, which already knows or resolves its own
 * projectId via the URL). This function's job is "figure out the default
 * project, then warm it" -- for a caller (the dashboard) that doesn't know
 * or care which project that is.
 *
 * Failures are swallowed on purpose: this is a background warm-up triggered
 * from the Operational Tower, not a data source anything renders from --
 * the same posture as `loadQualityRouteData`.
 */
export async function prefetchDefaultQualityPage(queryClient: QueryClient): Promise<void> {
  const projects = await queryClient.ensureQueryData(projectsQueryOptions).catch(() => []);
  const firstProjectId = projects[0]?.id;
  if (!firstProjectId) return;
  await queryClient.prefetchQuery(qualityPageQueryOptions(firstProjectId)).catch(() => undefined);
}
