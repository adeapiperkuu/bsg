import type { QueryClient } from "@tanstack/react-query";

import { prefetchDeliveryNav } from "@/lib/queries/delivery-prefetch";
import { adminProjectsQueryOptions } from "@/lib/queries/delivery";
import { prefetchGovernanceNav } from "@/features/governance/governance-prefetch";
import { prefetchKnowledgeNav } from "@/lib/queries/knowledge-prefetch";
import { prefetchReportsNav } from "@/features/reports/reports-prefetch";

/**
 * Sidebar nav prefetch coordinator.
 *
 * Hover storms + parallel agent loads exhaust Supabase session-mode (~15 clients).
 * Rules: linger before prefetch, one flight at a time, abort generation on switch.
 */
const HOVER_LINGER_MS = 450;
const SAME_ROUTE_COOLDOWN_MS = 2_500;

type PrefetchPath =
  | "/delivery"
  | "/governance"
  | "/knowledge"
  | "/admin/projects"
  | "/reports";

type Prefetcher = (queryClient: QueryClient, signal: AbortSignal) => Promise<void>;

const PREFETCHERS: Record<PrefetchPath, Prefetcher> = {
  "/delivery": (qc, signal) => prefetchDeliveryNav(qc, signal),
  "/governance": (qc, signal) => prefetchGovernanceNav(qc, signal),
  "/knowledge": (qc, signal) => prefetchKnowledgeNav(qc, signal),
  "/admin/projects": (qc) => qc.prefetchQuery(adminProjectsQueryOptions),
  "/reports": (qc, signal) => prefetchReportsNav(qc, signal),
};

let lingerTimer: ReturnType<typeof setTimeout> | null = null;
let pendingPath: PrefetchPath | null = null;
let activeController: AbortController | null = null;
let activePath: PrefetchPath | null = null;
let lastCompletedPath: PrefetchPath | null = null;
let lastCompletedAt = 0;

function isPrefetchPath(to: string): to is PrefetchPath {
  return to in PREFETCHERS;
}

function clearLinger(): void {
  if (lingerTimer !== null) {
    clearTimeout(lingerTimer);
    lingerTimer = null;
  }
}

function abortActive(): void {
  if (activeController) {
    activeController.abort();
    activeController = null;
  }
  activePath = null;
}

async function runPrefetch(queryClient: QueryClient, path: PrefetchPath): Promise<void> {
  if (path === lastCompletedPath && Date.now() - lastCompletedAt < SAME_ROUTE_COOLDOWN_MS) {
    return;
  }
  if (path === activePath) {
    return;
  }

  abortActive();

  const controller = new AbortController();
  activeController = controller;
  activePath = path;

  try {
    await PREFETCHERS[path](queryClient, controller.signal);
    if (!controller.signal.aborted) {
      lastCompletedPath = path;
      lastCompletedAt = Date.now();
    }
  } catch (error) {
    const aborted =
      controller.signal.aborted ||
      (error instanceof DOMException && error.name === "AbortError") ||
      (error instanceof Error && error.name === "AbortError");
    if (!aborted) {
      console.warn(`[nav-prefetch] ${path} failed`, error);
    }
  } finally {
    if (activeController === controller) {
      activeController = null;
      activePath = null;
    }
  }
}

export function scheduleNavPrefetch(queryClient: QueryClient, to: string): void {
  if (!isPrefetchPath(to)) return;
  pendingPath = to;
  clearLinger();
  lingerTimer = setTimeout(() => {
    lingerTimer = null;
    const path = pendingPath;
    pendingPath = null;
    if (path) void runPrefetch(queryClient, path);
  }, HOVER_LINGER_MS);
}

export function flushNavPrefetch(queryClient: QueryClient, to: string): void {
  if (!isPrefetchPath(to)) return;
  clearLinger();
  pendingPath = null;
  void runPrefetch(queryClient, to);
}

/** Test-only: clear linger/single-flight/cooldown state between cases. */
export function resetNavPrefetchStateForTests(): void {
  clearLinger();
  abortActive();
  pendingPath = null;
  lastCompletedPath = null;
  lastCompletedAt = 0;
}
