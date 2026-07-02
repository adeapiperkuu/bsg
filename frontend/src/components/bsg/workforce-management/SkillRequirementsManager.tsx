import { useMemo, useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";

import { createProjectSkillRequirement } from "@/lib/api";
import { queryKeys } from "@/lib/queries/keys";
import { useProjectSkillRequirementsQuery, useWorkforceSkillsQuery } from "@/lib/queries/workforce";
import type { ProficiencyLevel, SkillRequirementPriority } from "@/types/workforce";

import { SkillRequirementRow } from "./SkillRequirementRow";
import { ErrorText } from "./WorkforceManagementShared";
import {
  addButtonClass,
  numberClass,
  PRIORITIES,
  PROFICIENCY_LEVELS,
  selectClass,
  titleize,
} from "./workforceManagementUtils";

type SkillRequirementsManagerProps = {
  projectId: string;
  canManage: boolean;
};

export function SkillRequirementsManager({ projectId, canManage }: SkillRequirementsManagerProps) {
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
                <SkillRequirementRow
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
