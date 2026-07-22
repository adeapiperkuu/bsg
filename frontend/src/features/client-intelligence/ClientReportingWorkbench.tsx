import { useEffect, useMemo, useState } from "react";
import { Download, Eye, FileText, Loader2, Sparkles } from "lucide-react";

import { StatusPill } from "@/components/bsg/widgets";
import { DeliveryMarkdown } from "@/components/delivery/delivery-markdown";
import { Button } from "@/components/ui/button";
import { ApiError } from "@/lib/api";
import {
  useClientIntelligenceDashboardQuery,
  useClientReportApprovalsQuery,
  useClientReportDeliveriesQuery,
  useClientReportPackagesQuery,
  useClientReportSchedulesQuery,
  useDraftClientReportPackageMutation,
  useExportClientReportPackageMutation,
  useRunDueClientReportSchedulesMutation,
  useTransitionClientReportGovernanceMutation,
  useUpdateClientReportScheduleMutation,
  useUpsertClientReportScheduleMutation,
} from "@/lib/queries/client-intelligence";
import type {
  ClientReportCadence,
  ClientReportGovernanceStatus,
  ClientReportPackage,
  ReportSectionConfig,
  ReportSectionKey,
} from "@/types/client-intelligence";
import {
  GOVERNANCE_STATUS_LABELS,
  REPORT_CADENCE_OPTIONS,
  REPORT_SECTION_OPTIONS,
} from "@/types/client-intelligence";

function labelToken(value: string): string {
  return value
    .split("_")
    .filter(Boolean)
    .map((part) => part.charAt(0).toUpperCase() + part.slice(1).toLowerCase())
    .join(" ");
}

function formatDateTime(value: string | null | undefined): string {
  if (!value) return "—";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return new Intl.DateTimeFormat(undefined, {
    year: "numeric",
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  }).format(date);
}

function safeFileStem(title: string): string {
  const stem = title
    .trim()
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-+|-+$/g, "");
  return stem || "client-report";
}

function downloadBlob(blob: Blob, fileName: string) {
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = fileName;
  anchor.click();
  URL.revokeObjectURL(url);
}

function openBlobInNewTab(blob: Blob) {
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.target = "_blank";
  anchor.rel = "noopener noreferrer";
  anchor.style.display = "none";
  document.body.appendChild(anchor);
  anchor.click();
  anchor.remove();
  window.setTimeout(() => URL.revokeObjectURL(url), 60_000);
}

function defaultSections(): ReportSectionConfig[] {
  return REPORT_SECTION_OPTIONS.map((item) => ({
    section: item.key,
    enabled: true,
  }));
}

function statusTone(status: ClientReportGovernanceStatus): string {
  if (status === "published") return "bg-[color:var(--success)]/15 text-[color:var(--success)]";
  if (status === "rejected") return "bg-[color:var(--danger)]/15 text-[color:var(--danger)]";
  if (status === "draft") return "bg-muted text-muted-foreground";
  return "bg-[color:var(--warning)]/15 text-[color:var(--warning)]";
}

function Widget({
  title,
  value,
  detail,
  availability,
}: {
  title: string;
  value: string;
  detail: string;
  availability?: string;
}) {
  return (
    <div className="rounded-md border border-border bg-elevated p-2.5">
      <div className="flex items-center justify-between gap-2">
        <p className="text-[10px] font-semibold uppercase tracking-wider text-muted-foreground">
          {title}
        </p>
        {availability ? <StatusPill status={availability} /> : null}
      </div>
      <p className="mt-1 text-sm font-semibold text-foreground">{value}</p>
      <p className="mt-0.5 text-[11px] text-muted-foreground">{detail}</p>
    </div>
  );
}

export function ClientReportingWorkbench({ projectId }: { projectId: string }) {
  const dashboardQuery = useClientIntelligenceDashboardQuery(projectId);
  const schedulesQuery = useClientReportSchedulesQuery(projectId);
  const packagesQuery = useClientReportPackagesQuery(projectId);

  const upsertSchedule = useUpsertClientReportScheduleMutation(projectId);
  const updateSchedule = useUpdateClientReportScheduleMutation(projectId);
  const draftPackage = useDraftClientReportPackageMutation(projectId);
  const runDue = useRunDueClientReportSchedulesMutation(projectId);
  const transition = useTransitionClientReportGovernanceMutation(projectId);
  const exportPackage = useExportClientReportPackageMutation();

  const [cadence, setCadence] = useState<ClientReportCadence>("weekly");
  const [sections, setSections] = useState<ReportSectionConfig[]>(defaultSections);
  const [selectedPackageId, setSelectedPackageId] = useState<string | null>(null);
  const [comment, setComment] = useState("");
  const [rejectionReason, setRejectionReason] = useState("");
  const [exporting, setExporting] = useState<"pdf" | "docx" | "preview" | null>(null);
  const [notice, setNotice] = useState<{ tone: "success" | "error"; message: string } | null>(
    null,
  );

  const packages = packagesQuery.data ?? [];
  const selectedPackage =
    packages.find((item) => item.id === selectedPackageId) ?? packages[0] ?? null;

  useEffect(() => {
    if (!selectedPackageId && packages[0]) {
      setSelectedPackageId(packages[0].id);
    }
  }, [packages, selectedPackageId]);

  useEffect(() => {
    setSelectedPackageId(null);
    setNotice(null);
    setComment("");
    setRejectionReason("");
  }, [projectId]);

  const approvalsQuery = useClientReportApprovalsQuery(selectedPackage?.id ?? null);
  const deliveriesQuery = useClientReportDeliveriesQuery(selectedPackage?.id ?? null);

  const enabledCount = useMemo(
    () => sections.filter((item) => item.enabled).length,
    [sections],
  );

  const showError = (error: unknown, fallback: string) => {
    setNotice({
      tone: "error",
      message: error instanceof ApiError ? error.message : fallback,
    });
  };

  const toggleSection = (key: ReportSectionKey) => {
    setSections((current) =>
      current.map((item) =>
        item.section === key ? { ...item, enabled: !item.enabled } : item,
      ),
    );
  };

  const saveSchedule = async () => {
    setNotice(null);
    try {
      await upsertSchedule.mutateAsync({
        cadence,
        enabled: true,
        sections,
      });
      setNotice({
        tone: "success",
        message: `${labelToken(cadence)} schedule saved.`,
      });
    } catch (error) {
      showError(error, "Schedule could not be saved.");
    }
  };

  const generateDraft = async () => {
    setNotice(null);
    try {
      const pkg = await draftPackage.mutateAsync({
        cadence,
        sections,
        title: `${labelToken(cadence)} Client Report`,
      });
      setSelectedPackageId(pkg.id);
      setNotice({
        tone: "success",
        message: `AI draft created (v${pkg.version}).`,
      });
    } catch (error) {
      showError(error, "Report draft could not be generated.");
    }
  };

  const runDueSchedules = async () => {
    setNotice(null);
    try {
      const created = await runDue.mutateAsync();
      setNotice({
        tone: "success",
        message:
          created.length > 0
            ? `Generated ${created.length} due schedule draft(s).`
            : "No due schedules to run.",
      });
      if (created[0]) setSelectedPackageId(created[0].id);
    } catch (error) {
      showError(error, "Due schedules could not be run.");
    }
  };

  const runGovernance = async (
    action: "submit" | "approve" | "reject" | "resubmit",
    pkg: ClientReportPackage,
  ) => {
    setNotice(null);
    try {
      const updated = await transition.mutateAsync({
        packageId: pkg.id,
        action,
        comment: comment.trim() || null,
        rejection_reason: action === "reject" ? rejectionReason.trim() : null,
      });
      setSelectedPackageId(updated.id);
      setComment("");
      setRejectionReason("");
      setNotice({
        tone: "success",
        message: `Package moved to ${GOVERNANCE_STATUS_LABELS[updated.status]}.`,
      });
    } catch (error) {
      showError(error, "Governance transition failed.");
    }
  };

  const download = async (
    format: "pdf" | "docx",
    mode: "download" | "preview" = "download",
  ) => {
    if (!selectedPackage) return;
    setNotice(null);
    setExporting(mode === "preview" ? "preview" : format);
    try {
      const blob = await exportPackage.mutateAsync({
        packageId: selectedPackage.id,
        exportFormat: format,
      });
      const fileName = `${safeFileStem(selectedPackage.title)}.${format}`;
      if (mode === "preview" && format === "pdf") {
        openBlobInNewTab(blob);
        setNotice({
          tone: "success",
          message: "PDF opened in a new tab.",
        });
      } else {
        downloadBlob(blob, fileName);
        setNotice({
          tone: "success",
          message: `${format.toUpperCase()} export downloaded.`,
        });
      }
    } catch (error) {
      showError(
        error,
        mode === "preview" ? "PDF preview failed." : `${format.toUpperCase()} export failed.`,
      );
    } finally {
      setExporting(null);
    }
  };

  const dashboard = dashboardQuery.data;
  const busy =
    upsertSchedule.isPending ||
    updateSchedule.isPending ||
    draftPackage.isPending ||
    runDue.isPending ||
    transition.isPending ||
    exportPackage.isPending ||
    exporting != null;

  return (
    <section className="mb-4 space-y-3 rounded-md border border-border bg-card p-3">
      <div className="flex flex-wrap items-start justify-between gap-2">
        <div>
          <h4 className="text-xs font-semibold text-foreground">
            Client Reporting & Governance
          </h4>
          <p className="text-[11px] text-muted-foreground">
            Schedules, modular report builder, approval workflow, and delivery tracking.
          </p>
        </div>
        <button
          type="button"
          className="rounded border border-border px-2 py-1 text-[11px] hover:bg-elevated disabled:opacity-50"
          disabled={busy}
          onClick={() =>
            void Promise.all([
              dashboardQuery.refetch(),
              schedulesQuery.refetch(),
              packagesQuery.refetch(),
            ])
          }
        >
          Refresh
        </button>
      </div>

      {notice ? (
        <div
          role={notice.tone === "error" ? "alert" : "status"}
          className={`rounded-md border px-3 py-2 text-xs ${
            notice.tone === "error"
              ? "border-[color:var(--danger)]/30 bg-[color:var(--danger)]/10 text-[color:var(--danger)]"
              : "border-[color:var(--success)]/30 bg-[color:var(--success)]/10 text-[color:var(--success)]"
          }`}
        >
          {notice.message}
        </div>
      ) : null}

      <div className="grid gap-2 sm:grid-cols-2 xl:grid-cols-3">
        <Widget
          title="Readiness"
          availability={dashboard?.widget_availability.readiness}
          value={
            dashboard?.readiness?.overall_score_pct != null
              ? `${dashboard.readiness.overall_score_pct}%`
              : "—"
          }
          detail={
            dashboard?.readiness
              ? labelToken(dashboard.readiness.status)
              : dashboardQuery.isLoading
                ? "Loading…"
                : "Not assessed"
          }
        />
        <Widget
          title="Reports"
          availability={dashboard?.widget_availability.reports}
          value={`${dashboard?.reports_drafted_count ?? 0} / ${dashboard?.reports_approved_count ?? 0}`}
          detail={`Drafted / approved · ${dashboard?.reports_published_count ?? 0} published packages`}
        />
        <Widget
          title="Communications"
          availability={dashboard?.widget_availability.communications}
          value={`${dashboard?.communications_pending_count ?? 0}`}
          detail="Pending draft / in-review communications"
        />
        <Widget
          title="Project Health"
          availability={dashboard?.widget_availability.project_health}
          value={
            dashboard?.project_health
              ? labelToken(dashboard.project_health.status)
              : "—"
          }
          detail="Governed health from overview evidence"
        />
        <Widget
          title="Milestones"
          availability={dashboard?.widget_availability.milestones}
          value={`${dashboard?.milestone_on_track_count ?? 0} / ${dashboard?.milestone_at_risk_count ?? 0}`}
          detail="On track / at risk in selected period"
        />
        <Widget
          title="Approvals"
          availability={dashboard?.widget_availability.approvals}
          value={`${dashboard?.open_approvals_count ?? 0}`}
          detail="Packages awaiting manager / leadership / compliance"
        />
      </div>

      <div className="grid gap-3 lg:grid-cols-2">
        <div className="space-y-2 rounded-md border border-border p-2.5">
          <h5 className="text-[11px] font-semibold uppercase tracking-wider text-muted-foreground">
            Scheduling
          </h5>
          <label className="block text-[11px] text-muted-foreground">
            Cadence
            <select
              className="mt-1 h-8 w-full rounded-md border border-input bg-transparent px-2 text-xs"
              value={cadence}
              onChange={(event) => setCadence(event.target.value as ClientReportCadence)}
            >
              {REPORT_CADENCE_OPTIONS.map((option) => (
                <option key={option.value} value={option.value}>
                  {option.label}
                </option>
              ))}
            </select>
          </label>
          <div className="flex flex-wrap gap-1.5">
            <button
              type="button"
              disabled={busy}
              className="rounded border border-border px-2 py-1 text-[11px] hover:bg-elevated disabled:opacity-50"
              onClick={() => void saveSchedule()}
            >
              Save schedule
            </button>
            <button
              type="button"
              disabled={busy}
              className="rounded border border-border px-2 py-1 text-[11px] hover:bg-elevated disabled:opacity-50"
              onClick={() => void runDueSchedules()}
            >
              Run due schedules
            </button>
          </div>
          <ul className="space-y-1 text-[11px] text-muted-foreground">
            {(schedulesQuery.data ?? []).map((schedule) => (
              <li
                key={schedule.id}
                className="flex flex-wrap items-center justify-between gap-2 rounded border border-border/70 px-2 py-1"
              >
                <span>
                  {labelToken(schedule.cadence)} · {schedule.enabled ? "Enabled" : "Paused"}
                </span>
                <span className="flex items-center gap-2">
                  <span>Next {formatDateTime(schedule.next_run_at)}</span>
                  <button
                    type="button"
                    className="underline disabled:opacity-50"
                    disabled={busy}
                    onClick={() =>
                      void updateSchedule
                        .mutateAsync({
                          scheduleId: schedule.id,
                          payload: { enabled: !schedule.enabled },
                        })
                        .then(() =>
                          setNotice({
                            tone: "success",
                            message: `${labelToken(schedule.cadence)} schedule ${
                              schedule.enabled ? "paused" : "enabled"
                            }.`,
                          }),
                        )
                        .catch((error) => showError(error, "Schedule update failed."))
                    }
                  >
                    {schedule.enabled ? "Pause" : "Enable"}
                  </button>
                </span>
              </li>
            ))}
            {!schedulesQuery.isLoading && (schedulesQuery.data ?? []).length === 0 ? (
              <li>No schedules configured yet.</li>
            ) : null}
            {schedulesQuery.isError ? (
              <li className="text-[color:var(--danger)]">
                Schedules unavailable. Apply the readiness reporting migration if needed.
              </li>
            ) : null}
          </ul>
        </div>

        <div className="space-y-2 rounded-md border border-border p-2.5">
          <h5 className="text-[11px] font-semibold uppercase tracking-wider text-muted-foreground">
            Report builder ({enabledCount} sections)
          </h5>
          <div className="grid grid-cols-1 gap-1 sm:grid-cols-2">
            {REPORT_SECTION_OPTIONS.map((option) => {
              const checked =
                sections.find((item) => item.section === option.key)?.enabled ?? false;
              return (
                <label
                  key={option.key}
                  className="flex items-center gap-2 rounded border border-border/60 px-2 py-1 text-[11px]"
                >
                  <input
                    type="checkbox"
                    checked={checked}
                    onChange={() => toggleSection(option.key)}
                  />
                  {option.label}
                </label>
              );
            })}
          </div>
          <div className="flex flex-wrap gap-1.5">
            <Button
              type="button"
              size="sm"
              className="h-7 text-[11px]"
              disabled={busy || enabledCount === 0}
              onClick={() => void generateDraft()}
            >
              {draftPackage.isPending ? (
                <Loader2 className="mr-1 h-3 w-3 animate-spin" />
              ) : (
                <Sparkles className="mr-1 h-3 w-3" />
              )}
              Generate AI draft
            </Button>
          </div>
        </div>
      </div>

      <div className="grid gap-3 lg:grid-cols-2">
        <div className="space-y-2 rounded-md border border-border p-2.5">
          <h5 className="text-[11px] font-semibold uppercase tracking-wider text-muted-foreground">
            Report packages
          </h5>
          {packagesQuery.isError ? (
            <p className="text-[11px] text-[color:var(--danger)]">
              Packages unavailable. Confirm migration{" "}
              <code>20260722120000_client_intelligence_readiness_reporting.sql</code> is applied.
            </p>
          ) : null}
          <ul className="max-h-56 space-y-1 overflow-auto text-[11px]">
            {packages.map((pkg) => (
              <li key={pkg.id}>
                <button
                  type="button"
                  className={`w-full rounded border px-2 py-1.5 text-left hover:bg-elevated ${
                    selectedPackage?.id === pkg.id
                      ? "border-foreground/40 bg-elevated"
                      : "border-border"
                  }`}
                  onClick={() => setSelectedPackageId(pkg.id)}
                >
                  <div className="flex items-center justify-between gap-2">
                    <span className="font-medium text-foreground">{pkg.title}</span>
                    <span
                      className={`rounded px-1.5 py-0.5 text-[10px] ${statusTone(pkg.status)}`}
                    >
                      {GOVERNANCE_STATUS_LABELS[pkg.status]}
                    </span>
                  </div>
                  <p className="mt-0.5 text-muted-foreground">
                    {labelToken(pkg.report_type)} · v{pkg.version} ·{" "}
                    {formatDateTime(pkg.created_at)}
                  </p>
                </button>
              </li>
            ))}
            {!packagesQuery.isLoading && packages.length === 0 ? (
              <li className="text-muted-foreground">No report packages yet. Generate a draft.</li>
            ) : null}
          </ul>
        </div>

        <div className="space-y-2 rounded-md border border-border p-2.5">
          <h5 className="text-[11px] font-semibold uppercase tracking-wider text-muted-foreground">
            Governance workflow
          </h5>
          {!selectedPackage ? (
            <p className="text-[11px] text-muted-foreground">Select a package to manage approvals.</p>
          ) : (
            <>
              <p className="text-[11px] text-foreground">
                Current: <strong>{GOVERNANCE_STATUS_LABELS[selectedPackage.status]}</strong>
                {" · "}
                Draft → Manager → Leadership → Compliance → Published
              </p>
              {selectedPackage.rejection_reason ? (
                <p className="text-[11px] text-[color:var(--danger)]">
                  Rejection: {selectedPackage.rejection_reason}
                </p>
              ) : null}
              <label className="block text-[11px] text-muted-foreground">
                Comment
                <input
                  className="mt-1 h-8 w-full rounded-md border border-input bg-transparent px-2 text-xs"
                  value={comment}
                  onChange={(event) => setComment(event.target.value)}
                  placeholder="Optional review comment"
                />
              </label>
              {selectedPackage.status.startsWith("pending_") ? (
                <label className="block text-[11px] text-muted-foreground">
                  Rejection reason
                  <input
                    className="mt-1 h-8 w-full rounded-md border border-input bg-transparent px-2 text-xs"
                    value={rejectionReason}
                    onChange={(event) => setRejectionReason(event.target.value)}
                    placeholder="Required when rejecting"
                  />
                </label>
              ) : null}
              <div className="flex flex-wrap gap-1.5">
                {selectedPackage.status === "draft" ? (
                  <button
                    type="button"
                    disabled={busy}
                    className="rounded border border-border px-2 py-1 text-[11px] hover:bg-elevated disabled:opacity-50"
                    onClick={() => void runGovernance("submit", selectedPackage)}
                  >
                    Submit to manager
                  </button>
                ) : null}
                {selectedPackage.status.startsWith("pending_") ? (
                  <>
                    <button
                      type="button"
                      disabled={busy}
                      className="rounded border border-border px-2 py-1 text-[11px] hover:bg-elevated disabled:opacity-50"
                      onClick={() => void runGovernance("approve", selectedPackage)}
                    >
                      Approve stage
                    </button>
                    <button
                      type="button"
                      disabled={busy || !rejectionReason.trim()}
                      className="rounded border border-[color:var(--danger)]/40 px-2 py-1 text-[11px] text-[color:var(--danger)] hover:bg-[color:var(--danger)]/10 disabled:opacity-50"
                      onClick={() => void runGovernance("reject", selectedPackage)}
                    >
                      Reject
                    </button>
                  </>
                ) : null}
                {selectedPackage.status === "rejected" ? (
                  <button
                    type="button"
                    disabled={busy}
                    className="rounded border border-border px-2 py-1 text-[11px] hover:bg-elevated disabled:opacity-50"
                    onClick={() => void runGovernance("resubmit", selectedPackage)}
                  >
                    Resubmit as draft
                  </button>
                ) : null}
              </div>

              <div>
                <p className="text-[10px] font-semibold uppercase tracking-wider text-muted-foreground">
                  Approval history / audit trail
                </p>
                <ul className="mt-1 max-h-28 space-y-1 overflow-auto text-[11px] text-muted-foreground">
                  {(approvalsQuery.data ?? []).map((item) => (
                    <li key={item.id}>
                      {formatDateTime(item.created_at)} ·{" "}
                      {item.from_status
                        ? GOVERNANCE_STATUS_LABELS[item.from_status]
                        : "—"}{" "}
                      → {GOVERNANCE_STATUS_LABELS[item.to_status]}
                      {item.comment ? ` · ${item.comment}` : ""}
                      {item.rejection_reason ? ` · Rejected: ${item.rejection_reason}` : ""}
                    </li>
                  ))}
                  {!approvalsQuery.isLoading && (approvalsQuery.data ?? []).length === 0 ? (
                    <li>No approval events yet.</li>
                  ) : null}
                </ul>
              </div>

              <div>
                <p className="text-[10px] font-semibold uppercase tracking-wider text-muted-foreground">
                  Delivery tracking
                </p>
                <ul className="mt-1 max-h-24 space-y-1 overflow-auto text-[11px] text-muted-foreground">
                  {(deliveriesQuery.data ?? []).map((item) => (
                    <li key={item.id}>
                      {formatDateTime(item.delivered_at ?? item.created_at)} ·{" "}
                      {labelToken(item.status)} · {item.channel}
                      {item.recipient_summary ? ` · ${item.recipient_summary}` : ""}
                    </li>
                  ))}
                  {!deliveriesQuery.isLoading && (deliveriesQuery.data ?? []).length === 0 ? (
                    <li>No deliveries recorded until publish.</li>
                  ) : null}
                </ul>
              </div>
            </>
          )}
        </div>
      </div>

      <div className="space-y-2 rounded-md border border-border p-2.5">
        <div className="flex flex-wrap items-start justify-between gap-2">
          <div className="min-w-0">
            <h5 className="flex items-center gap-1.5 text-[11px] font-semibold uppercase tracking-wider text-muted-foreground">
              <FileText className="h-3.5 w-3.5" />
              Report preview & export
            </h5>
            {selectedPackage ? (
              <p className="mt-1 text-[11px] text-muted-foreground">
                {selectedPackage.title}
                {" · "}
                {GOVERNANCE_STATUS_LABELS[selectedPackage.status]}
                {" · "}
                {labelToken(selectedPackage.report_type)} v{selectedPackage.version}
                {" · "}
                {formatDateTime(selectedPackage.updated_at ?? selectedPackage.created_at)}
              </p>
            ) : (
              <p className="mt-1 text-[11px] text-muted-foreground">
                Select or generate a package to preview the report body and export PDF/DOCX.
              </p>
            )}
          </div>
          <div className="flex flex-wrap gap-1.5">
            <Button
              type="button"
              size="sm"
              variant="outline"
              className="h-7 text-[11px]"
              disabled={!selectedPackage || exporting != null}
              onClick={() => void download("pdf", "preview")}
            >
              {exporting === "preview" ? (
                <Loader2 className="mr-1 h-3 w-3 animate-spin" />
              ) : (
                <Eye className="mr-1 h-3 w-3" />
              )}
              Open PDF
            </Button>
            <Button
              type="button"
              size="sm"
              variant="outline"
              className="h-7 text-[11px]"
              disabled={!selectedPackage || exporting != null}
              onClick={() => void download("pdf")}
            >
              {exporting === "pdf" ? (
                <Loader2 className="mr-1 h-3 w-3 animate-spin" />
              ) : (
                <Download className="mr-1 h-3 w-3" />
              )}
              Download PDF
            </Button>
            <Button
              type="button"
              size="sm"
              variant="outline"
              className="h-7 text-[11px]"
              disabled={!selectedPackage || exporting != null}
              onClick={() => void download("docx")}
            >
              {exporting === "docx" ? (
                <Loader2 className="mr-1 h-3 w-3 animate-spin" />
              ) : (
                <Download className="mr-1 h-3 w-3" />
              )}
              Download DOCX
            </Button>
          </div>
        </div>

        <div className="overflow-hidden rounded-md border border-border bg-[color:var(--background)]">
          <div className="border-b border-border bg-elevated/50 px-4 py-2.5">
            <p className="text-[10px] font-semibold uppercase tracking-[0.14em] text-muted-foreground">
              Client Intelligence Report
            </p>
            <p className="mt-0.5 truncate text-sm font-semibold text-foreground">
              {selectedPackage?.title ?? "Untitled report"}
            </p>
          </div>
          <div className="max-h-[28rem] min-h-[12rem] overflow-y-auto p-5">
            {selectedPackage?.body_markdown?.trim() ? (
              <div className="prose-invert max-w-none text-sm leading-6">
                <DeliveryMarkdown content={selectedPackage.body_markdown} />
              </div>
            ) : (
              <div className="flex h-40 flex-col items-center justify-center text-center">
                <FileText className="h-6 w-6 text-muted-foreground" />
                <p className="mt-2 text-sm font-medium text-foreground">No report body yet</p>
                <p className="mt-1 max-w-sm text-[11px] text-muted-foreground">
                  Generate an AI draft from the section builder to populate this preview, then
                  export as PDF.
                </p>
              </div>
            )}
          </div>
        </div>
      </div>
    </section>
  );
}
