import { useMemo, useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { ChevronsUpDown, Search, UserPlus, X } from "lucide-react";
import { toast } from "sonner";

import { deleteAnnotator, updateAnnotator } from "@/lib/api";
import { queryKeys } from "@/lib/queries/keys";
import { Sheet, SheetContent, SheetDescription, SheetHeader, SheetTitle } from "@/components/ui/sheet";
import {
  Command,
  CommandEmpty,
  CommandGroup,
  CommandInput,
  CommandItem,
  CommandList,
} from "@/components/ui/command";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
import { cn } from "@/lib/utils";
import type { AnnotatorRead, TeamRead } from "@/types/workforce";

import { AnnotatorCreateForm } from "./AnnotatorCreateForm";
import { removeButtonClass, SITE_LABELS } from "./workforceManagementUtils";

type TeamMembersDrawerProps = {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  team: TeamRead | null;
  /** All annotators across the project (from the workforce summary). */
  annotators: AnnotatorRead[];
  projectId: string | null;
  canManage: boolean;
};

export function TeamMembersDrawer({
  open,
  onOpenChange,
  team,
  annotators,
  projectId,
  canManage,
}: TeamMembersDrawerProps) {
  const queryClient = useQueryClient();
  const [query, setQuery] = useState("");
  const [assignOpen, setAssignOpen] = useState(false);
  const [confirmRemoveId, setConfirmRemoveId] = useState<string | null>(null);

  const members = useMemo(
    () =>
      team
        ? annotators
            .filter((annotator) => annotator.team_id === team.id)
            .sort((left, right) => left.full_name.localeCompare(right.full_name))
        : [],
    [annotators, team],
  );

  const filteredMembers = useMemo(() => {
    const normalized = query.trim().toLowerCase();
    if (!normalized) return members;
    return members.filter((member) => member.full_name.toLowerCase().includes(normalized));
  }, [members, query]);

  // Annotators on other teams within the same project — the pool that can be moved in.
  const assignable = useMemo(
    () =>
      team
        ? annotators
            .filter((annotator) => annotator.team_id !== team.id)
            .sort((left, right) => left.full_name.localeCompare(right.full_name))
        : [],
    [annotators, team],
  );

  const invalidate = (teamIds: string[]) => {
    if (projectId) {
      void queryClient.invalidateQueries({
        queryKey: queryKeys.projectWorkforceSummary(projectId),
      });
      void queryClient.invalidateQueries({ queryKey: queryKeys.projectTeams(projectId) });
    }
    for (const teamId of new Set(teamIds)) {
      void queryClient.invalidateQueries({ queryKey: queryKeys.teamAnnotators(teamId) });
    }
  };

  const assignMutation = useMutation({
    mutationFn: (annotator: AnnotatorRead) => {
      if (!team) throw new Error("No team selected.");
      return updateAnnotator(annotator.id, { team_id: team.id });
    },
    onSuccess: (updated, annotator) => {
      invalidate([annotator.team_id, updated.team_id]);
      setAssignOpen(false);
      toast.success(`${updated.full_name} moved to ${team?.name ?? "team"}.`);
    },
    onError: (err: Error) => toast.error(err.message),
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

  const busy = assignMutation.isPending || removeMutation.isPending;

  return (
    <Sheet open={open} onOpenChange={onOpenChange}>
      <SheetContent side="right" className="w-full overflow-y-auto sm:max-w-lg">
        {team && (
          <div className="space-y-4">
            <SheetHeader className="space-y-1">
              <SheetTitle>{team.name} · Members</SheetTitle>
              <SheetDescription>
                {members.length} {members.length === 1 ? "member" : "members"} ·{" "}
                {SITE_LABELS[team.site]} · {team.domain}
              </SheetDescription>
            </SheetHeader>

            {/* Search + assign existing */}
            <div className="flex items-center gap-2">
              <div className="flex h-9 flex-1 items-center gap-2 rounded-sm border border-input bg-background px-2.5">
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

              {canManage && (
                <Popover open={assignOpen} onOpenChange={setAssignOpen}>
                  <PopoverTrigger asChild>
                    <button
                      type="button"
                      disabled={busy}
                      className="flex h-9 items-center gap-1.5 rounded-sm bg-[color:var(--brand)] px-3 text-xs font-medium text-[color:var(--brand-foreground)] hover:bg-[color:var(--brand)]/90 disabled:opacity-50"
                    >
                      <UserPlus className="h-3.5 w-3.5" />
                      Assign
                      <ChevronsUpDown className="h-3 w-3 opacity-70" />
                    </button>
                  </PopoverTrigger>
                  <PopoverContent align="end" className="w-72 p-0">
                    <Command>
                      <CommandInput placeholder="Search people to move here..." className="text-xs" />
                      <CommandList>
                        <CommandEmpty>No available people found.</CommandEmpty>
                        <CommandGroup>
                          {assignable.map((annotator) => (
                            <CommandItem
                              key={annotator.id}
                              value={annotator.full_name}
                              disabled={busy}
                              onSelect={() => assignMutation.mutate(annotator)}
                              className="flex items-center justify-between gap-2 text-xs"
                            >
                              <span className="truncate">{annotator.full_name}</span>
                              <span className="shrink-0 text-[10px] text-muted-foreground">
                                {SITE_LABELS[annotator.site]}
                              </span>
                            </CommandItem>
                          ))}
                        </CommandGroup>
                      </CommandList>
                    </Command>
                  </PopoverContent>
                </Popover>
              )}
            </div>

            {/* Roster */}
            <div className="rounded border border-border">
              {filteredMembers.length === 0 ? (
                <p className="px-3 py-4 text-xs text-muted-foreground">
                  {members.length === 0 ? "No members on this team yet." : "No members match your search."}
                </p>
              ) : (
                <ul className="divide-y divide-border/60">
                  {filteredMembers.map((member) => (
                    <li key={member.id} className="flex items-center justify-between gap-2 px-3 py-2">
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

            {/* Add a brand-new member — reuses the shared workforce form */}
            {canManage && projectId && (
              <AnnotatorCreateForm
                projectId={projectId}
                teamId={team.id}
                defaultSite={team.site}
                canManage={canManage}
              />
            )}
          </div>
        )}
      </SheetContent>
    </Sheet>
  );
}
