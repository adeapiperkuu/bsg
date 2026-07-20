import { useEffect, useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Search, X } from "lucide-react";
import { toast } from "sonner";

import { createProjectTeam, deleteAnnotator } from "@/lib/api";
import { queryKeys } from "@/lib/queries/keys";
import {
  projectTeamsQueryOptions,
  projectWorkforceSummaryQueryOptions,
} from "@/lib/queries/workforce";
import { Sheet, SheetContent, SheetDescription, SheetHeader, SheetTitle } from "@/components/ui/sheet";
import { cn } from "@/lib/utils";
import type { AnnotatorRead, DeliverySite, TeamRead } from "@/types/workforce";

import { AnnotatorCreateForm } from "./AnnotatorCreateForm";
import { ErrorText } from "./WorkforceManagementShared";
import {
  addButtonClass,
  inputClass,
  removeButtonClass,
  selectClass,
  SITE_LABELS,
} from "./workforceManagementUtils";

type ScopeTeamSheetProps = {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  /** Scope (delivery project) id. */
  projectId: string | null;
  scopeName: string | null;
  canManage: boolean;
  canRead: boolean;
};

export function ScopeTeamSheet({
  open,
  onOpenChange,
  projectId,
  scopeName,
  canManage,
  canRead,
}: ScopeTeamSheetProps) {
  const queryClient = useQueryClient();
  const [selectedTeamId, setSelectedTeamId] = useState<string | null>(null);
  const [query, setQuery] = useState("");
  const [confirmRemoveId, setConfirmRemoveId] = useState<string | null>(null);
  const [newTeamName, setNewTeamName] = useState("");
  const [newTeamSite, setNewTeamSite] = useState<DeliverySite>("india");
  const [newTeamDomain, setNewTeamDomain] = useState("");
  const [createError, setCreateError] = useState<string | null>(null);

  const teamsQuery = useQuery({
    ...projectTeamsQueryOptions(open ? projectId : null),
  });
  const summaryQuery = useQuery(
    projectWorkforceSummaryQueryOptions(open ? projectId : null, canRead),
  );

  const teams = useMemo(() => teamsQuery.data ?? [], [teamsQuery.data]);
  const annotators = useMemo(
    () => summaryQuery.data?.annotators ?? [],
    [summaryQuery.data],
  );

  useEffect(() => {
    if (!open) {
      setSelectedTeamId(null);
      setQuery("");
      setConfirmRemoveId(null);
      setNewTeamName("");
      setNewTeamSite("india");
      setNewTeamDomain("");
      setCreateError(null);
      return;
    }
    if (teams.length === 0) {
      setSelectedTeamId(null);
      return;
    }
    setSelectedTeamId((current) =>
      current && teams.some((team) => team.id === current) ? current : teams[0]!.id,
    );
  }, [open, teams]);

  const selectedTeam: TeamRead | null =
    teams.find((team) => team.id === selectedTeamId) ?? null;

  const members = useMemo(
    () =>
      selectedTeam
        ? annotators
            .filter((annotator) => annotator.team_id === selectedTeam.id)
            .sort((left, right) => left.full_name.localeCompare(right.full_name))
        : [],
    [annotators, selectedTeam],
  );

  const filteredMembers = useMemo(() => {
    const normalized = query.trim().toLowerCase();
    if (!normalized) return members;
    return members.filter((member) => member.full_name.toLowerCase().includes(normalized));
  }, [members, query]);

  const invalidate = (teamIds: string[] = []) => {
    if (!projectId) return;
    void queryClient.invalidateQueries({
      queryKey: queryKeys.projectWorkforceSummary(projectId),
    });
    void queryClient.invalidateQueries({ queryKey: queryKeys.projectTeams(projectId) });
    for (const teamId of new Set(teamIds)) {
      void queryClient.invalidateQueries({ queryKey: queryKeys.teamAnnotators(teamId) });
    }
  };

  const createTeamMutation = useMutation({
    mutationFn: () => {
      if (!projectId) throw new Error("No scope selected.");
      return createProjectTeam(projectId, {
        name: newTeamName.trim() || scopeName?.trim() || "Team",
        site: newTeamSite,
        domain: newTeamDomain.trim() || scopeName?.trim() || "General",
        is_active: true,
      });
    },
    onSuccess: (team) => {
      setCreateError(null);
      setNewTeamName("");
      setNewTeamDomain("");
      invalidate([team.id]);
      setSelectedTeamId(team.id);
      toast.success(`Team “${team.name}” created.`);
    },
    onError: (err: Error) => {
      setCreateError(err.message);
      toast.error(err.message);
    },
  });

  const removeMutation = useMutation({
    mutationFn: (annotator: AnnotatorRead) => deleteAnnotator(annotator.id),
    onSuccess: (_result, annotator) => {
      invalidate([annotator.team_id]);
      setConfirmRemoveId(null);
      toast.success(`${annotator.full_name} removed.`);
    },
    onError: (err: Error) => toast.error(err.message),
  });

  const loading = teamsQuery.isLoading || (canRead && summaryQuery.isLoading);
  const busy = createTeamMutation.isPending || removeMutation.isPending;

  return (
    <Sheet open={open} onOpenChange={onOpenChange}>
      <SheetContent side="right" className="w-full overflow-y-auto sm:max-w-lg">
        <div className="space-y-4">
          <SheetHeader className="space-y-1">
            <SheetTitle>{scopeName ? `${scopeName} · Team` : "Team"}</SheetTitle>
            <SheetDescription>
              {selectedTeam
                ? `${members.length} ${members.length === 1 ? "member" : "members"} on ${selectedTeam.name}`
                : "Add or remove members for this scope."}
            </SheetDescription>
          </SheetHeader>

          {!canRead ? (
            <p className="text-xs text-muted-foreground">
              You do not have permission to view team members for this scope.
            </p>
          ) : loading ? (
            <p className="text-xs text-muted-foreground">Loading team…</p>
          ) : teams.length === 0 ? (
            <div className="space-y-3 rounded border border-border p-3">
              <p className="text-xs text-muted-foreground">
                No team on this scope yet
                {canManage ? ". Create one to start adding members." : "."}
              </p>
              {canManage && (
                <div className="space-y-2">
                  <label className="flex flex-col gap-0.5 text-[10px] text-muted-foreground">
                    Team name
                    <input
                      type="text"
                      value={newTeamName}
                      disabled={busy}
                      onChange={(event) => setNewTeamName(event.target.value)}
                      className={inputClass}
                      placeholder={scopeName ?? "Team name"}
                    />
                  </label>
                  <div className="flex flex-wrap gap-2">
                    <label className="flex flex-col gap-0.5 text-[10px] text-muted-foreground">
                      Site
                      <select
                        value={newTeamSite}
                        disabled={busy}
                        onChange={(event) =>
                          setNewTeamSite(event.target.value as DeliverySite)
                        }
                        className={selectClass}
                      >
                        <option value="india">{SITE_LABELS.india}</option>
                        <option value="kosovo">{SITE_LABELS.kosovo}</option>
                      </select>
                    </label>
                    <label className="flex min-w-[140px] flex-1 flex-col gap-0.5 text-[10px] text-muted-foreground">
                      Domain
                      <input
                        type="text"
                        value={newTeamDomain}
                        disabled={busy}
                        onChange={(event) => setNewTeamDomain(event.target.value)}
                        className={inputClass}
                        placeholder="e.g. Operations"
                      />
                    </label>
                  </div>
                  <button
                    type="button"
                    disabled={busy}
                    onClick={() => createTeamMutation.mutate()}
                    className={addButtonClass}
                  >
                    {createTeamMutation.isPending ? "Creating…" : "Create team"}
                  </button>
                  <ErrorText message={createError} />
                </div>
              )}
            </div>
          ) : (
            <>
              {teams.length > 1 && (
                <label className="flex flex-col gap-1 text-[10px] text-muted-foreground">
                  Team
                  <select
                    value={selectedTeamId ?? ""}
                    onChange={(event) => {
                      setSelectedTeamId(event.target.value || null);
                      setConfirmRemoveId(null);
                      setQuery("");
                    }}
                    className={cn(selectClass, "h-9 w-full text-xs")}
                  >
                    {teams.map((team) => (
                      <option key={team.id} value={team.id}>
                        {team.name} · {SITE_LABELS[team.site]}
                      </option>
                    ))}
                  </select>
                </label>
              )}

              <div className="flex h-9 items-center gap-2 rounded-sm border border-input bg-background px-2.5">
                <Search className="h-3.5 w-3.5 shrink-0 text-muted-foreground" />
                <input
                  value={query}
                  onChange={(event) => setQuery(event.target.value)}
                  placeholder="Search members..."
                  className="min-w-0 flex-1 bg-transparent text-xs outline-none placeholder:text-muted-foreground/80"
                />
                {query && (
                  <button
                    type="button"
                    aria-label="Clear search"
                    onClick={() => setQuery("")}
                    className="text-muted-foreground/70 hover:text-muted-foreground"
                  >
                    <X className="h-3 w-3" />
                  </button>
                )}
              </div>

              <div className="rounded border border-border">
                {filteredMembers.length === 0 ? (
                  <p className="px-3 py-4 text-xs text-muted-foreground">
                    {members.length === 0
                      ? "No members on this team yet."
                      : "No members match your search."}
                  </p>
                ) : (
                  <ul className="divide-y divide-border/60">
                    {filteredMembers.map((member) => (
                      <li
                        key={member.id}
                        className="flex items-center justify-between gap-2 px-3 py-2"
                      >
                        <div className="min-w-0">
                          <p className="truncate text-xs font-medium">{member.full_name}</p>
                          <p className="text-[10px] text-muted-foreground">
                            {SITE_LABELS[member.site]}
                            {member.is_sme_certified ? " · SME" : ""}
                            {member.is_active ? "" : " · Inactive"}
                          </p>
                        </div>
                        {canManage &&
                          (confirmRemoveId === member.id ? (
                            <div className="flex shrink-0 items-center gap-1">
                              <button
                                type="button"
                                disabled={busy}
                                onClick={() => removeMutation.mutate(member)}
                                className={removeButtonClass}
                              >
                                {removeMutation.isPending ? "Removing..." : "Confirm"}
                              </button>
                              <button
                                type="button"
                                disabled={busy}
                                onClick={() => setConfirmRemoveId(null)}
                                className="rounded border border-border bg-elevated px-1.5 py-0.5 text-[10px] hover:bg-card disabled:opacity-50"
                              >
                                Cancel
                              </button>
                            </div>
                          ) : (
                            <button
                              type="button"
                              disabled={busy}
                              onClick={() => setConfirmRemoveId(member.id)}
                              className={cn(removeButtonClass, "shrink-0")}
                            >
                              Remove
                            </button>
                          ))}
                      </li>
                    ))}
                  </ul>
                )}
              </div>

              {canManage && projectId && selectedTeam && (
                <AnnotatorCreateForm
                  projectId={projectId}
                  teamId={selectedTeam.id}
                  defaultSite={selectedTeam.site}
                  canManage={canManage}
                />
              )}
            </>
          )}
        </div>
      </SheetContent>
    </Sheet>
  );
}
