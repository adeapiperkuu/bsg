import { useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";

import { createProjectTeam } from "@/lib/api";
import { queryKeys } from "@/lib/queries/keys";
import type { DeliverySite, TeamRead } from "@/types/workforce";

import { TeamRow } from "./TeamRow";
import { ErrorText } from "./WorkforceManagementShared";
import { addButtonClass, inputClass, selectClass, SITE_LABELS } from "./workforceManagementUtils";

const DELIVERY_SITES: DeliverySite[] = ["india", "kosovo"];

type TeamsManagerProps = {
  projectId: string;
  teams: TeamRead[];
  canManage: boolean;
};

export function TeamsManager({ projectId, teams, canManage }: TeamsManagerProps) {
  const queryClient = useQueryClient();
  const [name, setName] = useState("");
  const [site, setSite] = useState<DeliverySite>("india");
  const [domain, setDomain] = useState("");
  const [isActive, setIsActive] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const invalidate = () => {
    void queryClient.invalidateQueries({
      queryKey: queryKeys.projectTeams(projectId),
    });
    void queryClient.invalidateQueries({
      queryKey: queryKeys.projectWorkforceSummary(projectId),
    });
  };

  const addMutation = useMutation({
    mutationFn: () =>
      createProjectTeam(projectId, {
        name: name.trim(),
        site,
        domain: domain.trim(),
        is_active: isActive,
      }),
    onSuccess: () => {
      setError(null);
      setName("");
      setSite("india");
      setDomain("");
      setIsActive(true);
      invalidate();
    },
    onError: (err: Error) => setError(err.message),
  });

  const busy = addMutation.isPending;
  const canSubmit = name.trim().length > 0 && domain.trim().length > 0;

  if (!canManage) {
    return null;
  }

  return (
    <div className="mt-4 rounded-md border border-border bg-elevated/40 p-3">
      <h4 className="mb-2 text-xs font-semibold uppercase tracking-wider text-muted-foreground">
        Manage teams
      </h4>
      {teams.length === 0 ? (
        <p className="text-[11px] text-muted-foreground">No teams yet. Add the first team below.</p>
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full text-[11px]">
            <thead className="text-left text-muted-foreground">
              <tr className="border-b border-border">
                <th className="py-1.5 pr-2 font-medium">Name</th>
                <th className="py-1.5 pr-2 font-medium">Site</th>
                <th className="py-1.5 pr-2 font-medium">Domain</th>
                <th className="py-1.5 pr-2 font-medium">Status</th>
                <th className="py-1.5 pr-2 font-medium" />
              </tr>
            </thead>
            <tbody>
              {teams.map((team) => (
                <TeamRow
                  key={team.id}
                  team={team}
                  canManage={canManage}
                  onChanged={invalidate}
                  onError={setError}
                />
              ))}
            </tbody>
          </table>
        </div>
      )}

      <div className="mt-3 flex flex-wrap items-end gap-2">
        <label className="flex min-w-[140px] flex-1 flex-col gap-0.5 text-[10px] text-muted-foreground">
          Team name
          <input
            type="text"
            value={name}
            disabled={busy}
            onChange={(event) => setName(event.target.value)}
            className={inputClass}
            placeholder="e.g. Radiology QA"
          />
        </label>
        <label className="flex flex-col gap-0.5 text-[10px] text-muted-foreground">
          Site
          <select
            value={site}
            disabled={busy}
            onChange={(event) => setSite(event.target.value as DeliverySite)}
            className={selectClass}
          >
            {DELIVERY_SITES.map((value) => (
              <option key={value} value={value}>
                {SITE_LABELS[value]}
              </option>
            ))}
          </select>
        </label>
        <label className="flex min-w-[140px] flex-1 flex-col gap-0.5 text-[10px] text-muted-foreground">
          Domain
          <input
            type="text"
            value={domain}
            disabled={busy}
            onChange={(event) => setDomain(event.target.value)}
            className={inputClass}
            placeholder="e.g. Life Sciences"
          />
        </label>
        <label className="flex flex-col gap-0.5 text-[10px] text-muted-foreground">
          Status
          <select
            value={isActive ? "active" : "inactive"}
            disabled={busy}
            onChange={(event) => setIsActive(event.target.value === "active")}
            className={selectClass}
          >
            <option value="active">Active</option>
            <option value="inactive">Inactive</option>
          </select>
        </label>
        <button
          type="button"
          disabled={busy || !canSubmit}
          onClick={() => addMutation.mutate()}
          className={addButtonClass}
        >
          {addMutation.isPending ? "Adding..." : "Add team"}
        </button>
      </div>
      <ErrorText message={error} />
    </div>
  );
}
