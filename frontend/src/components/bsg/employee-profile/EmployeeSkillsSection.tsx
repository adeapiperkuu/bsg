import { useMemo, useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";

import { createAnnotatorSkill, deleteAnnotatorSkill, updateAnnotatorSkill } from "@/lib/api";
import { queryKeys } from "@/lib/queries/keys";
import { useAnnotatorSkillsQuery, useWorkforceSkillsQuery } from "@/lib/queries/workforce";
import type { ProficiencyLevel } from "@/types/workforce";

import {
  addButtonClass,
  PROFICIENCY_LEVELS,
  removeButtonClass,
  selectClass,
  titleize,
} from "./employeeProfileUtils";
import { ErrorText, SectionLabel } from "./EmployeeProfileShared";

type EmployeeSkillsSectionProps = {
  annotatorId: string;
  canManage: boolean;
  queriesEnabled: boolean;
};

export function EmployeeSkillsSection({
  annotatorId,
  canManage,
  queriesEnabled,
}: EmployeeSkillsSectionProps) {
  const queryClient = useQueryClient();
  const skillsQuery = useAnnotatorSkillsQuery(annotatorId, queriesEnabled);
  const catalogQuery = useWorkforceSkillsQuery(queriesEnabled);
  const [skillId, setSkillId] = useState("");
  const [proficiency, setProficiency] = useState<ProficiencyLevel>("beginner");
  const [error, setError] = useState<string | null>(null);

  const skillNameById = useMemo(() => {
    const map = new Map<string, string>();
    for (const skill of catalogQuery.data ?? []) map.set(skill.id, skill.name);
    return map;
  }, [catalogQuery.data]);

  const assigned = skillsQuery.data ?? [];
  const assignedIds = new Set(assigned.map((row) => row.skill_id));
  const available = (catalogQuery.data ?? []).filter((skill) => !assignedIds.has(skill.id));

  const invalidate = () =>
    queryClient.invalidateQueries({ queryKey: queryKeys.annotatorSkills(annotatorId) });

  const addMutation = useMutation({
    mutationFn: () =>
      createAnnotatorSkill(annotatorId, { skill_id: skillId, proficiency_level: proficiency }),
    onSuccess: () => {
      setError(null);
      setSkillId("");
      setProficiency("beginner");
      void invalidate();
    },
    onError: (err: Error) => setError(err.message),
  });

  const updateMutation = useMutation({
    mutationFn: (vars: { id: string; level: ProficiencyLevel }) =>
      updateAnnotatorSkill(vars.id, { proficiency_level: vars.level }),
    onSuccess: () => {
      setError(null);
      void invalidate();
    },
    onError: (err: Error) => setError(err.message),
  });

  const removeMutation = useMutation({
    mutationFn: (id: string) => deleteAnnotatorSkill(id),
    onSuccess: () => {
      setError(null);
      void invalidate();
    },
    onError: (err: Error) => setError(err.message),
  });

  const busy = addMutation.isPending || updateMutation.isPending || removeMutation.isPending;

  return (
    <div>
      <SectionLabel title="Skills" count={assigned.length} />
      {skillsQuery.isLoading ? (
        <div className="space-y-1.5">
          <div className="h-7 animate-pulse rounded bg-elevated" />
          <div className="h-7 animate-pulse rounded bg-elevated" />
        </div>
      ) : assigned.length === 0 ? (
        <p className="text-xs text-muted-foreground">No skills assigned.</p>
      ) : (
        <ul className="space-y-1.5">
          {assigned.map((row) => (
            <li
              key={row.id}
              className="flex items-center justify-between gap-2 rounded border border-border bg-elevated px-2 py-1.5"
            >
              <span className="text-[11px] font-medium text-foreground">
                {skillNameById.get(row.skill_id) ?? "Skill"}
              </span>
              <div className="flex items-center gap-2">
                {canManage ? (
                  <select
                    value={row.proficiency_level}
                    disabled={busy}
                    onChange={(event) =>
                      updateMutation.mutate({
                        id: row.id,
                        level: event.target.value as ProficiencyLevel,
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
                  <span className="text-[11px] text-muted-foreground">
                    {titleize(row.proficiency_level)}
                  </span>
                )}
                {canManage ? (
                  <button
                    type="button"
                    disabled={busy}
                    onClick={() => removeMutation.mutate(row.id)}
                    className={removeButtonClass}
                  >
                    Remove
                  </button>
                ) : null}
              </div>
            </li>
          ))}
        </ul>
      )}

      {canManage ? (
        <div className="mt-2 flex flex-wrap items-center gap-2">
          <select
            value={skillId}
            disabled={busy || available.length === 0}
            onChange={(event) => setSkillId(event.target.value)}
            className={selectClass}
          >
            <option value="">
              {available.length === 0 ? "No skills available" : "Select skill..."}
            </option>
            {available.map((skill) => (
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
          <button
            type="button"
            disabled={busy || !skillId}
            onClick={() => addMutation.mutate()}
            className={addButtonClass}
          >
            {addMutation.isPending ? "Adding..." : "Add skill"}
          </button>
        </div>
      ) : null}
      <ErrorText message={error} />
    </div>
  );
}
