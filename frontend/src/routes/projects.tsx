import { createFileRoute, Link } from "@tanstack/react-router";
import { useQueryClient } from "@tanstack/react-query";
import { useEffect, useMemo, useRef, useState } from "react";
import { Card, SectionHeader, StatusPill } from "@/components/bsg/widgets";
import { PageLoadingScreen } from "@/components/bsg/PageLoadingScreen";
import { ScopeTeamSheet } from "@/components/bsg/workforce-management/ScopeTeamSheet";
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
  createProgram,
  createProject,
  type ProgramRead,
  type ProjectCreatePayload,
  type ProjectRead,
  type ProjectStatus,
  updateProject,
} from "@/lib/api";
import {
  programsQueryOptions,
  projectsQueryOptions,
  useProgramsQuery,
  useProjectsQuery,
} from "@/lib/queries/delivery";
import { canManageWorkforce, canReadInternalWorkforce } from "@/lib/workforcePermissions";
import { useAuthStore } from "@/stores/useAuthStore";
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

function emptyScopeForm(programId: string): ProjectCreatePayload {
  return {
    name: "",
    description: "",
    vertical: "",
    status: "active",
    start_date: today(),
    target_end_date: nextMonth(),
    daily_target_units: null,
    program_id: programId || null,
  };
}

const fieldClass =
  "h-10 w-full rounded-sm border border-input bg-background px-3 text-sm shadow-none outline-none focus-visible:ring-1 focus-visible:ring-ring";

function ProjectsPage() {
  const queryClient = useQueryClient();
  const userRole = useAuthStore((state) => state.user?.role);
  const canReadTeam = canReadInternalWorkforce(userRole);
  const canManageTeam = canManageWorkforce(userRole);
  const programsQuery = useProgramsQuery();
  const projectsQuery = useProjectsQuery();
  const programs = useMemo(() => programsQuery.data ?? [], [programsQuery.data]);
  const scopes = useMemo(() => projectsQuery.data ?? [], [projectsQuery.data]);
  const loading = programsQuery.isLoading || projectsQuery.isLoading;

  const [query, setQuery] = useState("");
  const [isSearchOpen, setIsSearchOpen] = useState(false);
  const searchInputRef = useRef<HTMLInputElement>(null);
  const [selectedProgramId, setSelectedProgramId] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const [isCreateProgramOpen, setIsCreateProgramOpen] = useState(false);
  const [programName, setProgramName] = useState("");
  const [programDescription, setProgramDescription] = useState("");

  const [isCreateScopeOpen, setIsCreateScopeOpen] = useState(false);
  const [createForm, setCreateForm] = useState<ProjectCreatePayload>(emptyScopeForm(""));
  const [editingScope, setEditingScope] = useState<ProjectRead | null>(null);
  const [teamScope, setTeamScope] = useState<ProjectRead | null>(null);

  useEffect(() => {
    if (loading || programs.length === 0) return;
    if (selectedProgramId && programs.some((p) => p.id === selectedProgramId)) return;
    setSelectedProgramId(programs[0]?.id ?? null);
  }, [loading, programs, selectedProgramId]);

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

  const selectedProgram: ProgramRead | null =
    programs.find((p) => p.id === selectedProgramId) ?? null;

  const scopesForProgram = useMemo(() => {
    if (!selectedProgramId) return [];
    return scopes.filter((s) => s.program_id === selectedProgramId);
  }, [scopes, selectedProgramId]);

  const filteredScopes = useMemo(() => {
    const normalized = query.trim().toLowerCase();
    if (!normalized) return scopesForProgram;
    return scopesForProgram.filter((scope) =>
      [scope.name, scope.description, scope.vertical, scope.status]
        .filter(Boolean)
        .some((value) => String(value).toLowerCase().includes(normalized)),
    );
  }, [scopesForProgram, query]);

  const openSearch = () => setIsSearchOpen(true);
  const closeSearch = () => setIsSearchOpen(false);
  const clearSearch = () => {
    setQuery("");
    closeSearch();
  };

  const refresh = () => {
    void queryClient.invalidateQueries({ queryKey: programsQueryOptions.queryKey });
    void queryClient.invalidateQueries({ queryKey: projectsQueryOptions.queryKey });
  };

  const closeCreateProgram = () => {
    setIsCreateProgramOpen(false);
    setProgramName("");
    setProgramDescription("");
    setError(null);
  };

  const submitCreateProgram = (event: React.FormEvent) => {
    event.preventDefault();
    setSaving(true);
    setError(null);
    createProgram({
      name: programName.trim(),
      description: programDescription.trim() || null,
    })
      .then((created) => {
        refresh();
        setSelectedProgramId(created.id);
        closeCreateProgram();
      })
      .catch((err: unknown) => {
        setError(err instanceof Error ? err.message : "Project could not be created.");
      })
      .finally(() => setSaving(false));
  };

  const openCreateScope = () => {
    if (!selectedProgramId) {
      setError("Create or select a project tab before adding a scope.");
      return;
    }
    setCreateForm(emptyScopeForm(selectedProgramId));
    setIsCreateScopeOpen(true);
    setError(null);
  };

  const closeCreateScope = () => {
    setIsCreateScopeOpen(false);
    setCreateForm(emptyScopeForm(selectedProgramId ?? ""));
    setError(null);
  };

  const submitCreateScope = (event: React.FormEvent) => {
    event.preventDefault();
    if (!selectedProgramId) return;
    setSaving(true);
    setError(null);
    createProject({
      ...createForm,
      program_id: selectedProgramId,
      daily_target_units: createForm.daily_target_units || null,
      description: createForm.description || null,
    })
      .then(() => {
        refresh();
        closeCreateScope();
      })
      .catch((err: unknown) => {
        setError(err instanceof Error ? err.message : "Scope could not be created.");
      })
      .finally(() => setSaving(false));
  };

  const closeEditDialog = () => {
    setEditingScope(null);
    setError(null);
  };

  const submitEdit = (event: React.FormEvent) => {
    event.preventDefault();
    if (!editingScope) return;
    setSaving(true);
    setError(null);
    updateProject(editingScope.id, {
      name: editingScope.name,
      description: editingScope.description || null,
      status: editingScope.status,
      target_end_date: editingScope.target_end_date,
      actual_end_date: editingScope.actual_end_date,
      daily_target_units: editingScope.daily_target_units,
      program_id: editingScope.program_id,
    })
      .then(() => {
        refresh();
        closeEditDialog();
      })
      .catch((err: unknown) => {
        setError(err instanceof Error ? err.message : "Scope could not be updated.");
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
            aria-label="Search scopes"
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
            placeholder="Search scopes..."
            className={cn(
              "min-w-0 flex-1 bg-transparent text-xs text-foreground outline-none transition-all duration-300 ease-out placeholder:text-muted-foreground/80",
              isSearchOpen
                ? "w-full translate-x-0 opacity-100"
                : "pointer-events-none w-0 -translate-x-1 opacity-0",
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
        {programs.length > 0 && (
          <select
            aria-label="Project"
            value={selectedProgramId ?? ""}
            onChange={(event) => setSelectedProgramId(event.target.value || null)}
            className="h-[30px] min-w-64 max-w-md rounded-sm border border-input bg-background px-2 text-xs shadow-none outline-none focus-visible:ring-1 focus-visible:ring-ring"
          >
            {programs.map((program) => (
              <option key={program.id} value={program.id}>
                {program.name} ({program.scope_count})
              </option>
            ))}
          </select>
        )}
        <Button
          type="button"
          size="sm"
          variant="outline"
          className="h-[30px] rounded-sm px-3 text-xs shadow-none"
          onClick={() => {
            setIsCreateProgramOpen(true);
            setError(null);
          }}
        >
          New project
        </Button>
      </div>

      {error && !isCreateProgramOpen && !isCreateScopeOpen && !editingScope && !loading && (
        <Card>
          <p className="text-sm text-[color:var(--danger)]">{error}</p>
        </Card>
      )}

      {loading ? (
        <PageLoadingScreen />
      ) : (
        <Card className="rounded-md">
          <SectionHeader
            title="Projects"
            sub={
              selectedProgram
                ? `Scopes in ${selectedProgram.name}`
                : "Select a project to view scopes"
            }
            right={
              selectedProgramId ? (
                <Button
                  type="button"
                  size="sm"
                  className="h-[30px] shrink-0 rounded-sm bg-[color:var(--brand)] px-3 text-xs text-[color:var(--brand-foreground)] shadow-none hover:bg-[color:var(--brand)]/90"
                  onClick={openCreateScope}
                >
                  Add scope
                </Button>
              ) : undefined
            }
          />

          {programs.length === 0 ? (
            <div className="space-y-3">
              <p className="text-sm text-muted-foreground">
                No projects yet. Create a project tab, then add scopes under it.
              </p>
              <Button
                type="button"
                size="sm"
                className="bg-[color:var(--brand)] text-[color:var(--brand-foreground)] shadow-none"
                onClick={() => setIsCreateProgramOpen(true)}
              >
                New project
              </Button>
            </div>
          ) : (
            <>
              {filteredScopes.length === 0 ? (
                <p className="text-sm text-muted-foreground">
                  {query.trim()
                    ? "No scopes found."
                    : "No scopes in this project yet. Click Add scope to create one."}
                </p>
              ) : (
                <div className="overflow-x-auto">
                  <table className="w-full text-xs">
                    <thead className="text-left text-muted-foreground">
                      <tr className="border-b border-border">
                        <th className="py-2 pr-3 font-medium">Scope</th>
                        <th className="py-2 pr-3 font-medium">Vertical</th>
                        <th className="py-2 pr-3 font-medium">Status</th>
                        <th className="py-2 pr-3 font-medium">Target End</th>
                        <th className="py-2 pr-3 font-medium">Daily Target</th>
                        <th className="py-2 pr-3 font-medium"></th>
                      </tr>
                    </thead>
                    <tbody>
                      {filteredScopes.map((scope) => (
                        <tr key={scope.id} className="border-b border-border/50">
                          <td className="py-2.5 pr-3 font-medium">{scope.name}</td>
                          <td className="py-2.5 pr-3">{scope.vertical}</td>
                          <td className="py-2.5 pr-3">
                            <StatusPill status={statusLabel(scope.status)} />
                          </td>
                          <td className="py-2.5 pr-3">{scope.target_end_date}</td>
                          <td className="py-2.5 pr-3">{scope.daily_target_units ?? "No data"}</td>
                          <td className="py-2.5 pr-3">
                            <div className="flex items-center gap-2">
                              <Link
                                to="/delivery"
                                search={{ projectId: scope.id }}
                                className="rounded-sm border border-border px-3 py-1 text-xs font-medium hover:bg-elevated"
                              >
                                Open
                              </Link>
                              {canReadTeam && (
                                <button
                                  type="button"
                                  onClick={() => setTeamScope(scope)}
                                  className="rounded-sm border border-border px-3 py-1 text-xs font-medium hover:bg-elevated"
                                >
                                  Team
                                </button>
                              )}
                              <button
                                type="button"
                                onClick={() => setEditingScope({ ...scope })}
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
            </>
          )}
        </Card>
      )}

      <ScopeTeamSheet
        open={Boolean(teamScope)}
        onOpenChange={(open) => {
          if (!open) setTeamScope(null);
        }}
        projectId={teamScope?.id ?? null}
        scopeName={teamScope?.name ?? null}
        canManage={canManageTeam}
        canRead={canReadTeam}
      />

      <Dialog
        open={isCreateProgramOpen}
        onOpenChange={(open) => {
          if (!open) closeCreateProgram();
          else setIsCreateProgramOpen(true);
        }}
      >
        <DialogContent className="max-w-lg gap-0 overflow-hidden p-0 sm:max-w-xl">
          <DialogHeader className="border-b border-border bg-elevated/60 px-4 py-4 sm:px-6">
            <DialogTitle>New Project</DialogTitle>
            <DialogDescription>
              Create a project tab (e.g. Annotation). Then add scopes under it.
            </DialogDescription>
          </DialogHeader>
          <form onSubmit={submitCreateProgram}>
            <div className="max-h-[calc(100svh-14rem)] space-y-4 overflow-y-auto px-4 py-4 sm:max-h-[70vh] sm:px-6">
              {error && <p className="text-sm text-[color:var(--danger)]">{error}</p>}
              <div className="space-y-1.5">
                <Label htmlFor="program-name">Project name</Label>
                <Input
                  id="program-name"
                  required
                  value={programName}
                  onChange={(event) => setProgramName(event.target.value)}
                  placeholder="Annotation"
                  className="h-10 shadow-none"
                />
              </div>
              <div className="space-y-1.5">
                <Label htmlFor="program-description">Description</Label>
                <textarea
                  id="program-description"
                  value={programDescription}
                  onChange={(event) => setProgramDescription(event.target.value)}
                  placeholder="Optional description"
                  rows={3}
                  className="w-full resize-none rounded-sm border border-input bg-background px-3 py-2 text-sm shadow-none outline-none focus-visible:ring-1 focus-visible:ring-ring"
                />
              </div>
            </div>
            <DialogFooter className="gap-2 border-t border-border bg-elevated/60 px-4 py-4 sm:justify-end sm:space-x-0 sm:px-6">
              <Button
                type="button"
                variant="outline"
                className="shadow-none"
                onClick={closeCreateProgram}
              >
                Cancel
              </Button>
              <Button
                type="submit"
                disabled={saving || !programName.trim()}
                className="bg-[color:var(--brand)] text-[color:var(--brand-foreground)] shadow-none"
              >
                {saving ? "Creating..." : "Create"}
              </Button>
            </DialogFooter>
          </form>
        </DialogContent>
      </Dialog>

      <Dialog
        open={isCreateScopeOpen}
        onOpenChange={(open) => {
          if (!open) closeCreateScope();
          else setIsCreateScopeOpen(true);
        }}
      >
        <DialogContent className="max-w-lg gap-0 overflow-hidden p-0 sm:max-w-xl">
          <DialogHeader className="border-b border-border bg-elevated/60 px-4 py-4 sm:px-6">
            <DialogTitle>Create Scope</DialogTitle>
            <DialogDescription>
              {selectedProgram
                ? `Add a scope under ${selectedProgram.name}. Used for client reports.`
                : "Saved through the backend Projects API."}
            </DialogDescription>
          </DialogHeader>
          <form onSubmit={submitCreateScope}>
            <div className="max-h-[calc(100svh-14rem)] space-y-4 overflow-y-auto px-4 py-4 sm:max-h-[70vh] sm:px-6">
              {error && <p className="text-sm text-[color:var(--danger)]">{error}</p>}
              <div className="grid gap-4 sm:grid-cols-2">
                <div className="space-y-1.5 sm:col-span-2">
                  <Label htmlFor="scope-name">Scope name</Label>
                  <Input
                    id="scope-name"
                    required
                    value={createForm.name}
                    onChange={(event) => setCreateForm({ ...createForm, name: event.target.value })}
                    placeholder="Sprint 27"
                    className="h-10 shadow-none"
                  />
                </div>
                <div className="space-y-1.5">
                  <Label htmlFor="scope-vertical">Vertical</Label>
                  <Input
                    id="scope-vertical"
                    required
                    value={createForm.vertical}
                    onChange={(event) =>
                      setCreateForm({ ...createForm, vertical: event.target.value })
                    }
                    placeholder="Vertical"
                    className="h-10 shadow-none"
                  />
                </div>
                <div className="space-y-1.5">
                  <Label htmlFor="scope-status">Status</Label>
                  <select
                    id="scope-status"
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
                  <Label htmlFor="scope-start-date">Start date</Label>
                  <Input
                    id="scope-start-date"
                    required
                    type="date"
                    value={createForm.start_date}
                    onChange={(event) =>
                      setCreateForm({ ...createForm, start_date: event.target.value })
                    }
                    className="h-10 shadow-none"
                  />
                </div>
                <div className="space-y-1.5">
                  <Label htmlFor="scope-target-end-date">Target end date</Label>
                  <Input
                    id="scope-target-end-date"
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
                  <Label htmlFor="scope-daily-target">Daily target</Label>
                  <Input
                    id="scope-daily-target"
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
                  <Label htmlFor="scope-description">Description</Label>
                  <textarea
                    id="scope-description"
                    value={createForm.description ?? ""}
                    onChange={(event) =>
                      setCreateForm({ ...createForm, description: event.target.value })
                    }
                    placeholder="Description"
                    rows={3}
                    className="w-full resize-none rounded-sm border border-input bg-background px-3 py-2 text-sm shadow-none outline-none focus-visible:ring-1 focus-visible:ring-ring"
                  />
                </div>
              </div>
            </div>
            <DialogFooter className="gap-2 border-t border-border bg-elevated/60 px-4 py-4 sm:justify-end sm:space-x-0 sm:px-6">
              <Button
                type="button"
                variant="outline"
                className="shadow-none"
                onClick={closeCreateScope}
              >
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

      <Dialog
        open={Boolean(editingScope)}
        onOpenChange={(open) => {
          if (!open) closeEditDialog();
        }}
      >
        <DialogContent className="max-w-lg gap-0 overflow-hidden p-0 sm:max-w-xl">
          <DialogHeader className="border-b border-border bg-elevated/60 px-4 py-4 sm:px-6">
            <DialogTitle>Edit Scope</DialogTitle>
            <DialogDescription>
              {editingScope
                ? `Update details for ${editingScope.name}.`
                : "Update scope details."}
            </DialogDescription>
          </DialogHeader>
          {editingScope && (
            <form onSubmit={submitEdit}>
              <div className="max-h-[calc(100svh-14rem)] space-y-4 overflow-y-auto px-4 py-4 sm:max-h-[70vh] sm:px-6">
                {error && <p className="text-sm text-[color:var(--danger)]">{error}</p>}
                <div className="grid gap-4 sm:grid-cols-2">
                  <div className="space-y-1.5 sm:col-span-2">
                    <Label htmlFor="edit-scope-name">Scope name</Label>
                    <Input
                      id="edit-scope-name"
                      required
                      value={editingScope.name}
                      onChange={(event) =>
                        setEditingScope({ ...editingScope, name: event.target.value })
                      }
                      className="h-10 shadow-none"
                    />
                  </div>
                  <div className="space-y-1.5 sm:col-span-2">
                    <Label htmlFor="edit-scope-program">Project</Label>
                    <select
                      id="edit-scope-program"
                      value={editingScope.program_id ?? ""}
                      onChange={(event) =>
                        setEditingScope({
                          ...editingScope,
                          program_id: event.target.value || null,
                        })
                      }
                      className={fieldClass}
                    >
                      <option value="">Ungrouped</option>
                      {programs.map((program) => (
                        <option key={program.id} value={program.id}>
                          {program.name}
                        </option>
                      ))}
                    </select>
                  </div>
                  <div className="space-y-1.5">
                    <Label htmlFor="edit-scope-vertical">Vertical</Label>
                    <Input
                      id="edit-scope-vertical"
                      value={editingScope.vertical}
                      disabled
                      className="h-10 shadow-none"
                    />
                  </div>
                  <div className="space-y-1.5">
                    <Label htmlFor="edit-scope-status">Status</Label>
                    <select
                      id="edit-scope-status"
                      value={editingScope.status}
                      onChange={(event) =>
                        setEditingScope({
                          ...editingScope,
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
                    <Label htmlFor="edit-scope-start-date">Start date</Label>
                    <Input
                      id="edit-scope-start-date"
                      type="date"
                      value={editingScope.start_date}
                      disabled
                      className="h-10 shadow-none"
                    />
                  </div>
                  <div className="space-y-1.5">
                    <Label htmlFor="edit-scope-target-end-date">Target end date</Label>
                    <Input
                      id="edit-scope-target-end-date"
                      required
                      type="date"
                      value={editingScope.target_end_date}
                      onChange={(event) =>
                        setEditingScope({
                          ...editingScope,
                          target_end_date: event.target.value,
                        })
                      }
                      className="h-10 shadow-none"
                    />
                  </div>
                  <div className="space-y-1.5">
                    <Label htmlFor="edit-scope-actual-end-date">Actual end date</Label>
                    <Input
                      id="edit-scope-actual-end-date"
                      type="date"
                      value={editingScope.actual_end_date ?? ""}
                      onChange={(event) =>
                        setEditingScope({
                          ...editingScope,
                          actual_end_date: event.target.value || null,
                        })
                      }
                      className="h-10 shadow-none"
                    />
                  </div>
                  <div className="space-y-1.5">
                    <Label htmlFor="edit-scope-daily-target">Daily target</Label>
                    <Input
                      id="edit-scope-daily-target"
                      type="number"
                      min={0}
                      value={editingScope.daily_target_units ?? ""}
                      onChange={(event) =>
                        setEditingScope({
                          ...editingScope,
                          daily_target_units: event.target.value
                            ? Number(event.target.value)
                            : null,
                        })
                      }
                      placeholder="Daily target units"
                      className="h-10 shadow-none"
                    />
                  </div>
                  <div className="space-y-1.5 sm:col-span-2">
                    <Label htmlFor="edit-scope-description">Description</Label>
                    <textarea
                      id="edit-scope-description"
                      value={editingScope.description ?? ""}
                      onChange={(event) =>
                        setEditingScope({ ...editingScope, description: event.target.value })
                      }
                      placeholder="Description"
                      rows={3}
                      className="w-full resize-none rounded-sm border border-input bg-background px-3 py-2 text-sm shadow-none outline-none focus-visible:ring-1 focus-visible:ring-ring"
                    />
                  </div>
                </div>
              </div>
              <DialogFooter className="gap-2 border-t border-border bg-elevated/60 px-4 py-4 sm:justify-end sm:space-x-0 sm:px-6">
                <Button
                  type="button"
                  variant="outline"
                  className="shadow-none"
                  onClick={closeEditDialog}
                >
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
