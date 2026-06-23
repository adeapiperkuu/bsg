import { createFileRoute } from "@tanstack/react-router";
import { useEffect, useMemo, useState } from "react";
import { Card, SectionHeader, StatusPill } from "@/components/bsg/widgets";
import {
  createProject,
  listProjects,
  type ProjectCreatePayload,
  type ProjectRead,
  type ProjectStatus,
  updateProject,
} from "@/lib/api";
import { Search } from "lucide-react";

export const Route = createFileRoute("/projects")({ component: ProjectsPage });

const statusOptions: ProjectStatus[] = ["active", "ramping", "paused", "completed", "cancelled"];

function today(): string {
  return new Date().toISOString().slice(0, 10);
}

function nextMonth(): string {
  const date = new Date();
  date.setMonth(date.getMonth() + 1);
  return date.toISOString().slice(0, 10);
}

function statusLabel(status: string): string {
  return status.charAt(0).toUpperCase() + status.slice(1);
}

function ProjectsPage() {
  const [projects, setProjects] = useState<ProjectRead[]>([]);
  const [query, setQuery] = useState("");
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [editingProject, setEditingProject] = useState<ProjectRead | null>(null);
  const [createForm, setCreateForm] = useState<ProjectCreatePayload>({
    name: "",
    description: "",
    vertical: "",
    status: "active",
    start_date: today(),
    target_end_date: nextMonth(),
    daily_target_units: null,
  });

  const filteredProjects = useMemo(() => {
    const normalized = query.trim().toLowerCase();
    if (!normalized) return projects;
    return projects.filter((project) =>
      [project.name, project.description, project.vertical, project.status]
        .filter(Boolean)
        .some((value) => String(value).toLowerCase().includes(normalized)),
    );
  }, [projects, query]);

  const loadProjects = () => {
    setLoading(true);
    setError(null);
    listProjects()
      .then(setProjects)
      .catch((err: unknown) => {
        setError(err instanceof Error ? err.message : "Projects failed to load.");
      })
      .finally(() => setLoading(false));
  };

  useEffect(() => {
    loadProjects();
  }, []);

  const submitCreate = (event: React.FormEvent) => {
    event.preventDefault();
    setSaving(true);
    setError(null);
    createProject({
      ...createForm,
      daily_target_units: createForm.daily_target_units || null,
      description: createForm.description || null,
    })
      .then((project) => {
        setProjects((current) => [project, ...current]);
        setCreateForm({
          name: "",
          description: "",
          vertical: "",
          status: "active",
          start_date: today(),
          target_end_date: nextMonth(),
          daily_target_units: null,
        });
      })
      .catch((err: unknown) => {
        setError(err instanceof Error ? err.message : "Project could not be created.");
      })
      .finally(() => setSaving(false));
  };

  const submitEdit = (event: React.FormEvent) => {
    event.preventDefault();
    if (!editingProject) return;

    setSaving(true);
    setError(null);
    updateProject(editingProject.id, {
      name: editingProject.name,
      description: editingProject.description || null,
      status: editingProject.status,
      target_end_date: editingProject.target_end_date,
      actual_end_date: editingProject.actual_end_date,
      daily_target_units: editingProject.daily_target_units,
    })
      .then((updated) => {
        setProjects((current) =>
          current.map((project) => (project.id === updated.id ? updated : project)),
        );
        setEditingProject(null);
      })
      .catch((err: unknown) => {
        setError(err instanceof Error ? err.message : "Project could not be updated.");
      })
      .finally(() => setSaving(false));
  };

  return (
    <div className="space-y-5">
      <Card>
        <div className="flex flex-wrap items-center gap-2">
          <div className="flex flex-1 items-center gap-2 rounded-md border border-border bg-elevated px-2.5 py-1.5 text-xs">
            <Search className="h-3.5 w-3.5 text-muted-foreground" />
            <input
              value={query}
              onChange={(event) => setQuery(event.target.value)}
              placeholder="Search projects..."
              className="flex-1 bg-transparent outline-none"
            />
          </div>
          <button
            onClick={loadProjects}
            className="rounded border border-border px-3 py-1.5 text-xs hover:bg-elevated"
          >
            Refresh
          </button>
        </div>
      </Card>

      {error && (
        <Card>
          <p className="text-sm text-[color:var(--danger)]">{error}</p>
        </Card>
      )}

      <Card>
        <SectionHeader title="Create Project" sub="Saved through the backend Projects API" />
        <form onSubmit={submitCreate} className="grid gap-3 text-xs md:grid-cols-3">
          <input
            required
            value={createForm.name}
            onChange={(event) => setCreateForm({ ...createForm, name: event.target.value })}
            placeholder="Project name"
            className="rounded border border-border bg-card px-2.5 py-1.5 outline-none"
          />
          <input
            required
            value={createForm.vertical}
            onChange={(event) => setCreateForm({ ...createForm, vertical: event.target.value })}
            placeholder="Vertical"
            className="rounded border border-border bg-card px-2.5 py-1.5 outline-none"
          />
          <select
            value={createForm.status}
            onChange={(event) =>
              setCreateForm({ ...createForm, status: event.target.value as ProjectStatus })
            }
            className="rounded border border-border bg-card px-2.5 py-1.5 outline-none"
          >
            {statusOptions.map((status) => (
              <option key={status} value={status}>
                {statusLabel(status)}
              </option>
            ))}
          </select>
          <input
            required
            type="date"
            value={createForm.start_date}
            onChange={(event) => setCreateForm({ ...createForm, start_date: event.target.value })}
            className="rounded border border-border bg-card px-2.5 py-1.5 outline-none"
          />
          <input
            required
            type="date"
            value={createForm.target_end_date}
            onChange={(event) =>
              setCreateForm({ ...createForm, target_end_date: event.target.value })
            }
            className="rounded border border-border bg-card px-2.5 py-1.5 outline-none"
          />
          <input
            type="number"
            min={0}
            value={createForm.daily_target_units ?? ""}
            onChange={(event) =>
              setCreateForm({
                ...createForm,
                daily_target_units: event.target.value ? Number(event.target.value) : null,
              })
            }
            placeholder="Daily target"
            className="rounded border border-border bg-card px-2.5 py-1.5 outline-none"
          />
          <textarea
            value={createForm.description ?? ""}
            onChange={(event) => setCreateForm({ ...createForm, description: event.target.value })}
            placeholder="Description"
            className="rounded border border-border bg-card px-2.5 py-1.5 outline-none md:col-span-2"
          />
          <button
            disabled={saving}
            className="rounded bg-[color:var(--brand)] px-3 py-1.5 font-medium text-[color:var(--brand-foreground)] disabled:opacity-60"
          >
            {saving ? "Saving..." : "Create"}
          </button>
        </form>
      </Card>

      <Card>
        <SectionHeader title="Projects" sub="Loaded from GET /projects" />
        {loading ? (
          <p className="text-sm text-muted-foreground">Loading projects...</p>
        ) : filteredProjects.length === 0 ? (
          <p className="text-sm text-muted-foreground">No projects found.</p>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-xs">
              <thead className="text-left text-muted-foreground">
                <tr className="border-b border-border">
                  <th className="py-2 pr-3 font-medium">Project</th>
                  <th className="py-2 pr-3 font-medium">Vertical</th>
                  <th className="py-2 pr-3 font-medium">Status</th>
                  <th className="py-2 pr-3 font-medium">Target End</th>
                  <th className="py-2 pr-3 font-medium">Daily Target</th>
                  <th className="py-2 pr-3 font-medium"></th>
                </tr>
              </thead>
              <tbody>
                {filteredProjects.map((project) => (
                  <tr key={project.id} className="border-b border-border/50">
                    <td className="py-2.5 pr-3 font-medium">{project.name}</td>
                    <td className="py-2.5 pr-3">{project.vertical}</td>
                    <td className="py-2.5 pr-3">
                      <StatusPill status={statusLabel(project.status)} />
                    </td>
                    <td className="py-2.5 pr-3">{project.target_end_date}</td>
                    <td className="py-2.5 pr-3">{project.daily_target_units ?? "No data"}</td>
                    <td className="py-2.5 pr-3">
                      <button
                        onClick={() => setEditingProject(project)}
                        className="rounded border border-border px-2 py-0.5 text-[11px] hover:bg-elevated"
                      >
                        Edit
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Card>

      {editingProject && (
        <div
          className="fixed inset-0 z-40 flex justify-end bg-background/60 backdrop-blur-sm"
          onClick={() => setEditingProject(null)}
        >
          <form
            onSubmit={submitEdit}
            className="h-full w-full max-w-xl overflow-y-auto border-l border-border bg-card p-6"
            onClick={(event) => event.stopPropagation()}
          >
            <SectionHeader title="Edit Project" sub={editingProject.id} />
            <div className="space-y-3 text-xs">
              <input
                value={editingProject.name}
                onChange={(event) =>
                  setEditingProject({ ...editingProject, name: event.target.value })
                }
                className="w-full rounded border border-border bg-card px-2.5 py-1.5 outline-none"
              />
              <textarea
                value={editingProject.description ?? ""}
                onChange={(event) =>
                  setEditingProject({ ...editingProject, description: event.target.value })
                }
                className="w-full rounded border border-border bg-card px-2.5 py-1.5 outline-none"
              />
              <select
                value={editingProject.status}
                onChange={(event) =>
                  setEditingProject({
                    ...editingProject,
                    status: event.target.value as ProjectStatus,
                  })
                }
                className="w-full rounded border border-border bg-card px-2.5 py-1.5 outline-none"
              >
                {statusOptions.map((status) => (
                  <option key={status} value={status}>
                    {statusLabel(status)}
                  </option>
                ))}
              </select>
              <input
                type="date"
                value={editingProject.target_end_date}
                onChange={(event) =>
                  setEditingProject({ ...editingProject, target_end_date: event.target.value })
                }
                className="w-full rounded border border-border bg-card px-2.5 py-1.5 outline-none"
              />
              <input
                type="date"
                value={editingProject.actual_end_date ?? ""}
                onChange={(event) =>
                  setEditingProject({
                    ...editingProject,
                    actual_end_date: event.target.value || null,
                  })
                }
                className="w-full rounded border border-border bg-card px-2.5 py-1.5 outline-none"
              />
              <input
                type="number"
                min={0}
                value={editingProject.daily_target_units ?? ""}
                onChange={(event) =>
                  setEditingProject({
                    ...editingProject,
                    daily_target_units: event.target.value ? Number(event.target.value) : null,
                  })
                }
                className="w-full rounded border border-border bg-card px-2.5 py-1.5 outline-none"
              />
              <div className="flex justify-end gap-2">
                <button
                  type="button"
                  onClick={() => setEditingProject(null)}
                  className="rounded border border-border px-3 py-1.5"
                >
                  Cancel
                </button>
                <button
                  disabled={saving}
                  className="rounded bg-[color:var(--brand)] px-3 py-1.5 font-medium text-[color:var(--brand-foreground)] disabled:opacity-60"
                >
                  {saving ? "Saving..." : "Save"}
                </button>
              </div>
            </div>
          </form>
        </div>
      )}
    </div>
  );
}
