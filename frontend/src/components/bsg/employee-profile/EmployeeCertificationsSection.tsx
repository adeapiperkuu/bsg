import { useMemo, useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";

import { StatusPill } from "@/components/bsg/widgets";
import {
  createEmployeeCertification,
  deleteEmployeeCertification,
  updateEmployeeCertification,
} from "@/lib/api";
import { queryKeys } from "@/lib/queries/keys";
import {
  useAnnotatorCertificationsQuery,
  useWorkforceCertificationsQuery,
} from "@/lib/queries/workforce";
import type { CertificationStatus } from "@/types/workforce";

import {
  addButtonClass,
  CERT_STATUSES,
  CERT_STATUS_PILL,
  formatDate,
  removeButtonClass,
  selectClass,
  titleize,
} from "./employeeProfileUtils";
import { ErrorText, SectionLabel } from "./EmployeeProfileShared";

type EmployeeCertificationsSectionProps = {
  annotatorId: string;
  canManage: boolean;
  queriesEnabled: boolean;
};

export function EmployeeCertificationsSection({
  annotatorId,
  canManage,
  queriesEnabled,
}: EmployeeCertificationsSectionProps) {
  const queryClient = useQueryClient();
  const certsQuery = useAnnotatorCertificationsQuery(annotatorId, queriesEnabled);
  const catalogQuery = useWorkforceCertificationsQuery(queriesEnabled);
  const [certificationId, setCertificationId] = useState("");
  const [status, setStatus] = useState<CertificationStatus>("active");
  const [error, setError] = useState<string | null>(null);

  const certNameById = useMemo(() => {
    const map = new Map<string, string>();
    for (const cert of catalogQuery.data ?? []) map.set(cert.id, cert.name);
    return map;
  }, [catalogQuery.data]);

  const assigned = certsQuery.data ?? [];
  const assignedIds = new Set(assigned.map((row) => row.certification_id));
  const available = (catalogQuery.data ?? []).filter((cert) => !assignedIds.has(cert.id));

  const invalidate = () =>
    queryClient.invalidateQueries({
      queryKey: queryKeys.annotatorCertifications(annotatorId),
    });

  const addMutation = useMutation({
    mutationFn: () =>
      createEmployeeCertification(annotatorId, { certification_id: certificationId, status }),
    onSuccess: () => {
      setError(null);
      setCertificationId("");
      setStatus("active");
      void invalidate();
    },
    onError: (err: Error) => setError(err.message),
  });

  const updateMutation = useMutation({
    mutationFn: (vars: { id: string; status: CertificationStatus }) =>
      updateEmployeeCertification(vars.id, { status: vars.status }),
    onSuccess: () => {
      setError(null);
      void invalidate();
    },
    onError: (err: Error) => setError(err.message),
  });

  const removeMutation = useMutation({
    mutationFn: (id: string) => deleteEmployeeCertification(id),
    onSuccess: () => {
      setError(null);
      void invalidate();
    },
    onError: (err: Error) => setError(err.message),
  });

  const busy = addMutation.isPending || updateMutation.isPending || removeMutation.isPending;

  return (
    <div>
      <SectionLabel title="Certifications" count={assigned.length} />
      {certsQuery.isLoading ? (
        <div className="space-y-1.5">
          <div className="h-7 animate-pulse rounded bg-elevated" />
          <div className="h-7 animate-pulse rounded bg-elevated" />
        </div>
      ) : assigned.length === 0 ? (
        <p className="text-xs text-muted-foreground">No certifications recorded.</p>
      ) : (
        <ul className="space-y-1.5">
          {assigned.map((row) => (
            <li
              key={row.id}
              className="flex items-center justify-between gap-2 rounded border border-border bg-elevated px-2 py-1.5"
            >
              <div className="min-w-0">
                <div className="truncate text-[11px] font-medium text-foreground">
                  {certNameById.get(row.certification_id) ?? "Certification"}
                </div>
                <div className="text-[10px] text-muted-foreground">
                  {row.expires_at ? `Expires ${formatDate(row.expires_at)}` : "No expiry"}
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
                        status: event.target.value as CertificationStatus,
                      })
                    }
                    className={selectClass}
                  >
                    {CERT_STATUSES.map((value) => (
                      <option key={value} value={value}>
                        {titleize(value)}
                      </option>
                    ))}
                  </select>
                ) : (
                  <StatusPill status={CERT_STATUS_PILL[row.status]} />
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
            value={certificationId}
            disabled={busy || available.length === 0}
            onChange={(event) => setCertificationId(event.target.value)}
            className={selectClass}
          >
            <option value="">
              {available.length === 0 ? "No certifications available" : "Select certification..."}
            </option>
            {available.map((cert) => (
              <option key={cert.id} value={cert.id}>
                {cert.name}
              </option>
            ))}
          </select>
          <select
            value={status}
            disabled={busy}
            onChange={(event) => setStatus(event.target.value as CertificationStatus)}
            className={selectClass}
          >
            {CERT_STATUSES.map((value) => (
              <option key={value} value={value}>
                {titleize(value)}
              </option>
            ))}
          </select>
          <button
            type="button"
            disabled={busy || !certificationId}
            onClick={() => addMutation.mutate()}
            className={addButtonClass}
          >
            {addMutation.isPending ? "Adding..." : "Add certification"}
          </button>
        </div>
      ) : null}
      <ErrorText message={error} />
    </div>
  );
}
