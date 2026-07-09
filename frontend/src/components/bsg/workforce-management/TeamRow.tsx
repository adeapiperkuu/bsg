import { useState } from "react";
import { useMutation } from "@tanstack/react-query";

import { deleteTeam, updateTeam } from "@/lib/api";
import type { DeliverySite, TeamRead } from "@/types/workforce";

import {
  inputClass,
  removeButtonClass,
  selectClass,
  SITE_LABELS,
} from "./workforceManagementUtils";

const DELIVERY_SITES: DeliverySite[] = ["india", "kosovo"];

type TeamRowProps = {
  team: TeamRead;
  canManage: boolean;
  onChanged: () => void;
  onError: (message: string | null) => void;
};

export function TeamRow({ team, canManage, onChanged, onError }: TeamRowProps) {
  const [name, setName] = useState(team.name);
  const [domain, setDomain] = useState(team.domain);
  const [confirmRemove, setConfirmRemove] = useState(false);

  const updateMutation = useMutation({
    mutationFn: (payload: Parameters<typeof updateTeam>[1]) => updateTeam(team.id, payload),
    onSuccess: () => {
      onError(null);
      onChanged();
    },
    onError: (err: Error) => onError(err.message),
  });

  const removeMutation = useMutation({
    mutationFn: () => deleteTeam(team.id),
    onSuccess: () => {
      onError(null);
      setConfirmRemove(false);
      onChanged();
    },
    onError: (err: Error) => onError(err.message),
  });

  const busy = updateMutation.isPending || removeMutation.isPending;

  const commitName = () => {
    const trimmed = name.trim();
    if (trimmed && trimmed !== team.name) {
      updateMutation.mutate({ name: trimmed });
    } else {
      setName(team.name);
    }
  };

  const commitDomain = () => {
    const trimmed = domain.trim();
    if (trimmed && trimmed !== team.domain) {
      updateMutation.mutate({ domain: trimmed });
    } else {
      setDomain(team.domain);
    }
  };

  const handleRemoveClick = () => {
    if (!confirmRemove) {
      setConfirmRemove(true);
      return;
    }
    removeMutation.mutate();
  };

  return (
    <tr className="border-b border-border/50">
      <td className="py-1.5 pr-2">
        {canManage ? (
          <input
            type="text"
            value={name}
            disabled={busy}
            onChange={(event) => setName(event.target.value)}
            onBlur={commitName}
            className={inputClass}
          />
        ) : (
          <span className="font-medium">{team.name}</span>
        )}
      </td>
      <td className="py-1.5 pr-2">
        {canManage ? (
          <select
            value={team.site}
            disabled={busy}
            onChange={(event) =>
              updateMutation.mutate({ site: event.target.value as DeliverySite })
            }
            className={selectClass}
          >
            {DELIVERY_SITES.map((site) => (
              <option key={site} value={site}>
                {SITE_LABELS[site]}
              </option>
            ))}
          </select>
        ) : (
          SITE_LABELS[team.site]
        )}
      </td>
      <td className="py-1.5 pr-2">
        {canManage ? (
          <input
            type="text"
            value={domain}
            disabled={busy}
            onChange={(event) => setDomain(event.target.value)}
            onBlur={commitDomain}
            className={inputClass}
          />
        ) : (
          team.domain
        )}
      </td>
      <td className="py-1.5 pr-2">
        {canManage ? (
          <select
            value={team.is_active ? "active" : "inactive"}
            disabled={busy}
            onChange={(event) =>
              updateMutation.mutate({ is_active: event.target.value === "active" })
            }
            className={selectClass}
          >
            <option value="active">Active</option>
            <option value="inactive">Inactive</option>
          </select>
        ) : team.is_active ? (
          "Active"
        ) : (
          "Inactive"
        )}
      </td>
      {canManage ? (
        <td className="py-1.5 pr-2 text-right whitespace-nowrap">
          {confirmRemove ? (
            <div className="flex items-center justify-end gap-1">
              <button
                type="button"
                disabled={busy}
                onClick={handleRemoveClick}
                className={removeButtonClass}
              >
                {removeMutation.isPending ? "Removing..." : "Confirm"}
              </button>
              <button
                type="button"
                disabled={busy}
                onClick={() => setConfirmRemove(false)}
                className="rounded border border-border bg-elevated px-1.5 py-0.5 text-[10px] hover:bg-card disabled:opacity-50"
              >
                Cancel
              </button>
            </div>
          ) : (
            <button
              type="button"
              disabled={busy}
              onClick={handleRemoveClick}
              className={removeButtonClass}
            >
              Remove
            </button>
          )}
        </td>
      ) : null}
    </tr>
  );
}
