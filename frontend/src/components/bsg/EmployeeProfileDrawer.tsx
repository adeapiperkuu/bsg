import { useMemo, useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";

import { StatusPill } from "@/components/bsg/widgets";
import {
  Sheet,
  SheetContent,
  SheetDescription,
  SheetHeader,
  SheetTitle,
} from "@/components/ui/sheet";
import {
  createAnnotatorSkill,
  createEmployeeCertification,
  createTrainingRecord,
  deleteAnnotatorSkill,
  deleteEmployeeCertification,
  deleteTrainingRecord,
  updateAnnotatorSkill,
  updateEmployeeCertification,
  updateTrainingRecord,
} from "@/lib/api";
import { queryKeys } from "@/lib/queries/keys";
import {
  normalizeUtilizationPct,
  useAnnotatorCertificationsQuery,
  useAnnotatorSkillsQuery,
  useAnnotatorTrainingRecordsQuery,
  useProjectUtilizationQuery,
  useWorkforceCertificationsQuery,
  useWorkforceSkillsQuery,
  useWorkforceTrainingProgramsQuery,
} from "@/lib/queries/workforce";
import { cn } from "@/lib/utils";
import type {
  AnnotatorRead,
  CertificationStatus,
  DeliverySite,
  ProficiencyLevel,
  TeamRead,
  TrainingRecordStatus,
} from "@/types/workforce";

const SITE_LABELS: Record<DeliverySite, string> = {
  india: "India",
  kosovo: "Kosovo",
};

const PROFICIENCY_LEVELS: ProficiencyLevel[] = [
  "beginner",
  "intermediate",
  "advanced",
  "expert",
];

const CERT_STATUSES: CertificationStatus[] = [
  "active",
  "expired",
  "pending_review",
  "revoked",
];

const TRAINING_STATUSES: TrainingRecordStatus[] = [
  "not_started",
  "in_progress",
  "completed",
  "failed",
  "expired",
];

const CERT_STATUS_PILL: Record<CertificationStatus, string> = {
  active: "Active",
  expired: "Expired",
  pending_review: "Pending",
  revoked: "Cancelled",
};

const TRAINING_STATUS_PILL: Record<TrainingRecordStatus, string> = {
  not_started: "Draft",
  in_progress: "In Progress",
  completed: "Completed",
  failed: "High",
  expired: "Warning",
};

function titleize(value: string): string {
  return value
    .split("_")
    .map((word) => word.charAt(0).toUpperCase() + word.slice(1))
    .join(" ");
}

function formatDate(value: string | null): string {
  if (!value) return "-";
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) return value;
  return parsed.toLocaleDateString(undefined, {
    month: "short",
    day: "numeric",
    year: "numeric",
  });
}

const selectClass =
  "rounded border border-border bg-card px-2 py-1 text-[11px] outline-none";
const addButtonClass =
  "rounded border border-[color:var(--brand)]/30 bg-[color:var(--brand)]/10 px-2.5 py-1 text-[11px] font-medium text-[color:var(--brand)] hover:bg-[color:var(--brand)]/20 disabled:opacity-50";
const removeButtonClass =
  "rounded border border-border bg-elevated px-1.5 py-0.5 text-[10px] text-[color:var(--danger)] hover:bg-card disabled:opacity-50";

function SectionLabel({ title, count }: { title: string; count?: number }) {
  return (
    <div className="mb-2 flex items-center gap-2">
      <h4 className="text-xs font-semibold uppercase tracking-wider text-muted-foreground">
        {title}
      </h4>
      {count !== undefined && count > 0 ? (
        <span className="rounded bg-secondary px-1.5 py-0.5 text-[10px] font-medium text-foreground">
          {count}
        </span>
      ) : null}
    </div>
  );
}

function ErrorText({ message }: { message: string | null }) {
  if (!message) return null;
  return <p className="mt-1 text-[11px] text-[color:var(--danger)]">{message}</p>;
}

export function EmployeeProfileDrawer({
  open,
  onOpenChange,
  annotator,
  team,
  projectId,
  canManage,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  annotator: AnnotatorRead | null;
  team: TeamRead | undefined;
  projectId: string | null;
  canManage: boolean;
}) {
  return (
    <Sheet open={open} onOpenChange={onOpenChange}>
      <SheetContent side="right" className="w-full overflow-y-auto sm:max-w-lg">
        {annotator ? (
          <EmployeeProfileBody
            annotator={annotator}
            team={team}
            projectId={projectId}
            canManage={canManage}
          />
        ) : null}
      </SheetContent>
    </Sheet>
  );
}

function EmployeeProfileBody({
  annotator,
  team,
  projectId,
  canManage,
}: {
  annotator: AnnotatorRead;
  team: TeamRead | undefined;
  projectId: string | null;
  canManage: boolean;
}) {
  return (
    <div className="space-y-6 pr-2">
      <SheetHeader className="space-y-1 text-left">
        <SheetTitle>{annotator.full_name}</SheetTitle>
        <SheetDescription>
          {team ? team.name : "Unassigned team"} / {SITE_LABELS[annotator.site]}
        </SheetDescription>
      </SheetHeader>

      <div className="flex flex-wrap gap-2">
        <StatusPill status={annotator.is_active ? "Active" : "Warning"} />
        <StatusPill status={annotator.is_sme_certified ? "Approved" : "Draft"} />
        {team?.domain ? (
          <span className="inline-flex items-center rounded-full border border-border bg-secondary px-2 py-0.5 text-[10px] font-medium text-muted-foreground">
            {team.domain}
          </span>
        ) : null}
      </div>

      <dl className="grid grid-cols-2 gap-x-4 gap-y-2 text-[11px]">
        <div className="flex flex-col">
          <dt className="text-muted-foreground">SME status</dt>
          <dd className="font-medium">
            {annotator.is_sme_certified ? "SME certified" : "Not SME certified"}
          </dd>
        </div>
        <div className="flex flex-col">
          <dt className="text-muted-foreground">Active status</dt>
          <dd className="font-medium">{annotator.is_active ? "Active" : "Inactive"}</dd>
        </div>
        <div className="flex flex-col">
          <dt className="text-muted-foreground">Site</dt>
          <dd className="font-medium">{SITE_LABELS[annotator.site]}</dd>
        </div>
        <div className="flex flex-col">
          <dt className="text-muted-foreground">Domain</dt>
          <dd className="font-medium">{team?.domain ?? "-"}</dd>
        </div>
      </dl>

      <LatestUtilization annotatorId={annotator.id} projectId={projectId} />

      <SkillsSection annotatorId={annotator.id} canManage={canManage} />
      <CertificationsSection annotatorId={annotator.id} canManage={canManage} />
      <TrainingSection annotatorId={annotator.id} canManage={canManage} />

      {!canManage ? (
        <p className="text-[11px] text-muted-foreground">
          You have read-only access to employee details.
        </p>
      ) : null}
    </div>
  );
}

function LatestUtilization({
  annotatorId,
  projectId,
}: {
  annotatorId: string;
  projectId: string | null;
}) {
  const query = useProjectUtilizationQuery(projectId, true, {
    annotator_id: annotatorId,
    limit: 5,
  });
  const latest = useMemo(() => {
    const rows = query.data ?? [];
    if (rows.length === 0) return null;
    return [...rows].sort((left, right) =>
      right.snapshot_date.localeCompare(left.snapshot_date),
    )[0];
  }, [query.data]);

  return (
    <div>
      <SectionLabel title="Latest utilization" />
      {query.isLoading ? (
        <div className="h-6 w-32 animate-pulse rounded bg-elevated" />
      ) : latest ? (
        <p className="text-xs text-foreground">
          {Math.round(normalizeUtilizationPct(latest.utilization_pct))}% on{" "}
          {formatDate(latest.snapshot_date)}
        </p>
      ) : (
        <p className="text-xs text-muted-foreground">
          No utilization snapshots for this employee.
        </p>
      )}
    </div>
  );
}

function SkillsSection({
  annotatorId,
  canManage,
}: {
  annotatorId: string;
  canManage: boolean;
}) {
  const queryClient = useQueryClient();
  const skillsQuery = useAnnotatorSkillsQuery(annotatorId, true);
  const catalogQuery = useWorkforceSkillsQuery(true);
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

function CertificationsSection({
  annotatorId,
  canManage,
}: {
  annotatorId: string;
  canManage: boolean;
}) {
  const queryClient = useQueryClient();
  const certsQuery = useAnnotatorCertificationsQuery(annotatorId, true);
  const catalogQuery = useWorkforceCertificationsQuery(true);
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

function TrainingSection({
  annotatorId,
  canManage,
}: {
  annotatorId: string;
  canManage: boolean;
}) {
  const queryClient = useQueryClient();
  const recordsQuery = useAnnotatorTrainingRecordsQuery(annotatorId, true);
  const catalogQuery = useWorkforceTrainingProgramsQuery(true);
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
    mutationFn: () =>
      createTrainingRecord(annotatorId, { training_program_id: programId, status }),
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
