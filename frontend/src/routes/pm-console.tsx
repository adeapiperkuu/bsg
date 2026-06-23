import { createFileRoute } from "@tanstack/react-router";
import { Card, SectionHeader, StatusPill } from "@/components/bsg/widgets";
import { useProjectsQuery } from "@/lib/queries/delivery";

export const Route = createFileRoute("/pm-console")({ component: PmConsole });

function statusLabel(status: string): string {
  return status.charAt(0).toUpperCase() + status.slice(1);
}

function openDelivery(projectId: string): void {
  window.location.href = `/delivery?projectId=${projectId}`;
}

function PmConsole() {
  const { data: projects = [], isLoading: loading, error } = useProjectsQuery();
  const errorMessage = error instanceof Error ? error.message : null;

  return (
    <div className="grid grid-cols-1 gap-5 lg:grid-cols-3">
      <Card className="lg:col-span-2">
        <SectionHeader title="My Projects" sub="Loaded from backend Projects API" />
        {loading ? (
          <p className="text-sm text-muted-foreground">Loading projects...</p>
        ) : errorMessage ? (
          <p className="text-sm text-[color:var(--danger)]">{errorMessage}</p>
        ) : projects.length === 0 ? (
          <p className="text-sm text-muted-foreground">No projects assigned to this user.</p>
        ) : (
          <ul className="space-y-2 text-xs">
            {projects.map((project) => (
              <li
                key={project.id}
                className="flex items-center justify-between rounded border border-border bg-elevated px-3 py-2"
              >
                <div>
                  <div className="font-medium">{project.name}</div>
                  <div className="text-[10px] text-muted-foreground">
                    {project.vertical} · Target {project.target_end_date}
                  </div>
                </div>
                <div className="flex items-center gap-2">
                  <StatusPill status={statusLabel(project.status)} />
                  <button
                    onClick={() => openDelivery(project.id)}
                    className="rounded border border-border px-2 py-0.5 text-[10px]"
                  >
                    Open
                  </button>
                </div>
              </li>
            ))}
          </ul>
        )}
      </Card>
    </div>
  );
}
