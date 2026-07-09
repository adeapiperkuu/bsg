import { useState } from "react";
import { useMutation } from "@tanstack/react-query";

import { deleteUtilizationSnapshot, updateUtilizationSnapshot } from "@/lib/api";
import { normalizeUtilizationPct } from "@/lib/queries/workforce";
import type { UtilizationSnapshotRead } from "@/types/workforce";

import { numberClass, removeButtonClass } from "./workforceManagementUtils";

type UtilizationSnapshotRowProps = {
  snapshot: UtilizationSnapshotRead;
  teamName: string;
  canManage: boolean;
  onChanged: () => void;
  onError: (message: string | null) => void;
};

export function UtilizationSnapshotRow({
  snapshot,
  teamName,
  canManage,
  onChanged,
  onError,
}: UtilizationSnapshotRowProps) {
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
