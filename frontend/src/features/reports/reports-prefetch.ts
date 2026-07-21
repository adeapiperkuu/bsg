import type { QueryClient } from "@tanstack/react-query";

import { communicationsListQueryOptions } from "@/features/reports/useReportsQueries";

function throwIfAborted(signal: AbortSignal): void {
  if (signal.aborted) {
    throw new DOMException("The operation was aborted.", "AbortError");
  }
}

/**
 * Prefetch only the lightweight org-scoped communications list for `/reports`.
 * Do not prefetch detail for every report.
 */
export async function prefetchReportsRouteData(
  queryClient: QueryClient,
  signal: AbortSignal = new AbortController().signal,
): Promise<void> {
  throwIfAborted(signal);
  await queryClient.prefetchQuery(communicationsListQueryOptions({ limit: 30, offset: 0 }));
}

export function prefetchReportsNav(
  queryClient: QueryClient,
  signal?: AbortSignal,
): Promise<void> {
  return prefetchReportsRouteData(queryClient, signal ?? new AbortController().signal);
}
