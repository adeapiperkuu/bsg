import { createFileRoute } from "@tanstack/react-router";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useMemo, useRef, useState } from "react";
import { toast } from "sonner";
import { Card, SectionHeader, StatusPill } from "@/components/bsg/widgets";
import { PageLoadingScreen } from "@/components/bsg/PageLoadingScreen";
import { Button } from "@/components/ui/button";
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from "@/components/ui/alert-dialog";
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
import { createProjectTeam, deleteTeam, updateTeam } from "@/lib/api";
import { useProjectsQuery } from "@/lib/queries/delivery";
import { queryKeys } from "@/lib/queries/keys";
import {
  projectWorkforceSummaryQueryOptions,
  useProjectTeamsQuery,
} from "@/lib/queries/workforce";
import { canManageWorkforce, canReadInternalWorkforce } from "@/lib/workforcePermissions";
import { useAuthStore } from "@/stores/useAuthStore";
import { TeamMembersDrawer } from "@/components/bsg/workforce-management/TeamMembersDrawer";
import { cn } from "@/lib/utils";
import type { DeliverySite, TeamCreatePayload, TeamRead } from "@/types/workforce";
import { Search, X } from "lucide-react";

export const Route = createFileRoute("/teams")({ component: TeamsPage });

const siteOptions: DeliverySite[] = ["india", "kosovo"];

function siteLabel(site: DeliverySite): string {
  return site.charAt(0).toUpperCase() + site.slice(1);
}

function emptyCreateForm(): TeamCreatePayload {
  return {
    name: "",
    domain: "",
    site: "india",
    is_active: true,
  };
}

const fieldClass =
  "h-10 w-full rounded-sm border border-input bg-background px-3 text-sm shadow-none outline-none focus-visible:ring-1 focus-visible:ring-ring";

function TeamsPage() {
  const queryClient = useQueryClient();
  const projectsQuery = useProjectsQuery();
  const projects = useMemo(() => projectsQuery.data ?? [], [projectsQuery.data]);

  const [projectId, setProjectId] = useState<string | null>(null);

  // Default to the first project once projects load.
  useEffect(() => {
    if (!projectId && projects.length > 0) {
      setProjectId(projects[0].id);
    }
  }, [projects, projectId]);

  const userRole = useAuthStore((state) => state.user?.role);
  const canManage = canManageWorkforce(userRole);
  const canReadMembers = canReadInternalWorkforce(userRole);

  const teamsQuery = useProjectTeamsQuery(projectId);
  const teams = useMemo(() => teamsQuery.data ?? [], [teamsQuery.data]);
  const loading = projectsQuery.isLoading || (Boolean(projectId) && teamsQuery.isLoading);

  // Workforce summary gives every annotator in the project — used for member
  // counts and for the "assign existing member" pool inside the drawer.
  const summaryQuery = useQuery(
    projectWorkforceSummaryQueryOptions(projectId, canReadMembers),
  );
  const annotators = useMemo(
    () => summaryQuery.data?.annotators ?? [],
    [summaryQuery.data],
  );
  const memberCountByTeam = useMemo(() => {
    const counts = new Map<string, number>();
    for (const annotator of annotators) {
      counts.set(annotator.team_id, (counts.get(annotator.team_id) ?? 0) + 1);
    }
    return counts;
  }, [annotators]);

  const [membersTeam, setMembersTeam] = useState<TeamRead | null>(null);

  const [query, setQuery] = useState("");
  const [isSearchOpen, setIsSearchOpen] = useState(false);
  const searchInputRef = useRef<HTMLInputElement>(null);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [editingTeam, setEditingTeam] = useState<TeamRead | null>(null);
  const [isCreateOpen, setIsCreateOpen] = useState(false);
  const [createForm, setCreateForm] = useState<TeamCreatePayload>(emptyCreateForm);
  const [deletingTeam, setDeletingTeam] = useState<TeamRead | null>(null);
  const [deleting, setDeleting] = useState(false);

  const selectedProject = useMemo(
    () => projects.find((project) => project.id === projectId) ?? null,
    [projects, projectId],
  );

  const filteredTeams = useMemo(() => {
    const normalized = query.trim().toLowerCase();
    if (!normalized) return teams;
    return teams.filter((team) =>
      [team.name, team.domain, team.site, team.is_active ? "active" : "inactive"]
        .filter(Boolean)
        .some((value) => String(value).toLowerCase().includes(normalized)),
    );
  }, [teams, query]);

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

  const refreshTeams = () => {
    if (!projectId) return;
    void queryClient.invalidateQueries({ queryKey: queryKeys.projectTeams(projectId) });
  };

  const closeCreateDialog = () => {
    setIsCreateOpen(false);
    setCreateForm(emptyCreateForm());
    setError(null);
  };

  const submitCreate = (event: React.FormEvent) => {
    event.preventDefault();
    if (!projectId) return;
    setSaving(true);
    setError(null);
    createProjectTeam(projectId, {
      ...createForm,
      name: createForm.name.trim(),
      domain: createForm.domain.trim(),
    })
      .then(() => {
        refreshTeams();
        closeCreateDialog();
        toast.success("Team created.");
      })
      .catch((err: unknown) => {
        const message = err instanceof Error ? err.message : "Team could not be created.";
        setError(message);
        toast.error(message);
      })
      .finally(() => setSaving(false));
  };

  const closeEditDialog = () => {
    setEditingTeam(null);
    setError(null);
  };

  const submitEdit = (event: React.FormEvent) => {
    event.preventDefault();
    if (!editingTeam) return;
    setSaving(true);
    setError(null);
    updateTeam(editingTeam.id, {
      name: editingTeam.name.trim(),
      domain: editingTeam.domain.trim(),
      site: editingTeam.site,
      is_active: editingTeam.is_active,
    })
      .then(() => {
        refreshTeams();
        closeEditDialog();
        toast.success("Team updated.");
      })
      .catch((err: unknown) => {
        const message = err instanceof Error ? err.message : "Team could not be updated.";
        setError(message);
        toast.error(message);
      })
      .finally(() => setSaving(false));
  };

  const confirmDelete = () => {
    if (!deletingTeam) return;
    setDeleting(true);
    deleteTeam(deletingTeam.id)
      .then(() => {
        refreshTeams();
        setDeletingTeam(null);
        toast.success("Team deleted.");
      })
      .catch((err: unknown) => {
        toast.error(err instanceof Error ? err.message : "Team could not be deleted.");
      })
      .finally(() => setDeleting(false));
  };

  return (
    <div className="space-y-5">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div className="space-y-1.5">
          <Label htmlFor="teams-project" className="text-xs text-muted-foreground">
            Project
          </Label>
          <select
            id="teams-project"
            value={projectId ?? ""}
            onChange={(event) => setProjectId(event.target.value || null)}
            className={cn(fieldClass, "w-64")}
            disabled={projectsQuery.isLoading || projects.length === 0}
          >
            {projects.length === 0 && <option value="">No projects available</option>}
            {projects.map((project) => (
              <option key={project.id} value={project.id}>
                {project.name}
              </option>
            ))}
          </select>
        </div>

        <div className="flex items-center gap-2 self-end">
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
              aria-label="Search teams"
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
              placeholder="Search teams..."
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
          <Button
            type="button"
            size="sm"
            className="h-[30px] rounded-sm bg-[color:var(--brand)] px-3 text-xs text-[color:var(--brand-foreground)] shadow-none hover:bg-[color:var(--brand)]/90"
            onClick={() => setIsCreateOpen(true)}
            disabled={!projectId}
          >
            Create
          </Button>
        </div>
      </div>

      {error && !isCreateOpen && !editingTeam && !loading && (
        <Card>
          <p className="text-sm text-[color:var(--danger)]">{error}</p>
        </Card>
      )}

      {loading ? (
        <PageLoadingScreen />
      ) : (
        <Card className="rounded-md">
          <SectionHeader
            title="Teams"
            sub={selectedProject ? `Teams for ${selectedProject.name}` : undefined}
          />
          {filteredTeams.length === 0 ? (
            <p className="text-sm text-muted-foreground">No teams found.</p>
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full text-xs">
                <thead className="text-left text-muted-foreground">
                  <tr className="border-b border-border">
                    <th className="py-2 pr-3 font-medium">Team</th>
                    <th className="py-2 pr-3 font-medium">Domain</th>
                    <th className="py-2 pr-3 font-medium">Site</th>
                    <th className="py-2 pr-3 font-medium">Project</th>
                    {canReadMembers && <th className="py-2 pr-3 font-medium">Members</th>}
                    <th className="py-2 pr-3 font-medium">Status</th>
                    <th className="py-2 pr-3 font-medium"></th>
                  </tr>
                </thead>
                <tbody>
                  {filteredTeams.map((team) => (
                    <tr key={team.id} className="border-b border-border/50">
                      <td className="py-2.5 pr-3 font-medium">{team.name}</td>
                      <td className="py-2.5 pr-3">{team.domain || "No data"}</td>
                      <td className="py-2.5 pr-3">{siteLabel(team.site)}</td>
                      <td className="py-2.5 pr-3">{selectedProject?.name ?? "No data"}</td>
                      {canReadMembers && (
                        <td className="py-2.5 pr-3">
                          {summaryQuery.isLoading
                            ? "…"
                            : (memberCountByTeam.get(team.id) ?? 0)}
                        </td>
                      )}
                      <td className="py-2.5 pr-3">
                        <StatusPill status={team.is_active ? "Active" : "Inactive"} />
                      </td>
                      <td className="py-2.5 pr-3">
                        <div className="flex items-center gap-2">
                          {canReadMembers && (
                            <button
                              type="button"
                              onClick={() => setMembersTeam(team)}
                              className="rounded-sm border border-border px-3 py-1 text-xs font-medium hover:bg-elevated"
                            >
                              Members
                            </button>
                          )}
                          <button
                            type="button"
                            onClick={() => setEditingTeam({ ...team })}
                            className="rounded-sm bg-[color:var(--brand)] px-3 py-1 text-xs font-medium text-[color:var(--brand-foreground)] hover:bg-[color:var(--brand)]/90"
                          >
                            Edit
                          </button>
                          <button
                            type="button"
                            onClick={() => setDeletingTeam(team)}
                            className="rounded-sm border border-border px-3 py-1 text-xs font-medium hover:bg-elevated"
                          >
                            Delete
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
            <DialogTitle>Create Team</DialogTitle>
            <DialogDescription>Saved through the backend Teams API.</DialogDescription>
          </DialogHeader>
          <form onSubmit={submitCreate}>
            <div className="max-h-[calc(100svh-14rem)] space-y-4 overflow-y-auto px-4 py-4 sm:max-h-[70vh] sm:px-6">
              {error && <p className="text-sm text-[color:var(--danger)]">{error}</p>}
              <div className="grid gap-4 sm:grid-cols-2">
                <div className="space-y-1.5 sm:col-span-2">
                  <Label htmlFor="team-name">Team name</Label>
                  <Input
                    id="team-name"
                    required
                    value={createForm.name}
                    onChange={(event) => setCreateForm({ ...createForm, name: event.target.value })}
                    placeholder="Team name"
                    className="h-10 shadow-none"
                  />
                </div>
                <div className="space-y-1.5">
                  <Label htmlFor="team-domain">Domain</Label>
                  <Input
                    id="team-domain"
                    required
                    value={createForm.domain}
                    onChange={(event) =>
                      setCreateForm({ ...createForm, domain: event.target.value })
                    }
                    placeholder="Domain"
                    className="h-10 shadow-none"
                  />
                </div>
                <div className="space-y-1.5">
                  <Label htmlFor="team-site">Site</Label>
                  <select
                    id="team-site"
                    value={createForm.site}
                    onChange={(event) =>
                      setCreateForm({ ...createForm, site: event.target.value as DeliverySite })
                    }
                    className={fieldClass}
                  >
                    {siteOptions.map((site) => (
                      <option key={site} value={site}>
                        {siteLabel(site)}
                      </option>
                    ))}
                  </select>
                </div>
                <div className="flex items-center gap-2 sm:col-span-2">
                  <input
                    id="team-active"
                    type="checkbox"
                    checked={createForm.is_active ?? true}
                    onChange={(event) =>
                      setCreateForm({ ...createForm, is_active: event.target.checked })
                    }
                    className="h-4 w-4 rounded-sm border-input"
                  />
                  <Label htmlFor="team-active">Active</Label>
                </div>
              </div>
            </div>
            <DialogFooter className="gap-2 border-t border-border bg-elevated/60 px-4 py-4 sm:justify-end sm:space-x-0 sm:px-6">
              <Button
                type="button"
                variant="outline"
                className="shadow-none"
                onClick={closeCreateDialog}
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
        open={Boolean(editingTeam)}
        onOpenChange={(open) => {
          if (!open) closeEditDialog();
        }}
      >
        <DialogContent className="max-w-lg gap-0 overflow-hidden p-0 sm:max-w-xl">
          <DialogHeader className="border-b border-border bg-elevated/60 px-4 py-4 sm:px-6">
            <DialogTitle>Edit Team</DialogTitle>
            <DialogDescription>
              {editingTeam ? `Update details for ${editingTeam.name}.` : "Update team details."}
            </DialogDescription>
          </DialogHeader>
          {editingTeam && (
            <form onSubmit={submitEdit}>
              <div className="max-h-[calc(100svh-14rem)] space-y-4 overflow-y-auto px-4 py-4 sm:max-h-[70vh] sm:px-6">
                {error && <p className="text-sm text-[color:var(--danger)]">{error}</p>}
                <div className="grid gap-4 sm:grid-cols-2">
                  <div className="space-y-1.5 sm:col-span-2">
                    <Label htmlFor="edit-team-name">Team name</Label>
                    <Input
                      id="edit-team-name"
                      required
                      value={editingTeam.name}
                      onChange={(event) =>
                        setEditingTeam({ ...editingTeam, name: event.target.value })
                      }
                      className="h-10 shadow-none"
                    />
                  </div>
                  <div className="space-y-1.5">
                    <Label htmlFor="edit-team-domain">Domain</Label>
                    <Input
                      id="edit-team-domain"
                      required
                      value={editingTeam.domain}
                      onChange={(event) =>
                        setEditingTeam({ ...editingTeam, domain: event.target.value })
                      }
                      className="h-10 shadow-none"
                    />
                  </div>
                  <div className="space-y-1.5">
                    <Label htmlFor="edit-team-site">Site</Label>
                    <select
                      id="edit-team-site"
                      value={editingTeam.site}
                      onChange={(event) =>
                        setEditingTeam({
                          ...editingTeam,
                          site: event.target.value as DeliverySite,
                        })
                      }
                      className={fieldClass}
                    >
                      {siteOptions.map((site) => (
                        <option key={site} value={site}>
                          {siteLabel(site)}
                        </option>
                      ))}
                    </select>
                  </div>
                  <div className="flex items-center gap-2 sm:col-span-2">
                    <input
                      id="edit-team-active"
                      type="checkbox"
                      checked={editingTeam.is_active}
                      onChange={(event) =>
                        setEditingTeam({ ...editingTeam, is_active: event.target.checked })
                      }
                      className="h-4 w-4 rounded-sm border-input"
                    />
                    <Label htmlFor="edit-team-active">Active</Label>
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

      <AlertDialog
        open={Boolean(deletingTeam)}
        onOpenChange={(open) => !open && setDeletingTeam(null)}
      >
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>Delete team?</AlertDialogTitle>
            <AlertDialogDescription>
              {deletingTeam
                ? `This will remove "${deletingTeam.name}". This action cannot be undone.`
                : "This action cannot be undone."}
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel disabled={deleting}>Cancel</AlertDialogCancel>
            <AlertDialogAction disabled={deleting} onClick={() => void confirmDelete()}>
              {deleting ? "Deleting..." : "Delete"}
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>

      <TeamMembersDrawer
        open={Boolean(membersTeam)}
        onOpenChange={(open) => !open && setMembersTeam(null)}
        team={membersTeam}
        annotators={annotators}
        projectId={projectId}
        canManage={canManage}
      />
    </div>
  );
}
