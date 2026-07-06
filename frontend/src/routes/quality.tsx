import { createFileRoute, useNavigate } from "@tanstack/react-router";
import { useEffect, useMemo, useRef } from "react";
import { QualityDashboard } from "@/features/quality/QualityDashboard";
import { useProjectsQuery } from "@/lib/queries/delivery";

export const Route = createFileRoute("/quality")({
  validateSearch: (search: Record<string, unknown>) => ({
    projectId: typeof search.projectId === "string" ? search.projectId : undefined,
  }),
  component: QualityPage,
});

function QualityPage() {
  const navigate = useNavigate({ from: "/quality" });
  const { projectId: urlProjectId } = Route.useSearch();
  const syncedProjectIdRef = useRef<string | null>(null);

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
