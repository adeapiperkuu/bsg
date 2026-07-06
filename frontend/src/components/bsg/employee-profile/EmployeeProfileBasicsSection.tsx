import { useEffect, useMemo, useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";

import { deleteAnnotator, updateAnnotator } from "@/lib/api";
import { queryKeys } from "@/lib/queries/keys";
import type {
  AnnotatorRead,
  AnnotatorUpdatePayload,
  DeliverySite,
  TeamRead,
} from "@/types/workforce";

import {
  addButtonClass,
  removeButtonClass,
  selectClass,
  SITE_LABELS,
} from "./employeeProfileUtils";
import { ErrorText, SectionLabel } from "./EmployeeProfileShared";

const DELIVERY_SITES: DeliverySite[] = ["india", "kosovo"];

type EmployeeProfileBasicsSectionProps = {
  annotator: AnnotatorRead;
  teams: TeamRead[];
  projectId: string;
  canManage: boolean;
  onAnnotatorUpdated: (annotator: AnnotatorRead) => void;
  onAnnotatorRemoved: () => void;
};

export function EmployeeProfileBasicsSection({
  annotator,
  teams,
  projectId,
  canManage,
  onAnnotatorUpdated,
  onAnnotatorRemoved,
}: EmployeeProfileBasicsSectionProps) {
  const queryClient = useQueryClient();
  const [fullName, setFullName] = useState(annotator.full_name);
  const [site, setSite] = useState<DeliverySite>(annotator.site);
  const [isSmeCertified, setIsSmeCertified] = useState(annotator.is_sme_certified);
  const [isActive, setIsActive] = useState(annotator.is_active);
  const [teamId, setTeamId] = useState(annotator.team_id);
  const [error, setError] = useState<string | null>(null);
  const [confirmRemove, setConfirmRemove] = useState(false);

  useEffect(() => {
    setFullName(annotator.full_name);
    setSite(annotator.site);
    setIsSmeCertified(annotator.is_sme_certified);
    setIsActive(annotator.is_active);
    setTeamId(annotator.team_id);
    setError(null);
    setConfirmRemove(false);
  }, [annotator]);

  const sortedTeams = useMemo(
    () => [...teams].sort((left, right) => left.name.localeCompare(right.name)),
    [teams],
  );

  const invalidate = (oldTeamId: string, newTeamId: string) => {
    void queryClient.invalidateQueries({
      queryKey: queryKeys.projectWorkforceSummary(projectId),
    });
    void queryClient.invalidateQueries({
      queryKey: queryKeys.teamAnnotators(oldTeamId),
    });
    if (newTeamId !== oldTeamId) {
      void queryClient.invalidateQueries({
        queryKey: queryKeys.teamAnnotators(newTeamId),
      });
    }
  };

  const buildPayload = (): AnnotatorUpdatePayload | null => {
    const trimmedName = fullName.trim();
    if (!trimmedName) return null;

    const payload: AnnotatorUpdatePayload = {};
    if (trimmedName !== annotator.full_name) payload.full_name = trimmedName;
    if (site !== annotator.site) payload.site = site;
    if (isSmeCertified !== annotator.is_sme_certified) payload.is_sme_certified = isSmeCertified;
    if (isActive !== annotator.is_active) payload.is_active = isActive;
    if (teamId !== annotator.team_id) payload.team_id = teamId;

    return Object.keys(payload).length > 0 ? payload : null;
  };

  const hasChanges = buildPayload() !== null;

  const saveMutation = useMutation({
    mutationFn: () => {
      const payload = buildPayload();
      if (!payload) {
        throw new Error("No changes to save.");
      }
      return updateAnnotator(annotator.id, payload);
    },
    onSuccess: (updated) => {
      setError(null);
      invalidate(annotator.team_id, updated.team_id);
      onAnnotatorUpdated(updated);
    },
    onError: (err: Error) => setError(err.message),
  });

  const removeMutation = useMutation({
    mutationFn: () => deleteAnnotator(annotator.id),
    onSuccess: () => {
      setError(null);
      void queryClient.invalidateQueries({
        queryKey: queryKeys.projectWorkforceSummary(projectId),
      });
      void queryClient.invalidateQueries({
        queryKey: queryKeys.teamAnnotators(annotator.team_id),
      });
      onAnnotatorRemoved();
    },
    onError: (err: Error) => setError(err.message),
  });

  if (!canManage || teams.length === 0) {
    return null;
  }

  const busy = saveMutation.isPending || removeMutation.isPending;
  const canSubmit = fullName.trim().length > 0 && hasChanges;

  const handleRemoveClick = () => {
    if (!confirmRemove) {
      setConfirmRemove(true);
      return;
    }
    removeMutation.mutate();
  };

  return (
    <div>
      <SectionLabel title="Profile basics" />
      <div className="space-y-2 rounded border border-border bg-elevated/40 p-3">
        <label className="flex flex-col gap-0.5 text-[10px] text-muted-foreground">
          Full name
          <input
            type="text"
            value={fullName}
            disabled={busy}
            onChange={(event) => setFullName(event.target.value)}
            className="rounded border border-border bg-card px-2 py-1 text-[11px] outline-none"
          />
        </label>
        <div className="grid grid-cols-2 gap-2">
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
          <label className="flex flex-col gap-0.5 text-[10px] text-muted-foreground">
            Team
            <select
              value={teamId}
              disabled={busy}
              onChange={(event) => setTeamId(event.target.value)}
              className={selectClass}
            >
              {sortedTeams.map((team) => (
                <option key={team.id} value={team.id}>
                  {team.name}
                </option>
              ))}
            </select>
          </label>
          <label className="flex flex-col gap-0.5 text-[10px] text-muted-foreground">
            SME status
            <select
              value={isSmeCertified ? "yes" : "no"}
              disabled={busy}
              onChange={(event) => setIsSmeCertified(event.target.value === "yes")}
              className={selectClass}
            >
              <option value="no">Not SME certified</option>
              <option value="yes">SME certified</option>
            </select>
          </label>
          <label className="flex flex-col gap-0.5 text-[10px] text-muted-foreground">
            Active status
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
        </div>
        <div className="flex flex-wrap items-center gap-2 pt-1">
          <button
            type="button"
            disabled={busy || !canSubmit}
            onClick={() => saveMutation.mutate()}
            className={addButtonClass}
          >
            {saveMutation.isPending ? "Saving..." : "Save changes"}
          </button>
          {hasChanges ? (
            <span className="text-[10px] text-muted-foreground">Unsaved changes</span>
          ) : null}
        </div>
        <ErrorText message={error} />
        <div className="border-t border-border/60 pt-3">
          <p className="mb-2 text-[10px] text-muted-foreground">
            Removing an annotator hides them from active Workforce lists. Use inactive status above
            to keep them visible but marked inactive.
          </p>
          {confirmRemove ? (
            <div className="flex flex-wrap items-center gap-2">
              <button
                type="button"
                disabled={busy}
                onClick={handleRemoveClick}
                className={removeButtonClass}
              >
                {removeMutation.isPending ? "Removing..." : "Confirm remove"}
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
              Remove annotator
            </button>
          )}
        </div>
      </div>
    </div>
  );
}
