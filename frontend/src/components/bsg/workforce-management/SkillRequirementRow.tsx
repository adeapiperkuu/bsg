import { useState } from "react";
import { useMutation } from "@tanstack/react-query";

import { deleteProjectSkillRequirement, updateProjectSkillRequirement } from "@/lib/api";
import type {
  ProficiencyLevel,
  ProjectSkillRequirementRead,
  SkillRequirementPriority,
} from "@/types/workforce";

import {
  numberClass,
  PRIORITIES,
  PROFICIENCY_LEVELS,
  removeButtonClass,
  selectClass,
  titleize,
} from "./workforceManagementUtils";

type SkillRequirementRowProps = {
  requirement: ProjectSkillRequirementRead;
  skillName: string;
  canManage: boolean;
  onChanged: () => void;
  onError: (message: string | null) => void;
};

export function SkillRequirementRow({
  requirement,
  skillName,
  canManage,
  onChanged,
  onError,
}: SkillRequirementRowProps) {
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
