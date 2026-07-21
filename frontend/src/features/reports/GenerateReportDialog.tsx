import { useEffect, useId, useMemo, useRef, useState } from "react";
import { useQuery } from "@tanstack/react-query";

import { ApiError } from "@/lib/api";
import {
  organisationsQueryOptions,
  programsQueryOptions,
  projectsQueryOptions,
} from "@/lib/queries/delivery";
import type { CommunicationType } from "@/types/communications";

export const REPORT_INSTRUCTIONS_MAX_CHARS = 2000;

export type ReportTypeOption = {
  value: CommunicationType;
  label: string;
  subjectPrefix: string;
};

export const REPORT_TYPE_OPTIONS: ReportTypeOption[] = [
  {
    value: "weekly_summary",
    label: "Weekly Status",
    subjectPrefix: "Weekly Delivery Summary",
  },
  {
    value: "executive_summary",
    label: "Executive Summary",
    subjectPrefix: "Executive Summary",
  },
  {
    value: "ad_hoc",
    label: "Ad hoc Update",
    subjectPrefix: "Project Update",
  },
];

export function suggestReportSubject(
  projectName: string | undefined,
  reportType: CommunicationType,
): string {
  const option = REPORT_TYPE_OPTIONS.find((o) => o.value === reportType);
  const prefix = option?.subjectPrefix ?? "Project Update";
  const name = projectName?.trim() || "Project";
  return `${prefix} — ${name}`;
}

export interface GenerateReportFormValues {
  projectId: string;
  projectName: string;
  orgId: string;
  orgName: string;
  programId?: string;
  programName?: string;
  commType: CommunicationType;
  subject: string;
  instructions: string;
}

export interface GenerateReportDialogProps {
  open: boolean;
  onClose: () => void;
  onGenerate: (values: GenerateReportFormValues) => Promise<void>;
  isPending?: boolean;
  canGenerate?: boolean;
  initialProjectId?: string | null;
  initialCommType?: CommunicationType | null;
}

/**
 * Generate Report — Client → Project → Scope cascade.
 * Scope maps to API `projects` (where communications attach).
 */
export function GenerateReportDialog({
  open,
  onClose,
  onGenerate,
  isPending = false,
  canGenerate = true,
  initialProjectId = null,
  initialCommType = null,
}: GenerateReportDialogProps) {
  const titleId = useId();
  const firstFieldRef = useRef<HTMLSelectElement>(null);
  const [orgId, setOrgId] = useState("");
  const [programId, setProgramId] = useState("");
  const [projectId, setProjectId] = useState("");
  const [commType, setCommType] = useState<CommunicationType>("weekly_summary");
  const [subject, setSubject] = useState("");
  const [instructions, setInstructions] = useState("");
  const [subjectTouched, setSubjectTouched] = useState(false);
  const [fieldErrors, setFieldErrors] = useState<{
    orgId?: string;
    programId?: string;
    projectId?: string;
    subject?: string;
    instructions?: string;
  }>({});
  const [formError, setFormError] = useState<string | null>(null);
  const [excludedProjectIds, setExcludedProjectIds] = useState<string[]>([]);
  const wasOpen = useRef(false);

  const organisationsQuery = useQuery({ ...organisationsQueryOptions, enabled: open });
  const programsQuery = useQuery({ ...programsQueryOptions, enabled: open });
  const projectsQuery = useQuery({ ...projectsQueryOptions, enabled: open });

  const allScopes = useMemo(
    () => (projectsQuery.data ?? []).filter((p) => !excludedProjectIds.includes(p.id)),
    [projectsQuery.data, excludedProjectIds],
  );
  const allPrograms = programsQuery.data ?? [];

  const clients = useMemo(() => {
    const orgs = organisationsQuery.data ?? [];
    const orgIds = new Set(allScopes.map((p) => p.org_id));
    return orgs.filter((org) => orgIds.has(org.id));
  }, [organisationsQuery.data, allScopes]);

  const programsForClient = useMemo(() => {
    if (!orgId) return [];
    const programIdsWithScopes = new Set(
      allScopes.filter((s) => s.org_id === orgId && s.program_id).map((s) => s.program_id!),
    );
    return allPrograms.filter(
      (p) => p.org_id === orgId && (programIdsWithScopes.has(p.id) || p.scope_count > 0),
    );
  }, [allPrograms, allScopes, orgId]);

  const scopesForProgram = useMemo(() => {
    if (!orgId) return [];
    if (programId) {
      return allScopes.filter((s) => s.org_id === orgId && s.program_id === programId);
    }
    // Ungrouped scopes for this client
    return allScopes.filter((s) => s.org_id === orgId && !s.program_id);
  }, [allScopes, orgId, programId]);

  const selectedScope = scopesForProgram.find((p) => p.id === projectId);
  const selectedClient = clients.find((org) => org.id === orgId);
  const selectedProgram = programsForClient.find((p) => p.id === programId);
  const listsLoading =
    organisationsQuery.isLoading || programsQuery.isLoading || projectsQuery.isLoading;
  const listsError =
    organisationsQuery.isError || programsQuery.isError || projectsQuery.isError;

  useEffect(() => {
    if (open && !wasOpen.current) {
      setOrgId("");
      setProgramId("");
      setProjectId(initialProjectId ?? "");
      setCommType(initialCommType ?? "weekly_summary");
      setSubject("");
      setInstructions("");
      setSubjectTouched(false);
      setFieldErrors({});
      setFormError(null);
      setExcludedProjectIds([]);
      queueMicrotask(() => firstFieldRef.current?.focus());
    }
    wasOpen.current = open;
  }, [open, initialProjectId, initialCommType]);

  useEffect(() => {
    if (!open || listsLoading) return;

    if (projectId && (!orgId || !programId)) {
      const match = allScopes.find((p) => p.id === projectId);
      if (match) {
        if (!orgId) setOrgId(match.org_id);
        if (!programId && match.program_id) setProgramId(match.program_id);
        return;
      }
    }

    if (!orgId && clients.length === 1) {
      setOrgId(clients[0].id);
    }
  }, [open, listsLoading, projectId, orgId, programId, allScopes, clients]);

  useEffect(() => {
    if (!open || !orgId) return;
    if (programId && !programsForClient.some((p) => p.id === programId)) {
      setProgramId("");
      setProjectId("");
    }
  }, [open, orgId, programId, programsForClient]);

  useEffect(() => {
    if (!open || !projectId) return;
    const stillValid = scopesForProgram.some((p) => p.id === projectId);
    if (!stillValid) setProjectId("");
  }, [open, projectId, scopesForProgram]);

  useEffect(() => {
    if (!open || subjectTouched) return;
    setSubject(suggestReportSubject(selectedScope?.name, commType));
  }, [open, selectedScope?.name, commType, subjectTouched]);

  if (!open) return null;

  function validate(): boolean {
    const next: typeof fieldErrors = {};
    if (!orgId) next.orgId = "Select a client.";
    if (programsForClient.length > 0 && !programId) next.programId = "Select a project.";
    if (!projectId) next.projectId = "Select a scope.";
    if (!subject.trim()) next.subject = "Subject is required.";
    if (instructions.length > REPORT_INSTRUCTIONS_MAX_CHARS) {
      next.instructions = `Instructions must be ${REPORT_INSTRUCTIONS_MAX_CHARS} characters or fewer.`;
    }
    setFieldErrors(next);
    return Object.keys(next).length === 0;
  }

  async function handleSubmit() {
    if (!canGenerate) {
      setFormError("You do not have permission to generate reports.");
      return;
    }
    if (isPending) return;
    if (!validate()) return;
    if (!selectedScope) {
      setFieldErrors((prev) => ({ ...prev, projectId: "Select a visible scope." }));
      return;
    }

    setFormError(null);
    try {
      await onGenerate({
        projectId: selectedScope.id,
        projectName: selectedScope.name,
        orgId: selectedClient?.id ?? selectedScope.org_id,
        orgName: selectedClient?.name ?? "",
        programId: selectedProgram?.id,
        programName: selectedProgram?.name,
        commType,
        subject: subject.trim(),
        instructions: instructions.trim(),
      });
    } catch (err) {
      if (err instanceof ApiError) {
        if (err.status === 409 && err.code === "EVIDENCE_REQUIRED") {
          setFormError("Scope needs delivery data before a report can be generated.");
          return;
        }
        if (err.status === 403) {
          setFormError("You do not have permission to generate reports for this scope.");
          return;
        }
        if (err.status === 404) {
          setExcludedProjectIds((ids) => [...ids, projectId]);
          setProjectId("");
          setFormError("That scope is no longer available. Choose another scope.");
          return;
        }
        if (err.status === 503) {
          setFormError("Report generation is temporarily unavailable. Please try again.");
          return;
        }
        if (err.status === 422) {
          setFormError(err.message || "Check the form fields and try again.");
          return;
        }
        setFormError(err.message || "Failed to generate report.");
        return;
      }
      setFormError(err instanceof Error ? err.message : "Failed to generate report.");
    }
  }

  function retryLists() {
    void organisationsQuery.refetch();
    void programsQuery.refetch();
    void projectsQuery.refetch();
  }

  return (
    <div
      className="fixed inset-0 z-40 grid place-items-center bg-background/70 backdrop-blur-sm"
      onClick={() => {
        if (!isPending) onClose();
      }}
      role="presentation"
    >
      <div
        className="w-full max-w-md rounded-lg border border-border bg-card p-5"
        onClick={(e) => e.stopPropagation()}
        role="dialog"
        aria-labelledby={titleId}
        aria-busy={isPending}
      >
        <h3 id={titleId} className="text-sm font-semibold">
          Generate Report
        </h3>
        <p className="mt-1 text-[11px] text-muted-foreground">
          Pick client → project → scope, then generate an AI-assisted draft.
        </p>

        {!canGenerate ? (
          <p className="mt-3 text-xs text-[color:var(--danger)]" role="alert">
            You do not have permission to generate reports.
          </p>
        ) : null}

        <div className="mt-3 space-y-3 text-xs">
          <label className="block">
            <span className="text-muted-foreground">Client</span>
            <select
              ref={firstFieldRef}
              className="mt-1 w-full rounded border border-border bg-elevated px-2 py-1.5"
              value={orgId}
              disabled={isPending || !canGenerate || listsLoading}
              onChange={(e) => {
                setOrgId(e.target.value);
                setProgramId("");
                setProjectId("");
                setFieldErrors((prev) => ({
                  ...prev,
                  orgId: undefined,
                  programId: undefined,
                  projectId: undefined,
                }));
              }}
            >
              <option value="">{listsLoading ? "Loading clients…" : "Select a client"}</option>
              {clients.map((org) => (
                <option key={org.id} value={org.id}>
                  {org.name}
                </option>
              ))}
            </select>
            {fieldErrors.orgId ? (
              <p className="mt-1 text-[color:var(--danger)]">{fieldErrors.orgId}</p>
            ) : null}
          </label>

          <label className="block">
            <span className="text-muted-foreground">Project</span>
            <select
              className="mt-1 w-full rounded border border-border bg-elevated px-2 py-1.5"
              value={programId}
              disabled={isPending || !canGenerate || listsLoading || !orgId}
              onChange={(e) => {
                setProgramId(e.target.value);
                setProjectId("");
                setFieldErrors((prev) => ({
                  ...prev,
                  programId: undefined,
                  projectId: undefined,
                }));
              }}
            >
              <option value="">
                {!orgId
                  ? "Select a client first"
                  : listsLoading
                    ? "Loading projects…"
                    : programsForClient.length === 0
                      ? "No projects — use ungrouped scopes"
                      : "Select a project"}
              </option>
              {programsForClient.map((p) => (
                <option key={p.id} value={p.id}>
                  {p.name}
                </option>
              ))}
            </select>
            {fieldErrors.programId ? (
              <p className="mt-1 text-[color:var(--danger)]">{fieldErrors.programId}</p>
            ) : null}
          </label>

          <label className="block">
            <span className="text-muted-foreground">Scope</span>
            <select
              className="mt-1 w-full rounded border border-border bg-elevated px-2 py-1.5"
              value={projectId}
              disabled={
                isPending ||
                !canGenerate ||
                listsLoading ||
                !orgId ||
                (programsForClient.length > 0 && !programId)
              }
              onChange={(e) => {
                setProjectId(e.target.value);
                setFieldErrors((prev) => ({ ...prev, projectId: undefined }));
              }}
            >
              <option value="">
                {!orgId
                  ? "Select a client first"
                  : programsForClient.length > 0 && !programId
                    ? "Select a project first"
                    : listsLoading
                      ? "Loading scopes…"
                      : scopesForProgram.length === 0
                        ? "No scopes available"
                        : "Select a scope"}
              </option>
              {scopesForProgram.map((p) => (
                <option key={p.id} value={p.id}>
                  {p.name}
                </option>
              ))}
            </select>
            {listsError ? (
              <p className="mt-1 text-[color:var(--danger)]">
                Failed to load options.{" "}
                <button type="button" className="underline" onClick={retryLists}>
                  Retry
                </button>
              </p>
            ) : null}
            {fieldErrors.projectId ? (
              <p className="mt-1 text-[color:var(--danger)]">{fieldErrors.projectId}</p>
            ) : null}
          </label>

          <label className="block">
            <span className="text-muted-foreground">Report type</span>
            <select
              className="mt-1 w-full rounded border border-border bg-elevated px-2 py-1.5"
              value={commType}
              disabled={isPending || !canGenerate}
              onChange={(e) => setCommType(e.target.value as CommunicationType)}
            >
              {REPORT_TYPE_OPTIONS.map((opt) => (
                <option key={opt.value} value={opt.value}>
                  {opt.label}
                </option>
              ))}
            </select>
          </label>

          <label className="block">
            <span className="text-muted-foreground">Subject</span>
            <input
              type="text"
              className="mt-1 w-full rounded border border-border bg-elevated px-2 py-1.5"
              value={subject}
              disabled={isPending || !canGenerate}
              maxLength={500}
              onChange={(e) => {
                setSubjectTouched(true);
                setSubject(e.target.value);
                setFieldErrors((prev) => ({ ...prev, subject: undefined }));
              }}
            />
            {fieldErrors.subject ? (
              <p className="mt-1 text-[color:var(--danger)]">{fieldErrors.subject}</p>
            ) : null}
          </label>

          <label className="block">
            <span className="text-muted-foreground">
              Instructions <span className="opacity-70">(optional)</span>
            </span>
            <textarea
              className="mt-1 min-h-[72px] w-full rounded border border-border bg-elevated px-2 py-1.5"
              value={instructions}
              disabled={isPending || !canGenerate}
              maxLength={REPORT_INSTRUCTIONS_MAX_CHARS}
              placeholder="Emphasize the delayed milestone and the recovery plan."
              onChange={(e) => {
                setInstructions(e.target.value);
                setFieldErrors((prev) => ({ ...prev, instructions: undefined }));
              }}
            />
            <span className="mt-0.5 block text-[10px] text-muted-foreground">
              {instructions.length}/{REPORT_INSTRUCTIONS_MAX_CHARS}
            </span>
            {fieldErrors.instructions ? (
              <p className="mt-1 text-[color:var(--danger)]">{fieldErrors.instructions}</p>
            ) : null}
          </label>

          {formError ? (
            <p className="text-[color:var(--danger)]" role="alert">
              {formError}
            </p>
          ) : null}
          {isPending ? (
            <p className="text-muted-foreground" data-testid="generate-pending">
              Generating draft…
            </p>
          ) : null}
        </div>

        <div className="mt-4 flex justify-end gap-2">
          <button
            type="button"
            onClick={onClose}
            disabled={isPending}
            className="rounded border border-border px-3 py-1.5 text-xs disabled:opacity-50"
          >
            Cancel
          </button>
          <button
            type="button"
            onClick={() => void handleSubmit()}
            disabled={isPending || !canGenerate}
            className="rounded bg-[color:var(--brand)] px-3 py-1.5 text-xs font-medium text-[color:var(--brand-foreground)] disabled:opacity-50"
          >
            {isPending ? "Generating…" : "Generate"}
          </button>
        </div>
      </div>
    </div>
  );
}
