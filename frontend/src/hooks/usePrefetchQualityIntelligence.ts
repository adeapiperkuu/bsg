import { useEffect } from "react";
import { useQueryClient } from "@tanstack/react-query";

import { canAccessPath } from "@/lib/api";
import { prefetchDefaultQualityPage } from "@/lib/queries/quality";
import { useAuthStore } from "@/stores/useAuthStore";

/**
 * Warms the Quality Intelligence page's data in the background, once the
 * Operational Tower (this hook's caller, `/dashboard`) has already mounted
 * -- never before it and never in a way that could delay its own render
 * (PERF_IMPLEMENTATION_PLAN.md Phase 4). The Operational Tower is the first
 * thing a PM sees after login and must never wait on this.
 *
 * Deliberately NOT a route `loader`: a loader runs before the component
 * renders, which could delay first paint if the dashboard ever gains real
 * data-fetching of its own (it has none today -- see `routes/dashboard.tsx`
 * -- but this hook must stay correct if that changes). A post-mount effect,
 * further deferred to the browser's idle time via `requestIdleCallback`,
 * guarantees the dashboard's own paint/layout work always goes first.
 *
 * No ref-guard for "only run once": relying on one would misbehave under
 * React Strict Mode's dev-only double-invoke (schedule -> cleanup -> guard
 * now permanently blocks the second, surviving invocation from ever
 * scheduling anything). Standard effect cleanup already handles this
 * correctly -- the deps (`user` transitioning null -> the session's user
 * exactly once, per `AuthProvider.tsx`'s own reasoning) mean this rarely
 * re-runs, and on the rare re-run `prefetchDefaultQualityPage`'s underlying
 * `ensureQueryData`/`prefetchQuery` calls are cache-key-deduped and
 * `staleTime`-aware, so an extra call is a harmless no-op -- same posture
 * `loadQualityRouteData` already documents for its own callers.
 */
export function usePrefetchQualityIntelligence(): void {
  const queryClient = useQueryClient();
  const user = useAuthStore((state) => state.user);

  useEffect(() => {
    if (!user || !canAccessPath(user.role, "/quality")) return;

    let cancelled = false;
    const run = () => {
      if (!cancelled) void prefetchDefaultQualityPage(queryClient);
    };

    const win = window as typeof window & {
      requestIdleCallback?: (cb: () => void) => number;
      cancelIdleCallback?: (handle: number) => void;
    };

    if (typeof win.requestIdleCallback === "function") {
      const handle = win.requestIdleCallback(run);
      return () => {
        cancelled = true;
        win.cancelIdleCallback?.(handle);
      };
    }

    const timeout = window.setTimeout(run, 200);
    return () => {
      cancelled = true;
      window.clearTimeout(timeout);
    };
  }, [queryClient, user]);
}
