import { useQueryClient } from "@tanstack/react-query";
import { createFileRoute, useNavigate } from "@tanstack/react-router";
import { useEffect, useMemo, useRef } from "react";
import { QualityDashboard } from "@/features/quality/QualityDashboard";
import { useProjectsQuery } from "@/lib/queries/delivery";
import { loadQualityRouteData } from "@/lib/queries/quality";

export const Route = createFileRoute("/quality")({
  validateSearch: (search: Record<string, unknown>) => ({
    projectId: typeof search.projectId === "string" ? search.projectId : undefined,
  }),
  // Re-run the loader when only the `projectId` search param changes (e.g.
  // switching projects), not just on a fresh match -- by default a route's
  // loader keys off params, not search, so this opts search in too.
  loaderDeps: ({ search }) => ({ projectId: search.projectId }),
  // Kick off `projects` and (once a projectId is known) `quality-page` in
  // parallel at route-match time -- see loadQualityRouteData for why this
  // removes the cold-load waterfall (PERF_IMPLEMENTATION_PLAN.md Phase 1B).
  //
  // Deliberately NOT returned/awaited: TanStack Router awaits whatever a
  // loader returns before committing the navigation. Returning this promise
  // made every project switch (which re-runs the loader via `loaderDeps`)
  // block the ENTIRE transition on the quality-page fetch (~1-2s) with no
  // visual feedback at all -- confirmed live, the page would sit frozen
  // then instantly swap, and QualityDashboard's own `isFetching`-driven
  // "Updating..." indicator (QualityToolbar.tsx) never got a chance to
  // render, because by the time the component re-rendered with the new
  // project id the router-awaited fetch had already resolved. Firing it
  // without awaiting lets the router commit immediately -- the two
  // requests still start together exactly as before (this call schedules
  // both synchronously) -- so the component mounts/updates while the fetch
  // is still genuinely in flight, and its existing isLoading/isFetching UI
  // (skeleton on cold load, "Updating..." + dimmed content on a switch)
  // actually gets to run.
  loader: ({ context, deps }) => {
    void loadQualityRouteData(context.queryClient, deps.projectId);
  },
  component: QualityPage,
});

function QualityPage() {
  const navigate = useNavigate({ from: "/quality" });
  const { projectId: urlProjectId } = Route.useSearch();
  const syncedProjectIdRef = useRef<string | null>(null);
  const queryClient = useQueryClient();

  // Belt-and-suspenders alongside the route `loader` above: this app's root
  // route gates rendering on a client-only auth bootstrap (AuthProvider),
  // not a router `beforeLoad`/loader, and there is no query-dehydration
  // bridge from the server's request-scoped QueryClient to the client's. On
  // a cold load, TanStack Start's hydration reuses the SSR match without
  // re-invoking the loader against the *client* QueryClient, so the loader
  // alone never overlaps `quality-page` with `projects` there in practice
  // -- confirmed via resource timing while developing this fix. A plain
  // mount effect always runs client-side (hydration or SPA nav alike),
  // guaranteeing the two requests actually start together.
  useEffect(() => {
    void loadQualityRouteData(queryClient, urlProjectId);
  }, [queryClient, urlProjectId]);

  const projectsQuery = useProjectsQuery();
  const projects = projectsQuery.data ?? [];

  const resolvedProjectId = useMemo(() => {
    if (projects.length === 0) return undefined;
    if (urlProjectId && projects.some((project) => project.id === urlProjectId)) {
      return urlProjectId;
    }
    return projects[0]?.id;
  }, [projects, urlProjectId]);

  useEffect(() => {
    if (!resolvedProjectId || resolvedProjectId === urlProjectId) return;
    if (syncedProjectIdRef.current === resolvedProjectId) return;
    syncedProjectIdRef.current = resolvedProjectId;
    navigate({ search: { projectId: resolvedProjectId }, replace: true });
  }, [resolvedProjectId, urlProjectId, navigate]);

  const selectProject = (projectId: string) => {
    navigate({ search: { projectId } });
  };

  return (
    <QualityDashboard
      projects={projects}
      activeProjectId={resolvedProjectId}
      loadingProjects={projectsQuery.isLoading}
      onSelectProject={selectProject}
    />
  );
}
