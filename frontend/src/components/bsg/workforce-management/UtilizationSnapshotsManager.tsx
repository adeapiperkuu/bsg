import { useMemo, useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";

import { createUtilizationSnapshot } from "@/lib/api";
import { queryKeys } from "@/lib/queries/keys";
import { useProjectUtilizationQuery } from "@/lib/queries/workforce";
import type { TeamRead } from "@/types/workforce";

import { UtilizationSnapshotRow } from "./UtilizationSnapshotRow";
import { ErrorText } from "./WorkforceManagementShared";
import {
  addButtonClass,
  inputClass,
  numberClass,
  selectClass,
  SITE_LABELS,
  todayIso,
} from "./workforceManagementUtils";

type UtilizationSnapshotsManagerProps = {
  projectId: string;
  teams: TeamRead[];
  canManage: boolean;
};

export function UtilizationSnapshotsManager({
  projectId,
  teams,
  canManage,
}: UtilizationSnapshotsManagerProps) {
  const queryClient = useQueryClient();
  const utilizationQuery = useProjectUtilizationQuery(projectId, true);
  const [teamId, setTeamId] = useState("");
  const [snapshotDate, setSnapshotDate] = useState(todayIso());
  const [allocated, setAllocated] = useState("");
  const [available, setAvailable] = useState("");
  const [utilizationPct, setUtilizationPct] = useState("");
  const [notes, setNotes] = useState("");
  const [error, setError] = useState<string | null>(null);

  const teamNameById = useMemo(() => {
    const map = new Map<string, string>();
    for (const team of teams) map.set(team.id, team.name);
    return map;
  }, [teams]);

  const teamSnapshots = (utilizationQuery.data ?? []).filter(
    (snapshot) => snapshot.annotator_id === null,
  );

  const invalidate = () => {
    void queryClient.invalidateQueries({
      queryKey: ["projects", projectId, "utilization"],
    });
    void queryClient.invalidateQueries({
      queryKey: queryKeys.projectCapabilityGaps(projectId),
    });
  };

  const addMutation = useMutation({
    mutationFn: () =>
      createUtilizationSnapshot(projectId, {
        team_id: teamId || null,
        snapshot_date: snapshotDate,
        allocated_hours: Number(allocated) || 0,
        available_hours: Number(available) || 0,
        utilization_pct: utilizationPct.trim() === "" ? null : Number(utilizationPct),
        notes: notes.trim() === "" ? null : notes.trim(),
      }),
    onSuccess: () => {
      setError(null);
      setTeamId("");
      setSnapshotDate(todayIso());
      setAllocated("");
      setAvailable("");
      setUtilizationPct("");
      setNotes("");
      invalidate();
    },
    onError: (err: Error) => setError(err.message),
  });

  const canSubmit =
    Boolean(teamId) && allocated.trim() !== "" && available.trim() !== "" && snapshotDate !== "";
  const busy = addMutation.isPending;

  return (
    <div className="mt-4 rounded-md border border-border bg-elevated/40 p-3">
      <h4 className="mb-2 text-xs font-semibold uppercase tracking-wider text-muted-foreground">
        Manage team utilization snapshots
      </h4>
      {utilizationQuery.isLoading ? (
        <div className="space-y-1.5">
          <div className="h-8 animate-pulse rounded bg-elevated" />
          <div className="h-8 animate-pulse rounded bg-elevated" />
        </div>
      ) : teamSnapshots.length === 0 ? (
        <p className="text-[11px] text-muted-foreground">No team-level snapshots yet.</p>
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full text-[11px]">
            <thead className="text-left text-muted-foreground">
              <tr className="border-b border-border">
                <th className="py-1.5 pr-2 font-medium">Team</th>
                <th className="py-1.5 pr-2 font-medium">Date</th>
                <th className="py-1.5 pr-2 font-medium">Allocated</th>
                <th className="py-1.5 pr-2 font-medium">Available</th>
                <th className="py-1.5 pr-2 font-medium">Util %</th>
                {canManage ? <th className="py-1.5 pr-2 font-medium" /> : null}
              </tr>
            </thead>
            <tbody>
              {teamSnapshots.map((snapshot) => (
                <UtilizationSnapshotRow
                  key={snapshot.id}
                  snapshot={snapshot}
                  teamName={
                    snapshot.team_id
                      ? (teamNameById.get(snapshot.team_id) ?? "Team")
                      : "Project-wide"
                  }
                  canManage={canManage}
                  onChanged={invalidate}
                  onError={setError}
                />
              ))}
            </tbody>
          </table>
        </div>
      )}

      {canManage ? (
        <div className="mt-3 flex flex-wrap items-end gap-2">
          <label className="flex flex-col gap-0.5 text-[10px] text-muted-foreground">
            Team
            <select
              value={teamId}
              disabled={busy || teams.length === 0}
              onChange={(event) => setTeamId(event.target.value)}
              className={selectClass}
            >
              <option value="">{teams.length === 0 ? "No teams" : "Select team..."}</option>
              {teams.map((team) => (
                <option key={team.id} value={team.id}>
                  {team.name} ({SITE_LABELS[team.site]})
                </option>
              ))}
            </select>
          </label>
          <label className="flex flex-col gap-0.5 text-[10px] text-muted-foreground">
            Date
            <input
              type="date"
              value={snapshotDate}
              disabled={busy}
              onChange={(event) => setSnapshotDate(event.target.value)}
              className={selectClass}
            />
          </label>
          <label className="flex flex-col gap-0.5 text-[10px] text-muted-foreground">
            Allocated
            <input
              type="number"
              min={0}
              step="0.5"
              value={allocated}
              disabled={busy}
              onChange={(event) => setAllocated(event.target.value)}
              className={numberClass}
            />
          </label>
          <label className="flex flex-col gap-0.5 text-[10px] text-muted-foreground">
            Available
            <input
              type="number"
              min={0}
              step="0.5"
              value={available}
              disabled={busy}
              onChange={(event) => setAvailable(event.target.value)}
              className={numberClass}
            />
          </label>
          <label className="flex flex-col gap-0.5 text-[10px] text-muted-foreground">
            Util % (optional)
            <input
              type="number"
              min={0}
              step="0.1"
              value={utilizationPct}
              disabled={busy}
              placeholder="auto"
              onChange={(event) => setUtilizationPct(event.target.value)}
              className={numberClass}
            />
          </label>
          <label className="flex flex-1 flex-col gap-0.5 text-[10px] text-muted-foreground">
            Notes (optional)
            <input
              type="text"
              value={notes}
              disabled={busy}
              onChange={(event) => setNotes(event.target.value)}
              className={inputClass}
            />
          </label>
          <button
            type="button"
            disabled={busy || !canSubmit}
            onClick={() => addMutation.mutate()}
            className={addButtonClass}
          >
            {addMutation.isPending ? "Adding..." : "Add snapshot"}
          </button>
        </div>
      ) : null}
      <ErrorText message={error} />
    </div>
  );
}
