import { createFileRoute, Link } from "@tanstack/react-router";
import { useQueryClient } from "@tanstack/react-query";
import { useEffect, useMemo, useRef, useState } from "react";
import { Card, SectionHeader, StatusPill } from "@/components/bsg/widgets";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  createProject,
  type ProjectCreatePayload,
  type ProjectRead,
  type ProjectStatus,
  updateProject,
} from "@/lib/api";
import { projectsQueryOptions, useProjectsQuery } from "@/lib/queries/delivery";
import { cn } from "@/lib/utils";
import { Search, X } from "lucide-react";

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

function emptyCreateForm(): ProjectCreatePayload {
  return {
    name: "",
    description: "",
    vertical: "",
    status: "active",
    start_date: today(),
    target_end_date: nextMonth(),
    daily_target_units: null,
  };
}

const fieldClass =
  "h-10 w-full rounded-sm border border-input bg-background px-3 text-sm shadow-none outline-none focus-visible:ring-1 focus-visible:ring-ring";

function ProjectsPage() {
  const queryClient = useQueryClient();
  const projectsQuery = useProjectsQuery();
  const projects = projectsQuery.data ?? [];
  const loading = projectsQuery.isLoading;
  const [query, setQuery] = useState("");
  const [isSearchOpen, setIsSearchOpen] = useState(false);
  const searchInputRef = useRef<HTMLInputElement>(null);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [editingProject, setEditingProject] = useState<ProjectRead | null>(null);
  const [isCreateOpen, setIsCreateOpen] = useState(false);
  const [createForm, setCreateForm] = useState<ProjectCreatePayload>(emptyCreateForm);

  const filteredProjects = useMemo(() => {
    const normalized = query.trim().toLowerCase();
    if (!normalized) return projects;
    return projects.filter((project) =>
      [project.name, project.description, project.vertical, project.status]
        .filter(Boolean)
        .some((value) => String(value).toLowerCase().includes(normalized)),
    );
  }, [projects, query]);

  useEffect(() => {
    if (!isSearchOpen) return;
    const frame = requestAnimationFrame(() => searchInputRef.current?.focus());
    return () => cancelAnimationFrame(frame);
  }, [isSearchOpen]);

  useEffect(() => {
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape" && isSearchOpen) {
        setIsSearchOpen(false);
        searchInputRef.current?.blur();
      }
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [isSearchOpen]);

  const openSearch = () => setIsSearchOpen(true);

  const closeSearch = () => setIsSearchOpen(false);

  const clearSearch = () => {
    setQuery("");
    closeSearch();
  };

  const refreshProjects = () => {
    void queryClient.invalidateQueries({ queryKey: projectsQueryOptions.queryKey });
  };

  const closeCreateDialog = () => {
    setIsCreateOpen(false);
    setCreateForm(emptyCreateForm());
    setError(null);
  };

  const submitCreate = (event: React.FormEvent) => {
    event.preventDefault();
    setSaving(true);
    setError(null);
    createProject({
      ...createForm,
      daily_target_units: createForm.daily_target_units || null,
      description: createForm.description || null,
    })
      .then(() => {
        refreshProjects();
        closeCreateDialog();
      })
      .catch((err: unknown) => {
        setError(err instanceof Error ? err.message : "Project could not be created.");
      })
      .finally(() => setSaving(false));
  };

  const closeEditDialog = () => {
    setEditingProject(null);
    setError(null);
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
      .then(() => {
        refreshProjects();
        closeEditDialog();
      })
      .catch((err: unknown) => {
        setError(err instanceof Error ? err.message : "Project could not be updated.");
      })
      .finally(() => setSaving(false));
  };

  return (
    <div className="space-y-5">
      <div className="flex items-center justify-end gap-2">
        <div
          className={cn(
            "flex h-[30px] items-center overflow-hidden border transition-[width,max-width,padding,box-shadow,border-color,background-color,border-radius] duration-300 ease-out",
            isSearchOpen
              ? "w-56 rounded-full border-transparent bg-secondary/50 px-3 sm:w-64"
              : "w-[30px] rounded-sm border-[color:var(--brand)] bg-[color:var(--brand)] hover:bg-[color:var(--brand)]/90",
          )}
        >
          <button
            type="button"
            aria-label="Search projects"
            onClick={() => (isSearchOpen ? searchInputRef.current?.focus() : openSearch())}
            className="flex h-[30px] w-7 shrink-0 items-center justify-center"
          >
            <Search
              className={cn(
                "h-3.5 w-3.5 transition-colors duration-200",
                isSearchOpen ? "text-muted-foreground" : "text-[color:var(--brand-foreground)]",
              )}
            />
          </button>
          <input
            ref={searchInputRef}
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            onBlur={() => {
              if (!query.trim()) closeSearch();
            }}
            placeholder="Search projects..."
            className={cn(
              "min-w-0 flex-1 bg-transparent text-xs text-foreground outline-none transition-all duration-300 ease-out placeholder:text-muted-foreground/80",
              isSearchOpen ? "w-full translate-x-0 opacity-100" : "pointer-events-none w-0 -translate-x-1 opacity-0",
            )}
            tabIndex={isSearchOpen ? 0 : -1}
          />
          <button
            type="button"
            aria-label="Clear search"
            onMouseDown={(event) => event.preventDefault()}
            onClick={clearSearch}
            className={cn(
              "flex h-5 w-5 shrink-0 items-center justify-center rounded-full text-muted-foreground/70 transition-all duration-200 hover:bg-secondary hover:text-muted-foreground",
              isSearchOpen ? "scale-100 opacity-100" : "pointer-events-none scale-75 opacity-0",
            )}
          >
            <X className="h-3 w-3" />
          </button>
        </div>
        <Button
          type="button"
          size="sm"
          className="h-[30px] rounded-sm bg-[color:var(--brand)] px-3 text-xs text-[color:var(--brand-foreground)] shadow-none hover:bg-[color:var(--brand)]/90"
          onClick={() => setIsCreateOpen(true)}
        >
          Create
        </Button>
      </div>

      {error && !isCreateOpen && !editingProject && (
        <Card>
          <p className="text-sm text-[color:var(--danger)]">{error}</p>
        </Card>
      )}

      <Dialog
        open={isCreateOpen}
        onOpenChange={(open) => {
          if (!open) closeCreateDialog();
          else setIsCreateOpen(true);
        }}
      >
        <DialogContent className="max-w-lg gap-0 overflow-hidden p-0 sm:max-w-xl">
          <DialogHeader className="border-b border-border bg-elevated/60 px-4 py-4 sm:px-6">
            <DialogTitle>Create Project</DialogTitle>
            <DialogDescription>Saved through the backend Projects API.</DialogDescription>
          </DialogHeader>
          <form onSubmit={submitCreate}>
            <div className="max-h-[calc(100svh-14rem)] space-y-4 overflow-y-auto px-4 py-4 sm:max-h-[70vh] sm:px-6">
              {error && <p className="text-sm text-[color:var(--danger)]">{error}</p>}
              <div className="grid gap-4 sm:grid-cols-2">
                <div className="space-y-1.5 sm:col-span-2">
                  <Label htmlFor="project-name">Project name</Label>
                  <Input
                    id="project-name"
                    required
                    value={createForm.name}
                    onChange={(event) => setCreateForm({ ...createForm, name: event.target.value })}
                    placeholder="Project name"
                    className="h-10 shadow-none"
                  />
                </div>
                <div className="space-y-1.5">
                  <Label htmlFor="project-vertical">Vertical</Label>
                  <Input
                    id="project-vertical"
                    required
                    value={createForm.vertical}
                    onChange={(event) => setCreateForm({ ...createForm, vertical: event.target.value })}
                    placeholder="Vertical"
                    className="h-10 shadow-none"
                  />
                </div>
                <div className="space-y-1.5">
                  <Label htmlFor="project-status">Status</Label>
                  <select
                    id="project-status"
                    value={createForm.status}
                    onChange={(event) =>
                      setCreateForm({ ...createForm, status: event.target.value as ProjectStatus })
                    }
                    className={fieldClass}
                  >
                    {statusOptions.map((status) => (
                      <option key={status} value={status}>
                        {statusLabel(status)}
                      </option>
                    ))}
                  </select>
                </div>
                <div className="space-y-1.5">
                  <Label htmlFor="project-start-date">Start date</Label>
                  <Input
                    id="project-start-date"
                    required
                    type="date"
                    value={createForm.start_date}
                    onChange={(event) => setCreateForm({ ...createForm, start_date: event.target.value })}
                    className="h-10 shadow-none"
                  />
                </div>
                <div className="space-y-1.5">
                  <Label htmlFor="project-target-end-date">Target end date</Label>
                  <Input
                    id="project-target-end-date"
                    required
                    type="date"
                    value={createForm.target_end_date}
                    onChange={(event) =>
                      setCreateForm({ ...createForm, target_end_date: event.target.value })
                    }
                    className="h-10 shadow-none"
                  />
                </div>
                <div className="space-y-1.5 sm:col-span-2">
                  <Label htmlFor="project-daily-target">Daily target</Label>
                  <Input
                    id="project-daily-target"
                    type="number"
                    min={0}
                    value={createForm.daily_target_units ?? ""}
                    onChange={(event) =>
                      setCreateForm({
                        ...createForm,
                        daily_target_units: event.target.value ? Number(event.target.value) : null,
                      })
                    }
                    placeholder="Daily target units"
                    className="h-10 shadow-none"
                  />
                </div>
                <div className="space-y-1.5 sm:col-span-2">
                  <Label htmlFor="project-description">Description</Label>
                  <textarea
                    id="project-description"
                    value={createForm.description ?? ""}
                    onChange={(event) => setCreateForm({ ...createForm, description: event.target.value })}
                    placeholder="Description"
                    rows={3}
                    className="w-full resize-none rounded-sm border border-input bg-background px-3 py-2 text-sm shadow-none outline-none focus-visible:ring-1 focus-visible:ring-ring"
                  />
                </div>
              </div>
            </div>
            <DialogFooter className="gap-2 border-t border-border bg-elevated/60 px-4 py-4 sm:justify-end sm:space-x-0 sm:px-6">
              <Button type="button" variant="outline" className="shadow-none" onClick={closeCreateDialog}>
                Cancel
              </Button>
              <Button
                type="submit"
                disabled={saving}
                className="bg-[color:var(--brand)] text-[color:var(--brand-foreground)] shadow-none"
              >
                {saving ? "Creating..." : "Create"}
              </Button>
            </DialogFooter>
          </form>
        </DialogContent>
      </Dialog>

      <Card className="rounded-md">
        <SectionHeader title="Projects" />
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
                      <div className="flex items-center gap-2">
                        <Link
                          to="/delivery"
                          search={{ projectId: project.id }}
                          className="rounded-sm border border-border px-3 py-1 text-xs font-medium hover:bg-elevated"
                        >
                          Open
                        </Link>
                        <button
                          type="button"
                          onClick={() => setEditingProject({ ...project })}
                          className="rounded-sm bg-[color:var(--brand)] px-3 py-1 text-xs font-medium text-[color:var(--brand-foreground)] hover:bg-[color:var(--brand)]/90"
                        >
                          Edit
                        </button>
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Card>

      <Dialog
        open={Boolean(editingProject)}
        onOpenChange={(open) => {
          if (!open) closeEditDialog();
        }}
      >
        <DialogContent className="max-w-lg gap-0 overflow-hidden p-0 sm:max-w-xl">
          <DialogHeader className="border-b border-border bg-elevated/60 px-4 py-4 sm:px-6">
            <DialogTitle>Edit Project</DialogTitle>
            <DialogDescription>
              {editingProject ? `Update details for ${editingProject.name}.` : "Update project details."}
            </DialogDescription>
          </DialogHeader>
          {editingProject && (
            <form onSubmit={submitEdit}>
              <div className="max-h-[calc(100svh-14rem)] space-y-4 overflow-y-auto px-4 py-4 sm:max-h-[70vh] sm:px-6">
                {error && <p className="text-sm text-[color:var(--danger)]">{error}</p>}
                <div className="grid gap-4 sm:grid-cols-2">
                  <div className="space-y-1.5 sm:col-span-2">
                    <Label htmlFor="edit-project-name">Project name</Label>
                    <Input
                      id="edit-project-name"
                      required
                      value={editingProject.name}
                      onChange={(event) =>
                        setEditingProject({ ...editingProject, name: event.target.value })
                      }
                      className="h-10 shadow-none"
                    />
                  </div>
                  <div className="space-y-1.5">
                    <Label htmlFor="edit-project-vertical">Vertical</Label>
                    <Input
                      id="edit-project-vertical"
                      value={editingProject.vertical}
                      disabled
                      className="h-10 shadow-none"
                    />
                  </div>
                  <div className="space-y-1.5">
                    <Label htmlFor="edit-project-status">Status</Label>
                    <select
                      id="edit-project-status"
                      value={editingProject.status}
                      onChange={(event) =>
                        setEditingProject({
                          ...editingProject,
                          status: event.target.value as ProjectStatus,
                        })
                      }
                      className={fieldClass}
                    >
                      {statusOptions.map((status) => (
                        <option key={status} value={status}>
                          {statusLabel(status)}
                        </option>
                      ))}
                    </select>
                  </div>
                  <div className="space-y-1.5">
                    <Label htmlFor="edit-project-start-date">Start date</Label>
                    <Input
                      id="edit-project-start-date"
                      type="date"
                      value={editingProject.start_date}
                      disabled
                      className="h-10 shadow-none"
                    />
                  </div>
                  <div className="space-y-1.5">
                    <Label htmlFor="edit-project-target-end-date">Target end date</Label>
                    <Input
                      id="edit-project-target-end-date"
                      required
                      type="date"
                      value={editingProject.target_end_date}
                      onChange={(event) =>
                        setEditingProject({ ...editingProject, target_end_date: event.target.value })
                      }
                      className="h-10 shadow-none"
                    />
                  </div>
                  <div className="space-y-1.5">
                    <Label htmlFor="edit-project-actual-end-date">Actual end date</Label>
                    <Input
                      id="edit-project-actual-end-date"
                      type="date"
                      value={editingProject.actual_end_date ?? ""}
                      onChange={(event) =>
                        setEditingProject({
                          ...editingProject,
                          actual_end_date: event.target.value || null,
                        })
                      }
                      className="h-10 shadow-none"
                    />
                  </div>
                  <div className="space-y-1.5">
                    <Label htmlFor="edit-project-daily-target">Daily target</Label>
                    <Input
                      id="edit-project-daily-target"
                      type="number"
                      min={0}
                      value={editingProject.daily_target_units ?? ""}
                      onChange={(event) =>
                        setEditingProject({
                          ...editingProject,
                          daily_target_units: event.target.value ? Number(event.target.value) : null,
                        })
                      }
                      placeholder="Daily target units"
                      className="h-10 shadow-none"
                    />
                  </div>
                  <div className="space-y-1.5 sm:col-span-2">
                    <Label htmlFor="edit-project-description">Description</Label>
                    <textarea
                      id="edit-project-description"
                      value={editingProject.description ?? ""}
                      onChange={(event) =>
                        setEditingProject({ ...editingProject, description: event.target.value })
                      }
                      placeholder="Description"
                      rows={3}
                      className="w-full resize-none rounded-sm border border-input bg-background px-3 py-2 text-sm shadow-none outline-none focus-visible:ring-1 focus-visible:ring-ring"
                    />
                  </div>
                </div>
              </div>
              <DialogFooter className="gap-2 border-t border-border bg-elevated/60 px-4 py-4 sm:justify-end sm:space-x-0 sm:px-6">
                <Button type="button" variant="outline" className="shadow-none" onClick={closeEditDialog}>
                  Cancel
                </Button>
                <Button
                  type="submit"
                  disabled={saving}
                  className="bg-[color:var(--brand)] text-[color:var(--brand-foreground)] shadow-none"
                >
                  {saving ? "Saving..." : "Save"}
                </Button>
              </DialogFooter>
            </form>
          )}
        </DialogContent>
      </Dialog>
    </div>
  );
}
