import type { QueryClient } from "@tanstack/react-query";

import { fetchProjectRecommendations } from "@/features/mitigation-recommendations/api/recommendations";
import {
  resolveDefaultProjectId,
  sortByPriority,
  toPortfolioEntries,
} from "@/features/delivery/portfolio";
import {
  deliveryPortfolioQueryOptions,
  organisationsQueryOptions,
  projectDeliveryConfidenceQueryOptions,
} from "@/lib/queries/delivery";
import { queryKeys, STALE_TIME_MS } from "@/lib/queries/keys";
import type { DeliveryPortfolioResponse } from "@/lib/api";

function throwIfAborted(signal: AbortSignal): void {
  if (signal.aborted) {
    throw new DOMException("The operation was aborted.", "AbortError");
  }
}

/**
 * Warm Delivery cache sequentially so we do not open many DB sessions at once.
 *
 * `/projects` is deliberately absent: the Delivery page derives its entire project
 * universe from the portfolio payload, so warming a separately-limited project list
 * would fetch rows the page never reads.
 */
export async function prefetchDeliveryRouteData(
  queryClient: QueryClient,
  signal: AbortSignal = new AbortController().signal,
): Promise<void> {
  throwIfAborted(signal);
  await queryClient.prefetchQuery(organisationsQueryOptions);
  throwIfAborted(signal);
  await queryClient.prefetchQuery(deliveryPortfolioQueryOptions);
  throwIfAborted(signal);

  const portfolio =
    queryClient.getQueryData<DeliveryPortfolioResponse>(deliveryPortfolioQueryOptions.queryKey) ??
    (await queryClient.ensureQueryData(deliveryPortfolioQueryOptions));
  const focusProjectId = resolvePrefetchProjectId(portfolio);
  if (!focusProjectId) return;

  throwIfAborted(signal);
  await queryClient.prefetchQuery(projectDeliveryConfidenceQueryOptions(focusProjectId));
  throwIfAborted(signal);
  await queryClient.prefetchQuery({
    queryKey: queryKeys.projectRecommendations(focusProjectId),
    queryFn: () => fetchProjectRecommendations(focusProjectId),
    staleTime: STALE_TIME_MS,
  });
}

export function prefetchDeliveryNav(queryClient: QueryClient, signal?: AbortSignal): Promise<void> {
  return prefetchDeliveryRouteData(queryClient, signal ?? new AbortController().signal);
}

/**
 * Warm the project the page will actually focus on. Must mirror the page's own
 * resolution: URL first, otherwise the highest-priority project. Prefetching an
 * arbitrary first element would warm a project the page never opens.
 */
function resolvePrefetchProjectId(portfolio: DeliveryPortfolioResponse | undefined): string | null {
  const ranked = sortByPriority(toPortfolioEntries(portfolio));
  const fromUrl =
    typeof window !== "undefined"
      ? (new URLSearchParams(window.location.search).get("projectId") ?? undefined)
      : undefined;
  return resolveDefaultProjectId(ranked, fromUrl);
}
