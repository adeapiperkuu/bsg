import { useMemo, useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";

import { StatusPill } from "@/components/bsg/widgets";
import { createTrainingRecord, deleteTrainingRecord, updateTrainingRecord } from "@/lib/api";
import { queryKeys } from "@/lib/queries/keys";
import {
  useAnnotatorTrainingRecordsQuery,
  useWorkforceTrainingProgramsQuery,
} from "@/lib/queries/workforce";
import type { TrainingRecordStatus } from "@/types/workforce";

import {
  addButtonClass,
  formatDate,
  removeButtonClass,
  selectClass,
  titleize,
  TRAINING_STATUSES,
  TRAINING_STATUS_PILL,
} from "./employeeProfileUtils";
import { ErrorText, SectionLabel } from "./EmployeeProfileShared";

type EmployeeTrainingSectionProps = {
  annotatorId: string;
  canManage: boolean;
  queriesEnabled: boolean;
};

export function EmployeeTrainingSection({
  annotatorId,
  canManage,
  queriesEnabled,
}: EmployeeTrainingSectionProps) {
  const queryClient = useQueryClient();
  const recordsQuery = useAnnotatorTrainingRecordsQuery(annotatorId, queriesEnabled);
  const catalogQuery = useWorkforceTrainingProgramsQuery(queriesEnabled);
  const [programId, setProgramId] = useState("");
  const [status, setStatus] = useState<TrainingRecordStatus>("not_started");
  const [error, setError] = useState<string | null>(null);

  const programNameById = useMemo(() => {
    const map = new Map<string, string>();
    for (const program of catalogQuery.data ?? []) map.set(program.id, program.name);
    return map;
  }, [catalogQuery.data]);

  const assigned = recordsQuery.data ?? [];
  const assignedIds = new Set(assigned.map((row) => row.training_program_id));
  const available = (catalogQuery.data ?? []).filter((program) => !assignedIds.has(program.id));

  const invalidate = () =>
    queryClient.invalidateQueries({
      queryKey: queryKeys.annotatorTrainingRecords(annotatorId),
    });

  const addMutation = useMutation({
    mutationFn: () => createTrainingRecord(annotatorId, { training_program_id: programId, status }),
    onSuccess: () => {
      setError(null);
      setProgramId("");
      setStatus("not_started");
      void invalidate();
    },
    onError: (err: Error) => setError(err.message),
  });

  const updateMutation = useMutation({
    mutationFn: (vars: { id: string; status: TrainingRecordStatus }) =>
      updateTrainingRecord(vars.id, { status: vars.status }),
    onSuccess: () => {
      setError(null);
      void invalidate();
    },
    onError: (err: Error) => setError(err.message),
  });

  const removeMutation = useMutation({
    mutationFn: (id: string) => deleteTrainingRecord(id),
    onSuccess: () => {
      setError(null);
      void invalidate();
    },
    onError: (err: Error) => setError(err.message),
  });

  const busy = addMutation.isPending || updateMutation.isPending || removeMutation.isPending;

  return (
    <div>
      <SectionLabel title="Training records" count={assigned.length} />
      {recordsQuery.isLoading ? (
        <div className="space-y-1.5">
          <div className="h-7 animate-pulse rounded bg-elevated" />
          <div className="h-7 animate-pulse rounded bg-elevated" />
        </div>
      ) : assigned.length === 0 ? (
        <p className="text-xs text-muted-foreground">No training records.</p>
      ) : (
        <ul className="space-y-1.5">
          {assigned.map((row) => (
            <li
              key={row.id}
              className="flex items-center justify-between gap-2 rounded border border-border bg-elevated px-2 py-1.5"
            >
              <div className="min-w-0">
                <div className="truncate text-[11px] font-medium text-foreground">
                  {programNameById.get(row.training_program_id) ?? "Training program"}
                </div>
                <div className="text-[10px] text-muted-foreground">
                  {row.completed_at ? `Completed ${formatDate(row.completed_at)}` : "Not completed"}
                </div>
              </div>
              <div className="flex items-center gap-2">
                {canManage ? (
                  <select
                    value={row.status}
                    disabled={busy}
                    onChange={(event) =>
                      updateMutation.mutate({
                        id: row.id,
                        status: event.target.value as TrainingRecordStatus,
                      })
                    }
                    className={selectClass}
                  >
                    {TRAINING_STATUSES.map((value) => (
                      <option key={value} value={value}>
                        {titleize(value)}
                      </option>
                    ))}
                  </select>
                ) : (
                  <StatusPill status={TRAINING_STATUS_PILL[row.status]} />
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
            value={programId}
            disabled={busy || available.length === 0}
            onChange={(event) => setProgramId(event.target.value)}
            className={selectClass}
          >
            <option value="">
              {available.length === 0 ? "No programs available" : "Select program..."}
            </option>
            {available.map((program) => (
              <option key={program.id} value={program.id}>
                {program.name}
              </option>
            ))}
          </select>
          <select
            value={status}
            disabled={busy}
            onChange={(event) => setStatus(event.target.value as TrainingRecordStatus)}
            className={selectClass}
          >
            {TRAINING_STATUSES.map((value) => (
              <option key={value} value={value}>
                {titleize(value)}
              </option>
            ))}
          </select>
          <button
            type="button"
            disabled={busy || !programId}
            onClick={() => addMutation.mutate()}
            className={addButtonClass}
          >
            {addMutation.isPending ? "Adding..." : "Add training"}
          </button>
        </div>
      ) : null}
      <ErrorText message={error} />
    </div>
  );
}
