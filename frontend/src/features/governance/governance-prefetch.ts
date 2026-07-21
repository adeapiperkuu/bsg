import type { QueryClient } from "@tanstack/react-query";

import {
  governanceAnalyticsSummaryQueryOptions,
  governanceBootstrapQueryOptions,
  governanceDependenciesQueryOptions,
  governanceEscalationsQueryOptions,
} from "@/lib/queries/governance";
import { useAuthStore } from "@/stores/useAuthStore";
import type { AppRole } from "@/types/auth";

/** Must match GovernanceDashboard TABLE_PAGE_SIZE / backend GOVERNANCE_FIRST_PAINT_LIMIT. */
export const GOVERNANCE_DEFAULT_TABLE_PARAMS = {
  limit: 6,
  offset: 0,
} as const;

export const GOVERNANCE_DEFAULT_ANALYTICS_DAYS = 30;

export type GovernancePrefetchRole = AppRole | null | undefined;

function throwIfAborted(signal: AbortSignal): void {
  if (signal.aborted) {
    throw new DOMException("The operation was aborted.", "AbortError");
  }
}

function resolvePrefetchRole(role?: GovernancePrefetchRole): AppRole | undefined {
  if (role) return role;
  return useAuthStore.getState().user?.role;
}

function isClientRole(role: AppRole | undefined): boolean {
  return role === "client";
}

function isAbortError(error: unknown): boolean {
  return (
    (error instanceof DOMException && error.name === "AbortError") ||
    (error instanceof Error && error.name === "AbortError")
  );
}

/**
 * Prefetch Governance first-paint queries concurrently.
 *
 * Cross-agent single-flight stays in nav-prefetch.ts — only tasks inside this
 * Governance bundle run in parallel. Analytics detail is never prefetched.
 * Mounted-page 200 ms summary defer is unchanged for click-without-hover.
 */
export async function prefetchGovernanceRouteData(
  queryClient: QueryClient,
  signal: AbortSignal = new AbortController().signal,
  role?: GovernancePrefetchRole,
): Promise<void> {
  throwIfAborted(signal);
  const resolvedRole = resolvePrefetchRole(role);
  const client = isClientRole(resolvedRole);
  const startedAt = typeof performance !== "undefined" ? performance.now() : 0;

  const tasks: Array<Promise<unknown>> = [
    queryClient.prefetchQuery(governanceBootstrapQueryOptions),
  ];

  if (client) {
    tasks.push(
      queryClient.prefetchQuery(governanceEscalationsQueryOptions(GOVERNANCE_DEFAULT_TABLE_PARAMS)),
    );
  } else {
    // Internal: bootstrap + dependencies + summary start together (no sequential awaits).
    tasks.push(
      queryClient.prefetchQuery(
        governanceDependenciesQueryOptions(GOVERNANCE_DEFAULT_TABLE_PARAMS),
      ),
      queryClient.prefetchQuery(
        governanceAnalyticsSummaryQueryOptions(GOVERNANCE_DEFAULT_ANALYTICS_DAYS),
      ),
    );
  }

  const results = await Promise.allSettled(tasks);
  throwIfAborted(signal);

  const failedCount = results.filter((result) => result.status === "rejected").length;
  if (import.meta.env.DEV) {
    const durationMs =
      typeof performance !== "undefined" ? Math.round(performance.now() - startedAt) : undefined;
    console.debug("[governance-prefetch]", {
      event: "governance_prefetch_completed",
      governance_prefetch_role: client ? "client" : "internal",
      governance_prefetch_task_count: tasks.length,
      governance_prefetch_failed_task_count: failedCount,
      governance_prefetch_duration_ms: durationMs,
    });
  }

  // Surface non-abort failures to the nav-prefetch wrapper for logging, without
  // blocking later navigation — only if every task failed.
  if (failedCount === results.length && failedCount > 0) {
    const firstRejection = results.find((result) => result.status === "rejected");
    if (firstRejection && firstRejection.status === "rejected") {
      if (isAbortError(firstRejection.reason)) {
        throw firstRejection.reason;
      }
      throw firstRejection.reason;
    }
  }
}

export function prefetchGovernanceRouteModule(): void {
  void import("@/features/governance/GovernanceDashboard");
}

export async function prefetchGovernanceNav(
  queryClient: QueryClient,
  signal: AbortSignal = new AbortController().signal,
  role?: GovernancePrefetchRole,
): Promise<void> {
  prefetchGovernanceRouteModule();
  await prefetchGovernanceRouteData(queryClient, signal, role);
}
