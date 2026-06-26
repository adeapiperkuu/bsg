import { useMemo, useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";

import {
  createProjectSkillRequirement,
  createUtilizationSnapshot,
  deleteProjectSkillRequirement,
  deleteUtilizationSnapshot,
  updateProjectSkillRequirement,
  updateUtilizationSnapshot,
} from "@/lib/api";
import { queryKeys } from "@/lib/queries/keys";
import {
  normalizeUtilizationPct,
  useProjectSkillRequirementsQuery,
  useProjectUtilizationQuery,
  useWorkforceSkillsQuery,
} from "@/lib/queries/workforce";
import type {
  DeliverySite,
  ProficiencyLevel,
  ProjectSkillRequirementRead,
  SkillRequirementPriority,
  TeamRead,
  UtilizationSnapshotRead,
} from "@/types/workforce";

const PROFICIENCY_LEVELS: ProficiencyLevel[] = [
  "beginner",
  "intermediate",
  "advanced",
  "expert",
];

const PRIORITIES: SkillRequirementPriority[] = ["low", "medium", "high", "critical"];

const SITE_LABELS: Record<DeliverySite, string> = {
  india: "India",
  kosovo: "Kosovo",
};

const selectClass =
  "rounded border border-border bg-card px-2 py-1 text-[11px] outline-none";
const inputClass =
  "w-full rounded border border-border bg-card px-2 py-1 text-[11px] outline-none";
const numberClass =
  "w-16 rounded border border-border bg-card px-2 py-1 text-[11px] outline-none";
const addButtonClass =
  "rounded border border-[color:var(--brand)]/30 bg-[color:var(--brand)]/10 px-2.5 py-1 text-[11px] font-medium text-[color:var(--brand)] hover:bg-[color:var(--brand)]/20 disabled:opacity-50";
const removeButtonClass =
  "rounded border border-border bg-elevated px-1.5 py-0.5 text-[10px] text-[color:var(--danger)] hover:bg-card disabled:opacity-50";

function titleize(value: string): string {
  return value.charAt(0).toUpperCase() + value.slice(1);
}

function ErrorText({ message }: { message: string | null }) {
  if (!message) return null;
  return <p className="mt-2 text-[11px] text-[color:var(--danger)]">{message}</p>;
}

function todayIso(): string {
  return new Date().toISOString().slice(0, 10);
}

export function SkillRequirementsManager({
  projectId,
  canManage,
}: {
  projectId: string;
  canManage: boolean;
}) {
  const queryClient = useQueryClient();
  const requirementsQuery = useProjectSkillRequirementsQuery(projectId, true);
  const skillsQuery = useWorkforceSkillsQuery(true);
  const [skillId, setSkillId] = useState("");
  const [proficiency, setProficiency] = useState<ProficiencyLevel>("intermediate");
  const [headcount, setHeadcount] = useState("1");
  const [smeCount, setSmeCount] = useState("0");
  const [priority, setPriority] = useState<SkillRequirementPriority>("medium");
  const [error, setError] = useState<string | null>(null);

  const skillNameById = useMemo(() => {
    const map = new Map<string, string>();
    for (const skill of skillsQuery.data ?? []) map.set(skill.id, skill.name);
    return map;
  }, [skillsQuery.data]);

  const requirements = requirementsQuery.data ?? [];
  const requiredSkillIds = new Set(requirements.map((row) => row.skill_id));
  const availableSkills = (skillsQuery.data ?? []).filter(
    (skill) => !requiredSkillIds.has(skill.id),
  );

  const invalidate = () => {
    void queryClient.invalidateQueries({
      queryKey: queryKeys.projectSkillRequirements(projectId),
    });
    void queryClient.invalidateQueries({
      queryKey: queryKeys.projectSkillMatrix(projectId),
    });
    void queryClient.invalidateQueries({
      queryKey: queryKeys.projectCapabilityGaps(projectId),
    });
  };

  const addMutation = useMutation({
    mutationFn: () =>
      createProjectSkillRequirement(projectId, {
        skill_id: skillId,
        required_proficiency_level: proficiency,
        required_headcount: Number(headcount) || 0,
        required_sme_count: Number(smeCount) || 0,
        priority,
      }),
    onSuccess: () => {
      setError(null);
      setSkillId("");
      setProficiency("intermediate");
      setHeadcount("1");
      setSmeCount("0");
      setPriority("medium");
      invalidate();
    },
    onError: (err: Error) => setError(err.message),
  });

  const busy = addMutation.isPending;

  return (
    <div className="mt-4 rounded-md border border-border bg-elevated/40 p-3">
      <h4 className="mb-2 text-xs font-semibold uppercase tracking-wider text-muted-foreground">
        Manage skill requirements
      </h4>
      {requirementsQuery.isLoading ? (
        <div className="space-y-1.5">
          <div className="h-8 animate-pulse rounded bg-elevated" />
          <div className="h-8 animate-pulse rounded bg-elevated" />
        </div>
      ) : requirements.length === 0 ? (
        <p className="text-[11px] text-muted-foreground">No skill requirements yet.</p>
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full text-[11px]">
            <thead className="text-left text-muted-foreground">
              <tr className="border-b border-border">
                <th className="py-1.5 pr-2 font-medium">Skill</th>
                <th className="py-1.5 pr-2 font-medium">Proficiency</th>
                <th className="py-1.5 pr-2 font-medium">Headcount</th>
                <th className="py-1.5 pr-2 font-medium">SMEs</th>
                <th className="py-1.5 pr-2 font-medium">Priority</th>
                {canManage ? <th className="py-1.5 pr-2 font-medium" /> : null}
              </tr>
            </thead>
            <tbody>
              {requirements.map((requirement) => (
                <RequirementRow
                  key={requirement.id}
                  requirement={requirement}
                  skillName={skillNameById.get(requirement.skill_id) ?? "Skill"}
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
          <select
            value={skillId}
            disabled={busy || availableSkills.length === 0}
            onChange={(event) => setSkillId(event.target.value)}
            className={selectClass}
          >
            <option value="">
              {availableSkills.length === 0 ? "No skills available" : "Select skill..."}
            </option>
            {availableSkills.map((skill) => (
              <option key={skill.id} value={skill.id}>
                {skill.name}
              </option>
            ))}
          </select>
          <select
            value={proficiency}
            disabled={busy}
            onChange={(event) => setProficiency(event.target.value as ProficiencyLevel)}
            className={selectClass}
          >
            {PROFICIENCY_LEVELS.map((level) => (
              <option key={level} value={level}>
                {titleize(level)}
              </option>
            ))}
          </select>
          <label className="flex flex-col gap-0.5 text-[10px] text-muted-foreground">
            Headcount
            <input
              type="number"
              min={0}
              value={headcount}
              disabled={busy}
              onChange={(event) => setHeadcount(event.target.value)}
              className={numberClass}
            />
          </label>
          <label className="flex flex-col gap-0.5 text-[10px] text-muted-foreground">
            SMEs
            <input
              type="number"
              min={0}
              value={smeCount}
              disabled={busy}
              onChange={(event) => setSmeCount(event.target.value)}
              className={numberClass}
            />
          </label>
          <select
            value={priority}
            disabled={busy}
            onChange={(event) => setPriority(event.target.value as SkillRequirementPriority)}
            className={selectClass}
          >
            {PRIORITIES.map((value) => (
              <option key={value} value={value}>
                {titleize(value)}
              </option>
            ))}
          </select>
          <button
            type="button"
            disabled={busy || !skillId}
            onClick={() => addMutation.mutate()}
            className={addButtonClass}
          >
            {addMutation.isPending ? "Adding..." : "Add requirement"}
          </button>
        </div>
      ) : null}
      <ErrorText message={error} />
    </div>
  );
}

function RequirementRow({
  requirement,
  skillName,
  canManage,
  onChanged,
  onError,
}: {
  requirement: ProjectSkillRequirementRead;
  skillName: string;
  canManage: boolean;
  onChanged: () => void;
  onError: (message: string | null) => void;
}) {
  const [headcount, setHeadcount] = useState(String(requirement.required_headcount));
  const [smeCount, setSmeCount] = useState(String(requirement.required_sme_count));

  const updateMutation = useMutation({
    mutationFn: (payload: Parameters<typeof updateProjectSkillRequirement>[1]) =>
      updateProjectSkillRequirement(requirement.id, payload),
    onSuccess: () => {
      onError(null);
      onChanged();
    },
    onError: (err: Error) => onError(err.message),
  });

  const removeMutation = useMutation({
    mutationFn: () => deleteProjectSkillRequirement(requirement.id),
    onSuccess: () => {
      onError(null);
      onChanged();
    },
    onError: (err: Error) => onError(err.message),
  });

  const busy = updateMutation.isPending || removeMutation.isPending;

  const commitHeadcount = () => {
    const next = Number(headcount);
    if (Number.isFinite(next) && next >= 0 && next !== requirement.required_headcount) {
      updateMutation.mutate({ required_headcount: next });
    } else {
      setHeadcount(String(requirement.required_headcount));
    }
  };

  const commitSme = () => {
    const next = Number(smeCount);
    if (Number.isFinite(next) && next >= 0 && next !== requirement.required_sme_count) {
      updateMutation.mutate({ required_sme_count: next });
    } else {
      setSmeCount(String(requirement.required_sme_count));
    }
  };

  return (
    <tr className="border-b border-border/50">
      <td className="py-1.5 pr-2 font-medium">{skillName}</td>
      <td className="py-1.5 pr-2">
        {canManage ? (
          <select
            value={requirement.required_proficiency_level}
            disabled={busy}
            onChange={(event) =>
              updateMutation.mutate({
                required_proficiency_level: event.target.value as ProficiencyLevel,
              })
            }
            className={selectClass}
          >
            {PROFICIENCY_LEVELS.map((level) => (
              <option key={level} value={level}>
                {titleize(level)}
              </option>
            ))}
          </select>
        ) : (
          titleize(requirement.required_proficiency_level)
        )}
      </td>
      <td className="py-1.5 pr-2">
        {canManage ? (
          <input
            type="number"
            min={0}
            value={headcount}
            disabled={busy}
            onChange={(event) => setHeadcount(event.target.value)}
            onBlur={commitHeadcount}
            className={numberClass}
          />
        ) : (
          requirement.required_headcount
        )}
      </td>
      <td className="py-1.5 pr-2">
        {canManage ? (
          <input
            type="number"
            min={0}
            value={smeCount}
            disabled={busy}
            onChange={(event) => setSmeCount(event.target.value)}
            onBlur={commitSme}
            className={numberClass}
          />
        ) : (
          requirement.required_sme_count
        )}
      </td>
      <td className="py-1.5 pr-2">
        {canManage ? (
          <select
            value={requirement.priority}
            disabled={busy}
            onChange={(event) =>
              updateMutation.mutate({
                priority: event.target.value as SkillRequirementPriority,
              })
            }
            className={selectClass}
          >
            {PRIORITIES.map((value) => (
              <option key={value} value={value}>
                {titleize(value)}
              </option>
            ))}
          </select>
        ) : (
          titleize(requirement.priority)
        )}
      </td>
      {canManage ? (
        <td className="py-1.5 pr-2 text-right">
          <button
            type="button"
            disabled={busy}
            onClick={() => removeMutation.mutate()}
            className={removeButtonClass}
          >
            Remove
          </button>
        </td>
      ) : null}
    </tr>
  );
}

export function UtilizationSnapshotsManager({
  projectId,
  teams,
  canManage,
}: {
  projectId: string;
  teams: TeamRead[];
  canManage: boolean;
}) {
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
                <SnapshotRow
                  key={snapshot.id}
                  snapshot={snapshot}
                  teamName={
                    snapshot.team_id
                      ? teamNameById.get(snapshot.team_id) ?? "Team"
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
              <option value="">
                {teams.length === 0 ? "No teams" : "Select team..."}
              </option>
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

function SnapshotRow({
  snapshot,
  teamName,
  canManage,
  onChanged,
  onError,
}: {
  snapshot: UtilizationSnapshotRead;
  teamName: string;
  canManage: boolean;
  onChanged: () => void;
  onError: (message: string | null) => void;
}) {
  const [allocated, setAllocated] = useState(String(snapshot.allocated_hours));
  const [available, setAvailable] = useState(String(snapshot.available_hours));

  const updateMutation = useMutation({
    mutationFn: (payload: Parameters<typeof updateUtilizationSnapshot>[1]) =>
      updateUtilizationSnapshot(snapshot.id, payload),
    onSuccess: () => {
      onError(null);
      onChanged();
    },
    onError: (err: Error) => onError(err.message),
  });

  const removeMutation = useMutation({
    mutationFn: () => deleteUtilizationSnapshot(snapshot.id),
    onSuccess: () => {
      onError(null);
      onChanged();
    },
    onError: (err: Error) => onError(err.message),
  });

  const busy = updateMutation.isPending || removeMutation.isPending;

  const commitAllocated = () => {
    const next = Number(allocated);
    if (Number.isFinite(next) && next >= 0 && next !== Number(snapshot.allocated_hours)) {
      updateMutation.mutate({ allocated_hours: next });
    } else {
      setAllocated(String(snapshot.allocated_hours));
    }
  };

  const commitAvailable = () => {
    const next = Number(available);
    if (Number.isFinite(next) && next >= 0 && next !== Number(snapshot.available_hours)) {
      updateMutation.mutate({ available_hours: next });
    } else {
      setAvailable(String(snapshot.available_hours));
    }
  };

  return (
    <tr className="border-b border-border/50">
      <td className="py-1.5 pr-2 font-medium">{teamName}</td>
      <td className="py-1.5 pr-2 text-muted-foreground whitespace-nowrap">
        {snapshot.snapshot_date}
      </td>
      <td className="py-1.5 pr-2">
        {canManage ? (
          <input
            type="number"
            min={0}
            step="0.5"
            value={allocated}
            disabled={busy}
            onChange={(event) => setAllocated(event.target.value)}
            onBlur={commitAllocated}
            className={numberClass}
          />
        ) : (
          String(snapshot.allocated_hours)
        )}
      </td>
      <td className="py-1.5 pr-2">
        {canManage ? (
          <input
            type="number"
            min={0}
            step="0.5"
            value={available}
            disabled={busy}
            onChange={(event) => setAvailable(event.target.value)}
            onBlur={commitAvailable}
            className={numberClass}
          />
        ) : (
          String(snapshot.available_hours)
        )}
      </td>
      <td className="py-1.5 pr-2 whitespace-nowrap">
        {Math.round(normalizeUtilizationPct(snapshot.utilization_pct))}%
      </td>
      {canManage ? (
        <td className="py-1.5 pr-2 text-right">
          <button
            type="button"
            disabled={busy}
            onClick={() => removeMutation.mutate()}
            className={removeButtonClass}
          >
            Remove
          </button>
        </td>
      ) : null}
    </tr>
  );
}
