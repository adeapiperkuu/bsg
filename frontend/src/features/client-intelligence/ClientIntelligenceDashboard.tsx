import { useMutation, useQueryClient } from "@tanstack/react-query";
import { RefreshCw, Star } from "lucide-react";
import { useEffect, useId, useMemo, useRef, useState, type ReactNode } from "react";

import { Card, SectionHeader, StatusPill } from "@/components/bsg/widgets";
import {
  AlertDialog,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from "@/components/ui/alert-dialog";
import {
  ApiError,
  approveClientIntelligenceCommunication,
  createClientIntelligenceDraft,
  editClientIntelligenceDraft,
  rejectClientIntelligenceCommunication,
  sendClientIntelligenceCommunication,
  submitClientIntelligenceDraftForReview,
  type ProjectRead,
} from "@/lib/api";
import {
  useClientMasterQuery,
  useClientIntelligenceCommunicationsQuery,
  useClientIntelligenceDeliveryConfidenceHistoryQuery,
  useClientIntelligenceOverviewQuery,
  useClientIntelligenceProjectSummaryQuery,
  useClientIntelligenceQueryHistoryQuery,
  useClientIntelligenceReportHistoryQuery,
  useClientIntelligenceSummaryQuery,
  useCreateClientIntelligenceQueryMutation,
} from "@/lib/queries/client-intelligence";
import {
  cancelClientIntelligenceProjectPrefetch,
  scheduleClientIntelligenceProjectPrefetch,
} from "@/lib/queries/client-intelligence-prefetch";
import { projectsQueryOptions, useProjectsQuery } from "@/lib/queries/delivery";
import { queryKeys } from "@/lib/queries/keys";
import type {
  ClientIntelligenceOverview,
  ClientIntelligenceQueryRead,
  ClientIntelligenceReportHistoryItem,
  ClientIntelligenceSummary,
  ClientCommunicationDraft,
  ClientMasterRow,
  DeliveryConfidenceHistory,
  DeliveryConfidenceHistoryPoint,
  ReportHistoryStatusFilter,
  SummaryMetricAvailability,
} from "@/types/client-intelligence";

const ACTIVE_QUEUE_STATUSES = new Set(["draft", "in_review", "approved", "rejected"]);

type LifecycleAction = "edit" | "submit_for_review" | "approve" | "reject" | "send";

type LifecycleMutationVars = {
  communicationId: string;
  projectId: string;
  action: LifecycleAction;
  subject?: string;
  body_draft?: string;
  body_approved?: string;
  rejection_reason?: string;
};

type LifecycleNotice = {
  projectId: string;
  tone: "success" | "error";
  message: string;
};

function lifecyclePendingKey(communicationId: string, action: LifecycleAction): string {
  return `${communicationId}:${action}`;
}

function labelToken(value: string): string {
  return value
    .split("_")
    .filter(Boolean)
    .map((part) => part.charAt(0).toUpperCase() + part.slice(1).toLowerCase())
    .join(" ");
}

function formatDate(value: string | null): string {
  if (!value) return "Not available";
  const date = new Date(value.includes("T") ? value : `${value}T00:00:00Z`);
  if (Number.isNaN(date.getTime())) return value;
  return new Intl.DateTimeFormat(undefined, {
    year: "numeric",
    month: "short",
    day: "numeric",
  }).format(date);
}

function formatDateTime(value: string): string {
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

function formatShortDate(value: string | null): string {
  if (!value) return "—";
  const parsed = new Date(value.includes("T") ? value : `${value}T00:00:00Z`);
  if (Number.isNaN(parsed.getTime())) return value;
  return new Intl.DateTimeFormat(undefined, {
    month: "short",
    day: "2-digit",
  }).format(parsed);
}

function exactUnique(values: string[]): string[] {
  return [...new Set(values)];
}

function formatLatency(ms: number | null | undefined): string {
  if (ms == null) return "Not measured";
  if (ms < 1000) return `${ms} ms`;
  if (ms < 60_000) {
    const seconds = ms / 1000;
    const rounded = seconds >= 10 ? Math.round(seconds) : Number(seconds.toFixed(1));
    return `${rounded} s`;
  }
  const minutes = ms / 60_000;
  if (minutes >= 60) {
    return `${Number((minutes / 60).toFixed(1))} h`;
  }
  const rounded = minutes >= 10 ? Math.round(minutes) : Number(minutes.toFixed(1));
  return `${rounded} min`;
}

function availabilityLabel(availability: SummaryMetricAvailability): string {
  if (availability === "no_data") return "No data";
  if (availability === "partial") return "Partial";
  if (availability === "unavailable") return "Not available";
  return "Available";
}

/** Approved share of drafted reports, clamped to 0–100. Zero drafted → 0%. */
function reportsApprovedPercentage(draftedCount: number, approvedCount: number): string {
  if (!Number.isFinite(draftedCount) || draftedCount <= 0) return "0%";
  if (!Number.isFinite(approvedCount) || approvedCount <= 0) return "0%";
  const raw = Math.round((approvedCount / draftedCount) * 100);
  return `${Math.min(100, Math.max(0, raw))}%`;
}

function Status({ value }: { value: string }) {
  return <StatusPill status={labelToken(value)} />;
}

function CompactButton({
  children,
  onClick,
  disabled = false,
  ariaLabel,
}: {
  children: ReactNode;
  onClick: () => void;
  disabled?: boolean;
  ariaLabel?: string;
}) {
  return (
    <button
      type="button"
      aria-label={ariaLabel}
      disabled={disabled}
      onClick={onClick}
      className="rounded border border-border px-2 py-0.5 text-[10px] transition-colors hover:bg-elevated focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring disabled:cursor-not-allowed disabled:opacity-50"
    >
      {children}
    </button>
  );
}

function LimitationItems({ values }: { values: string[] }) {
  const limitations = exactUnique(values);
  if (limitations.length === 0) return null;
  return (
    <ul className="mt-1 space-y-1 text-[11px] text-muted-foreground">
      {limitations.map((limitation) => (
        <li key={limitation} className="break-words">
          {labelToken(limitation)}
        </li>
      ))}
    </ul>
  );
}

function clampSparklineCoord(value: number, min: number, max: number): number {
  if (!Number.isFinite(value)) return min;
  return Math.min(max, Math.max(min, value));
}

function sparklineCoordinates(
  points: DeliveryConfidenceHistoryPoint[],
): Array<{ x: number; y: number }> {
  const width = 76;
  const height = 24;
  const padX = 2;
  const padY = 2;
  const usableWidth = width - padX * 2;
  const usableHeight = height - padY * 2;
  if (points.length === 0) return [];
  return points.map((point, index) => {
    const score = Number(point.score_pct);
    const safeScore = Number.isFinite(score) ? Math.min(100, Math.max(0, score)) : 0;
    const x =
      points.length === 1
        ? padX + usableWidth / 2
        : padX + (index / (points.length - 1)) * usableWidth;
    const y = padY + usableHeight - (safeScore / 100) * usableHeight;
    return {
      x: clampSparklineCoord(x, 0, width),
      y: clampSparklineCoord(y, 0, height),
    };
  });
}

function formatHistoryDate(value: string): string {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return new Intl.DateTimeFormat(undefined, {
    year: "numeric",
    month: "short",
    day: "numeric",
  }).format(date);
}

function ConfidenceHistorySparkline({
  selected,
  history,
  loading,
  error,
}: {
  selected: boolean;
  history: DeliveryConfidenceHistory | undefined;
  loading: boolean;
  error: boolean;
}) {
  const width = 76;
  const height = 24;

  if (!selected) {
    return (
      <div className="h-6 w-[76px]" aria-label="Confidence history unavailable.">
        <span className="sr-only">Confidence history unavailable.</span>
      </div>
    );
  }

  if (loading) {
    return (
      <div className="h-6 w-[76px]" aria-label="Loading confidence history…">
        <span className="sr-only">Loading confidence history…</span>
      </div>
    );
  }

  if (error || !history || history.availability === "unavailable") {
    return (
      <div className="h-6 w-[76px]" aria-label="Confidence history unavailable.">
        <span className="sr-only">Confidence history unavailable.</span>
      </div>
    );
  }

  if (history.availability === "no_data") {
    return (
      <div className="h-6 w-[76px]" aria-label="No confidence history available.">
        <span className="sr-only">No confidence history available.</span>
      </div>
    );
  }

  if (history.points.length === 0) {
    const emptyLabel =
      history.current_score_availability === "invalid"
        ? "No confidence history available. Current confidence score unavailable."
        : "No confidence history available.";
    return (
      <div className="h-6 w-[76px]" aria-label={emptyLabel}>
        <span className="sr-only">{emptyLabel}</span>
        {history.limitations.length > 0 && (
          <div className="sr-only">
            <LimitationItems values={history.limitations} />
          </div>
        )}
      </div>
    );
  }

  const coords = sparklineCoordinates(history.points);
  const oldest = history.points[0];
  const latest = history.points[history.points.length - 1];
  const latestPhrase = history.latest_history_point_is_current
    ? `latest/current ${latest.score_pct}% on ${formatHistoryDate(latest.observed_at)}`
    : `latest historical point ${latest.score_pct}% on ${formatHistoryDate(latest.observed_at)}`;
  const summaryParts = [
    `${history.returned_point_count} point${history.returned_point_count === 1 ? "" : "s"}`,
    `oldest ${oldest.score_pct}% on ${formatHistoryDate(oldest.observed_at)}`,
    latestPhrase,
    labelToken(history.availability),
  ];
  if (!history.latest_history_point_is_current) {
    summaryParts.push("current confidence score unavailable");
  }
  const summary = summaryParts.join(" · ");

  return (
    <div className="h-6 w-[76px]">
      <svg
        viewBox={`0 0 ${width} ${height}`}
        className="h-6 w-[76px] text-[color:var(--brand)]"
        fill="none"
        role="img"
        aria-label={summary}
      >
        <title>{summary}</title>
        {coords.length >= 2 ? (
          <polyline
            points={coords.map((point) => `${point.x},${point.y}`).join(" ")}
            stroke="currentColor"
            strokeWidth="2"
            strokeLinecap="round"
            strokeLinejoin="round"
          />
        ) : (
          <circle cx={coords[0].x} cy={coords[0].y} r="2.5" fill="currentColor" />
        )}
      </svg>
      {history.availability === "partial" && history.limitations.length > 0 && (
        <div className="sr-only">
          <LimitationItems values={history.limitations} />
        </div>
      )}
    </div>
  );
}

function DeliveryConfidenceCard({
  overview,
  selectedProjectName,
  loading,
  error,
  summary,
  summaryLoading,
  summaryError,
  history,
  historyLoading,
  historyError,
  historyEnabled,
}: {
  overview: ClientIntelligenceOverview | undefined;
  selectedProjectName: string | undefined;
  loading: boolean;
  error: boolean;
  summary: ClientIntelligenceSummary["delivery_confidence"] | undefined;
  summaryLoading: boolean;
  summaryError: boolean;
  history: DeliveryConfidenceHistory | undefined;
  historyLoading: boolean;
  historyError: boolean;
  historyEnabled: boolean;
}) {
  const confidence = overview?.delivery_confidence;
  const hasSelection = Boolean(selectedProjectName);
  let value: string;
  let state: string;
  let limitations: string[] = [];

  if (hasSelection) {
    if (loading) {
      value = "Loading…";
      state = `Loading ${selectedProjectName}`;
    } else if (error || !confidence) {
      value = "Not available";
      state = `${selectedProjectName} · Overview unavailable`;
    } else {
      value = confidence.score_pct === null ? "No score" : `${confidence.score_pct}%`;
      state = [
        selectedProjectName,
        labelToken(confidence.availability),
        confidence.confidence_band ? labelToken(confidence.confidence_band) : null,
      ]
        .filter((item): item is string => Boolean(item))
        .join(" · ");
    }
  } else if (summaryLoading) {
    value = "Loading…";
    state = "Loading authorized scope";
  } else if (summaryError || !summary) {
    value = "Not available";
    state = "Authorized-scope summary unavailable";
  } else {
    value = summary.average_score_pct === null ? "No score" : `${summary.average_score_pct}%`;
    state = `${availabilityLabel(summary.availability)} · ${
      summary.covered_project_count
    } of ${summary.eligible_project_count} projects`;
    limitations = summary.limitations;
  }

  return (
    <Card>
      <div className="text-xs uppercase tracking-wider text-muted-foreground">
        Delivery Confidence
      </div>
      <div className="mt-2 flex items-center justify-between">
        <div className="text-2xl font-semibold">{value}</div>
        <ConfidenceHistorySparkline
          selected={historyEnabled}
          history={history}
          loading={historyLoading}
          error={historyError}
        />
      </div>
      <div className="sr-only">{state}</div>
      {limitations.length > 0 && (
        <div className="sr-only">
          <LimitationItems values={limitations} />
        </div>
      )}
    </Card>
  );
}

function SummaryCapabilityCards({
  summary,
  loading,
  error,
  scopeLabel,
}: {
  summary: ClientIntelligenceSummary | undefined;
  loading: boolean;
  error: boolean;
  scopeLabel: string;
}) {
  const reports = summary?.reports;
  const query = summary?.query_response;
  const csat = summary?.csat;
  const reportsAvailability = loading
    ? "Loading"
    : error
      ? "Not available"
      : reports
        ? availabilityLabel(reports.availability)
        : "Not available";
  const queryAvailability = loading
    ? "Loading"
    : error
      ? "Not available"
      : query
        ? availabilityLabel(query.availability)
        : "Not available";
  const csatAvailability = loading
    ? "Loading"
    : error
      ? "Not available"
      : csat
        ? availabilityLabel(csat.availability)
        : "Not available";

  const reportsValue = loading
    ? "Loading…"
    : error
      ? "Not available"
      : reports
        ? reports.availability === "available" || reports.availability === "partial"
          ? `${reports.drafted_count} drafted · ${reports.approved_count} approved`
          : availabilityLabel(reports.availability)
        : "Not available";

  const queryValue = loading
    ? "Loading…"
    : error
      ? "Not available"
      : query
        ? query.availability === "available" || query.availability === "partial"
          ? query.average_latency_ms === null
            ? availabilityLabel(query.availability)
            : formatLatency(query.average_latency_ms)
          : availabilityLabel(query.availability)
        : "Not available";

  const csatValue = loading
    ? "Loading…"
    : error
      ? "Not available"
      : csat
        ? csat.availability === "available" || csat.availability === "partial"
          ? csat.average_score === null
            ? availabilityLabel(csat.availability)
            : `${csat.average_score} / ${csat.scale_max}`
          : csat.availability === "no_data"
            ? "No responses"
            : availabilityLabel(csat.availability)
        : "Not available";
  const approvedWidth =
    !loading &&
    !error &&
    reports &&
    (reports.availability === "available" || reports.availability === "partial")
      ? reportsApprovedPercentage(reports.drafted_count, reports.approved_count)
      : "0%";
  const hasCsatScore =
    !loading &&
    !error &&
    Boolean(csat) &&
    (csat!.availability === "available" || csat!.availability === "partial") &&
    csat!.average_score !== null;
  const numericCsat = hasCsatScore ? Number(csat!.average_score) : 0;
  const filledStars = Number.isFinite(numericCsat) ? Math.floor(numericCsat) : 0;
  const queryHasSample = !loading && !error && Boolean(query && query.sample_size > 0);
  const querySecondary = queryHasSample
    ? `${query!.sample_size} response${query!.sample_size === 1 ? "" : "s"}`
    : queryValue === "No data" || queryValue === "Not available" || queryValue === "Loading…"
      ? null
      : queryAvailability;
  const csatDetail = hasCsatScore
    ? `${csat!.average_score} / ${csat!.scale_max} across ${csat!.sample_size} response${
        csat!.sample_size === 1 ? "" : "s"
      }`
    : csatValue;

  return (
    <>
      <Card>
        <div className="text-xs uppercase tracking-wider text-muted-foreground">
          Reports Drafted vs Approved
        </div>
        <div className="mt-2 text-sm">{reportsValue}</div>
        <div
          className="mt-2 h-2 overflow-hidden rounded bg-elevated"
          aria-label={`Reports Drafted vs Approved availability: ${scopeLabel} · ${reportsAvailability}`}
        >
          <div className="h-full bg-[color:var(--brand)]" style={{ width: approvedWidth }} />
        </div>
        <span className="sr-only">{`${scopeLabel} · ${reportsAvailability}`}</span>
        {!loading && !error && reports && reports.limitations.length > 0 && (
          <div className="sr-only">
            <LimitationItems values={reports.limitations} />
          </div>
        )}
      </Card>
      <Card>
        <div className="text-xs font-medium uppercase tracking-wider text-muted-foreground">
          Avg Query Response
        </div>
        <div className="mt-2 text-2xl font-semibold text-foreground">{queryValue}</div>
        <div
          aria-label={`Avg Query Response availability: ${scopeLabel} · ${queryAvailability}`}
          className={`mt-1 text-xs font-medium ${
            queryHasSample ? "text-[color:var(--success)]" : "text-muted-foreground"
          }`}
        >
          {querySecondary}
        </div>
        <span className="sr-only">{`${scopeLabel} · ${queryAvailability}`}</span>
        {!loading && !error && query && query.limitations.length > 0 && (
          <div className="sr-only">
            <LimitationItems values={query.limitations} />
          </div>
        )}
      </Card>
      <Card>
        <div className="text-xs uppercase tracking-wider text-muted-foreground">Avg CSAT</div>
        <div className="mt-2 flex gap-0.5" aria-label={`${csatValue} average CSAT`}>
          {[1, 2, 3, 4, 5].map((star) => (
            <Star
              key={star}
              className={`h-5 w-5 ${
                star <= filledStars
                  ? "fill-[color:var(--warning)] text-[color:var(--warning)]"
                  : "text-muted-foreground/40"
              }`}
            />
          ))}
        </div>
        <div className="mt-1 text-[11px] text-muted-foreground">{csatDetail}</div>
        <div className="sr-only">
          <span>{`${scopeLabel} · ${csatAvailability}`}</span>
          <span aria-label={`Avg CSAT availability: ${scopeLabel} · ${csatAvailability}`}>
            {csatAvailability}
          </span>
          {!loading && !error && csat && csat.limitations.length > 0 && (
            <LimitationItems values={csat.limitations} />
          )}
        </div>
      </Card>
    </>
  );
}

function ProjectTable({
  projects,
  selectedProjectId,
  overview,
  overviewLoading,
  overviewError,
  masterByProjectId,
  query,
  onQueryChange,
  onSelect,
  onDraft,
  draftingProjectId,
  onRefresh,
}: {
  projects: ProjectRead[];
  selectedProjectId: string | null;
  overview: ClientIntelligenceOverview | undefined;
  overviewLoading: boolean;
  overviewError: boolean;
  masterByProjectId: Map<string, ClientMasterRow>;
  query: string;
  onQueryChange: (value: string) => void;
  onSelect: (projectId: string) => void;
  onDraft: (projectId: string) => void;
  draftingProjectId: string | null;
  onRefresh: () => void;
}) {
  const queryClient = useQueryClient();
  const filteredProjects = useMemo(() => {
    const normalized = query.trim().toLowerCase();
    if (!normalized) return projects;
    return projects.filter((project) => project.name.toLowerCase().includes(normalized));
  }, [projects, query]);

  return (
    <>
      <SectionHeader
        title="Client Master"
        right={
          <div className="sr-only">
            <label>
              Search project names
              <input value={query} onChange={(event) => onQueryChange(event.target.value)} />
            </label>
            <CompactButton onClick={onRefresh} ariaLabel="Refresh projects">
              <RefreshCw className="h-3 w-3" />
            </CompactButton>
          </div>
        }
      />
      {filteredProjects.length === 0 ? (
        <div className="rounded-md border border-dashed border-border p-6 text-center text-xs text-muted-foreground">
          {query.trim()
            ? "No authorized projects match this search."
            : "No authorized projects are available for Client Intelligence."}
        </div>
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full min-w-[43rem] text-xs" aria-label="Authorized client projects">
            <thead className="text-left text-muted-foreground">
              <tr className="border-b border-border">
                <th className="py-2 pr-3 font-medium">Client</th>
                <th className="py-2 pr-3 font-medium">Projects</th>
                <th className="py-2 pr-3 font-medium">Health</th>
                <th className="py-2 pr-3 font-medium">Confidence</th>
                <th className="py-2 pr-3 font-medium">Last Report</th>
                <th className="py-2 pr-3 font-medium">Next</th>
                <th className="py-2 pr-3 font-medium">CSAT</th>
                <th className="py-2 pr-3 font-medium"></th>
              </tr>
            </thead>
            <tbody>
              {filteredProjects.map((project) => {
                const selected = project.id === selectedProjectId;
                const master = masterByProjectId.get(project.id);
                const rowOverview =
                  overview?.project.project_id === project.id ? overview : undefined;
                const rowLoading = selected && overviewLoading;
                const rowOverviewFailed = selected && overviewError;
                return (
                  <tr
                    key={project.id}
                    aria-selected={selected}
                    className={`cursor-pointer border-b border-border/50 hover:bg-elevated ${
                      selected ? "bg-elevated" : ""
                    }`}
                    onClick={() => {
                      cancelClientIntelligenceProjectPrefetch(project.id);
                      onSelect(project.id);
                    }}
                    onMouseEnter={() =>
                      scheduleClientIntelligenceProjectPrefetch(queryClient, project.id)
                    }
                    onMouseLeave={() => cancelClientIntelligenceProjectPrefetch(project.id)}
                  >
                    <td className="py-2.5 pr-3 font-medium">{project.name}</td>
                    <td className="py-2.5 pr-3">{master?.project_count ?? 1}</td>
                    <td className="py-2.5 pr-3">
                      {rowOverviewFailed ? (
                        "Not assessed"
                      ) : rowOverview ? (
                        <Status value={rowOverview.project_health.status} />
                      ) : rowLoading ? (
                        "Loading…"
                      ) : (
                        "Not assessed"
                      )}
                    </td>
                    <td className="py-2.5 pr-3">
                      {rowOverview
                        ? rowOverview.delivery_confidence.score_pct === null
                          ? "No score"
                          : `${rowOverview.delivery_confidence.score_pct}%`
                        : rowLoading
                          ? "Loading…"
                          : master?.confidence_score_pct
                            ? `${master.confidence_score_pct}%`
                            : "—"}
                    </td>
                    <td className="py-2.5 pr-3 text-muted-foreground">
                      {formatShortDate(master?.last_report_at ?? null)}
                    </td>
                    <td className="py-2.5 pr-3">
                      {formatShortDate(master?.next_milestone_date ?? null)}
                    </td>
                    <td className="py-2.5 pr-3">
                      {master?.csat_average ? `${master.csat_average}/5` : "—"}
                    </td>
                    <td className="py-2.5 pr-3">
                      <div className="flex items-center gap-1">
                        <button
                          type="button"
                          aria-label={`View ${project.name}`}
                          onClick={(event) => {
                            event.stopPropagation();
                            onSelect(project.id);
                          }}
                          className="cursor-pointer rounded border border-border bg-card px-2.5 py-1 text-[11px] font-medium transition-colors hover:bg-elevated focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
                        >
                          View
                        </button>
                        <button
                          type="button"
                          aria-label={`Draft ${project.name}`}
                          onClick={(event) => {
                            event.stopPropagation();
                            onDraft(project.id);
                          }}
                          disabled={draftingProjectId === project.id}
                          title={`Create evidence-backed draft${
                            master?.draft_count ? ` · ${master.draft_count} pending` : ""
                          }`}
                          className="cursor-pointer rounded bg-[color:var(--brand)] px-2.5 py-1 text-[11px] font-semibold text-[color:var(--brand-foreground)] transition-opacity hover:opacity-90 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring disabled:cursor-wait disabled:opacity-50"
                        >
                          {draftingProjectId === project.id ? "Creating…" : "Draft"}
                        </button>
                      </div>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
    </>
  );
}

function ProjectListState({
  loading,
  error,
  onRetry,
}: {
  loading: boolean;
  error: boolean;
  onRetry: () => void;
}) {
  if (loading) {
    return (
      <div
        role="status"
        aria-live="polite"
        className="py-10 text-center text-xs text-muted-foreground"
      >
        Loading authorized projects…
      </div>
    );
  }
  if (error) {
    return (
      <div role="alert" className="rounded-md border border-dashed border-border p-6 text-center">
        <p className="text-xs text-muted-foreground">Authorized projects could not be loaded.</p>
        <div className="mt-2">
          <CompactButton onClick={onRetry}>Retry projects</CompactButton>
        </div>
      </div>
    );
  }
  return null;
}

function healthStatusLabel(status: string): string {
  if (status === "green") return "On Track";
  if (status === "amber") return "At Risk";
  if (status === "red") return "Critical";
  if (status === "insufficient") return "Insufficient";
  return labelToken(status);
}

function healthTrendLabel(trend: string): string {
  if (trend === "improving") return "Improving";
  if (trend === "stable") return "Stable";
  if (trend === "deteriorating") return "Getting worse";
  return "Not enough history yet";
}

function confidenceTrendLabel(trend: string): string {
  if (trend === "increased") return "Improving";
  if (trend === "decreased") return "Declining";
  if (trend === "stable") return "Stable";
  return "Not enough history yet";
}

function confidenceBandLabel(band: string | null): string {
  if (!band) return "Not available yet";
  if (band === "on_track") return "On track";
  if (band === "at_risk") return "At risk";
  if (band === "critical") return "Critical";
  return labelToken(band);
}

function dataQualityPlainLabel(quality: string): string {
  if (quality === "complete") return "Complete";
  if (quality === "partial") return "Partial";
  if (quality === "stale") return "Out of date";
  if (quality === "conflicting") return "Conflicting";
  if (quality === "unavailable") return "Not available";
  return labelToken(quality);
}

const LIMITATION_FRIENDLY_LABELS: Record<string, string> = {
  PROJECT_HEALTH_POLICY_UNAVAILABLE: "Project health rules are not configured yet",
  PREVIOUS_ASSESSMENT_UNAVAILABLE: "No previous health assessment is available",
  EXPLANATION_POLICY_UNAVAILABLE: "Confidence explanation rules are not configured yet",
  RISK_POLICY_UNAVAILABLE: "Risk policy is not configured yet",
  CLIENT_VISIBILITY_POLICY_UNAVAILABLE: "Client visibility rules for risks are not configured yet",
  BUSINESS_IMPACT_POLICY_UNRESOLVED: "Business-impact rules for risks are not resolved yet",
  MITIGATION_EVIDENCE_UNAVAILABLE: "Mitigation evidence is not available yet",
  WORKFLOW_STATUS_UNAVAILABLE: "Workflow status data is not connected yet",
  BACKLOG_QUEUE_UNAVAILABLE: "Backlog queue data is not connected yet",
  CLIENT_COMMUNICATION_NOTES_UNAVAILABLE: "Client communication notes are not available yet",
  PLAN_SERIES_UNAVAILABLE: "Plan progress data is not available yet",
  DEVIATION_POLICY_UNAVAILABLE: "Delivery deviation rules are not configured yet",
  FRESHNESS_SLA_UNRESOLVED: "Data freshness rules are not configured yet",
};

function limitationCodeKey(raw: string): string | null {
  const trimmed = raw.trim();
  const leading = trimmed.match(/^([A-Z][A-Z0-9_]{2,})\b/);
  if (leading) return leading[1];
  if (/^[A-Z][A-Z0-9_]+$/.test(trimmed)) return trimmed;
  return null;
}

function isTechnicalLimitationText(raw: string): boolean {
  const text = raw.toLowerCase();
  return (
    /ci-d\d+/i.test(raw) ||
    text.includes("knowledgesourcetype") ||
    text.includes("knowledge source type") ||
    text.includes("phase 1 blocker") ||
    text.includes("knowledgedocument") ||
    text.includes("clientcommunication") ||
    text.includes("lesson_learned") ||
    text.includes("uuid project") ||
    text.includes("source contract") ||
    text.includes("normalized project-name") ||
    text.includes("stale-data threshold") ||
    text.includes("retrieval-ready")
  );
}

function friendlyLimitationLabel(raw: string): string {
  const trimmed = raw.trim();
  const code = limitationCodeKey(trimmed);
  if (code && LIMITATION_FRIENDLY_LABELS[code]) return LIMITATION_FRIENDLY_LABELS[code];
  if (code && /^[A-Z][A-Z0-9_]+$/.test(trimmed)) return labelToken(trimmed);
  if (isTechnicalLimitationText(trimmed)) {
    if (/communication notes/i.test(trimmed)) {
      return "Client communication notes are not available yet";
    }
    if (/backlog/i.test(trimmed)) return "Backlog queue data is not connected yet";
    if (/workflow status/i.test(trimmed)) return "Workflow status data is not connected yet";
    if (/freshness|stale/i.test(trimmed)) return "Data freshness rules are not configured yet";
    if (/knowledge/i.test(trimmed)) {
      return "Some knowledge sources are not available for this project";
    }
    if (/charter/i.test(trimmed)) return "No project charter was found for this date";
    return "Some supporting data is not available yet";
  }
  return trimmed;
}

function friendlyDataQualitySource(source: string): string {
  const key = source.trim().toLowerCase().replace(/-/g, "_");
  const map: Record<string, string> = {
    throughput_snapshots: "Delivery throughput",
    delivery_confidence_scores: "Delivery confidence scores",
    delivery: "Delivery evidence",
    freshness_sla: "Data freshness rules",
    bottlenecks: "Bottlenecks",
    risk_alerts: "Risk alerts",
    milestones: "Milestones",
    quality_snapshots: "Quality snapshots",
    workforce: "Workforce",
    utilization_snapshots: "Utilization",
    project_skill_requirements: "Skill requirements",
    capability_gaps: "Capability gaps",
    knowledge_visibility: "Knowledge visibility",
    governance_actions: "Governance actions",
    governance_dependencies: "Governance dependencies",
    governance_escalations: "Governance escalations",
    governance_scope: "Governance scope",
    governance_charter: "Project charter",
    projects: "Project record",
    overall_data_quality: "Overall data quality",
    source_fingerprint: "Source fingerprint",
    policy_fingerprint: "Policy fingerprint",
    reporting_period: "Reporting period",
    generated_at: "Generated timestamp",
    evidence: "Evidence links",
    data_quality: "Data quality checks",
    visibility_limitations: "Visibility checks",
    limitations: "Limitation checks",
    visibility_mode: "Visibility mode",
    operational_knowledge: "Operational knowledge",
    ci_d07: "Workflow status",
    dq_ci_d07: "Workflow status",
    ci_d09: "Backlog queue",
    dq_ci_d09: "Backlog queue",
    ci_d14: "Client communication notes",
    dq_ci_d14: "Client communication notes",
    knowledge_ci_d11: "SOP documents",
    knowledge_ci_d12: "Training documents",
    knowledge_ci_d13: "Project charter documents",
    knowledge_ci_d14: "Client communication notes",
  };
  if (map[key]) return map[key];

  const ciMatch = key.match(/(?:^|_)(?:dq_)?ci_d(\d+)$/);
  if (ciMatch) {
    const ciLabels: Record<string, string> = {
      "07": "Workflow status",
      "09": "Backlog queue",
      "11": "SOP documents",
      "12": "Training documents",
      "13": "Project charter documents",
      "14": "Client communication notes",
    };
    if (ciLabels[ciMatch[1]]) return ciLabels[ciMatch[1]];
  }

  return labelToken(source);
}

function friendlyDataQualityDetail(detail: string): string {
  const trimmed = detail.trim();
  if (!isTechnicalLimitationText(trimmed) && trimmed.length < 160) return trimmed;
  return friendlyLimitationLabel(trimmed);
}

type DataQualityCategory =
  | "Delivery"
  | "Risks & blockers"
  | "Documents & knowledge"
  | "Governance"
  | "Team"
  | "Other";

const DATA_QUALITY_CATEGORY_ORDER: DataQualityCategory[] = [
  "Delivery",
  "Risks & blockers",
  "Documents & knowledge",
  "Governance",
  "Team",
  "Other",
];

const DATA_QUALITY_STATE_PRIORITY: Record<string, number> = {
  unavailable: 0,
  conflicting: 1,
  stale: 2,
  partial: 3,
};

const DATA_QUALITY_VISIBLE_LIMIT = 5;

type FriendlyDataQualityRow = {
  key: string;
  source: string;
  sourceLabel: string;
  state: string;
  stateLabel: string;
  category: DataQualityCategory;
  detailLabel: string | null;
};

function dataQualityCategory(source: string): DataQualityCategory {
  const key = source.trim().toLowerCase().replace(/-/g, "_");
  if (
    [
      "throughput_snapshots",
      "delivery_confidence_scores",
      "delivery",
      "milestones",
      "freshness_sla",
      "ci_d07",
      "dq_ci_d07",
      "ci_d09",
      "dq_ci_d09",
    ].includes(key) ||
    /(?:^|_)(?:dq_)?ci_d0[79]$/.test(key)
  ) {
    return "Delivery";
  }
  if (["risk_alerts", "bottlenecks"].includes(key)) return "Risks & blockers";
  if (
    key.startsWith("knowledge") ||
    key === "operational_knowledge" ||
    ["ci_d14", "dq_ci_d14"].includes(key) ||
    /(?:^|_)(?:dq_)?ci_d1[1-4]$/.test(key)
  ) {
    return "Documents & knowledge";
  }
  if (key.startsWith("governance")) return "Governance";
  if (
    ["workforce", "utilization_snapshots", "project_skill_requirements", "capability_gaps"].includes(
      key,
    )
  ) {
    return "Team";
  }
  return "Other";
}

function userFacingDataQualityProblems(
  issues: ClientIntelligenceOverview["data_quality"],
): FriendlyDataQualityRow[] {
  const rows: FriendlyDataQualityRow[] = [];
  const seen = new Set<string>();

  for (const issue of issues) {
    const state = issue.state.trim().toLowerCase();
    if (state === "complete") continue;

    const sourceLabel = friendlyDataQualitySource(issue.source);
    const stateLabel = dataQualityPlainLabel(issue.state);
    const detailIsTechnical = isTechnicalLimitationText(issue.detail);
    let detailLabel = detailIsTechnical
      ? friendlyLimitationLabel(issue.detail)
      : friendlyDataQualityDetail(issue.detail);
    if (
      !detailLabel ||
      detailLabel.length > 120 ||
      detailLabel.toLowerCase() === stateLabel.toLowerCase() ||
      detailLabel.toLowerCase() === "some supporting data is not available yet"
    ) {
      detailLabel = "";
    }

    const dedupeKey = `${sourceLabel}|${state}`;
    if (seen.has(dedupeKey)) continue;
    seen.add(dedupeKey);

    rows.push({
      key: `${issue.source}:${issue.state}`,
      source: issue.source,
      sourceLabel,
      state,
      stateLabel,
      category: dataQualityCategory(issue.source),
      detailLabel: detailLabel || null,
    });
  }

  return rows.sort((a, b) => {
    const stateDiff =
      (DATA_QUALITY_STATE_PRIORITY[a.state] ?? 99) - (DATA_QUALITY_STATE_PRIORITY[b.state] ?? 99);
    if (stateDiff !== 0) return stateDiff;
    const categoryDiff =
      DATA_QUALITY_CATEGORY_ORDER.indexOf(a.category) -
      DATA_QUALITY_CATEGORY_ORDER.indexOf(b.category);
    if (categoryDiff !== 0) return categoryDiff;
    return a.sourceLabel.localeCompare(b.sourceLabel);
  });
}

type DataQualityGroupSummary = {
  category: DataQualityCategory;
  worstStateLabel: string;
  rows: FriendlyDataQualityRow[];
};

function summarizeStateCounts(rows: FriendlyDataQualityRow[]): string {
  const labelOrder = ["Not available", "Conflicting", "Out of date", "Partial"];
  const counts = new Map<string, number>();
  for (const row of rows) {
    counts.set(row.stateLabel, (counts.get(row.stateLabel) ?? 0) + 1);
  }
  return [...counts.entries()]
    .sort((a, b) => {
      const ai = labelOrder.indexOf(a[0]);
      const bi = labelOrder.indexOf(b[0]);
      return (ai === -1 ? 99 : ai) - (bi === -1 ? 99 : bi);
    })
    .map(([label, count]) => (count === 1 ? label : `${count} ${label.toLowerCase()}`))
    .join(", ");
}

function groupDataQualityProblems(rows: FriendlyDataQualityRow[]): DataQualityGroupSummary[] {
  const byCategory = new Map<DataQualityCategory, FriendlyDataQualityRow[]>();
  for (const row of rows) {
    const list = byCategory.get(row.category) ?? [];
    list.push(row);
    byCategory.set(row.category, list);
  }

  return DATA_QUALITY_CATEGORY_ORDER.filter((category) => byCategory.has(category)).map(
    (category) => {
      const groupRows = byCategory.get(category) ?? [];
      return {
        category,
        worstStateLabel: groupRows[0]?.stateLabel ?? "Partial",
        rows: groupRows,
      };
    },
  );
}

function DataQualitySummary({
  overall,
  issues,
}: {
  overall: string;
  issues: ClientIntelligenceOverview["data_quality"];
}) {
  const [showAll, setShowAll] = useState(false);
  const problems = userFacingDataQualityProblems(issues);
  const groups = groupDataQualityProblems(problems);
  const visibleGroups = showAll ? groups : groups.slice(0, DATA_QUALITY_VISIBLE_LIMIT);
  const hasCollapsedSources = groups.some((group) => group.rows.length > 1);
  const hasHiddenGroups = groups.length > DATA_QUALITY_VISIBLE_LIMIT;
  const totalSources = problems.length;

  return (
    <section>
      <div className="mb-2 flex items-center justify-between">
        <h4 className="text-[10px] font-semibold uppercase tracking-wider text-muted-foreground">
          Data quality
        </h4>
        <Status value={dataQualityPlainLabel(overall)} />
      </div>
      {problems.length === 0 ? (
        <p className="text-[11px] text-muted-foreground">
          {overall === "complete"
            ? "All checked sources look complete for this snapshot."
            : "No data-quality issues were flagged for this snapshot."}
        </p>
      ) : (
        <div className="space-y-2">
          <ul className="space-y-1.5 text-[11px] text-muted-foreground">
            {visibleGroups.map((group) => (
              <li key={group.category}>
                <div className="flex items-start justify-between gap-2">
                  <p className="min-w-0 break-words">
                    {group.rows.length === 1 ? (
                      <>
                        <span className="font-medium text-foreground">
                          {group.rows[0].sourceLabel}
                        </span>
                        {" · "}
                        {group.rows[0].stateLabel}
                        {group.rows[0].detailLabel ? (
                          <>
                            {" · "}
                            {group.rows[0].detailLabel}
                          </>
                        ) : null}
                      </>
                    ) : (
                      <>
                        <span className="font-medium text-foreground">{group.category}</span>
                        {" · "}
                        {summarizeStateCounts(group.rows)}
                      </>
                    )}
                  </p>
                  {group.rows.length > 1 && <Status value={group.worstStateLabel} />}
                </div>
                {showAll && group.rows.length > 1 && (
                  <ul className="mt-1 space-y-0.5 border-l border-border pl-2">
                    {group.rows.map((row) => (
                      <li key={row.key}>
                        {row.sourceLabel} · {row.stateLabel}
                        {row.detailLabel ? ` · ${row.detailLabel}` : ""}
                      </li>
                    ))}
                  </ul>
                )}
              </li>
            ))}
          </ul>
          {!showAll && (hasCollapsedSources || hasHiddenGroups) && (
            <button
              type="button"
              className="text-[11px] font-medium text-foreground underline-offset-2 hover:underline"
              onClick={() => setShowAll(true)}
            >
              Show all sources ({totalSources})
            </button>
          )}
          {showAll && (hasCollapsedSources || hasHiddenGroups) && (
            <button
              type="button"
              className="text-[11px] font-medium text-foreground underline-offset-2 hover:underline"
              onClick={() => setShowAll(false)}
            >
              Show less
            </button>
          )}
        </div>
      )}
    </section>
  );
}

function userFacingLimitations(values: string[]): string[] {
  return exactUnique(
    values
      .map((value) => value.trim())
      .filter(Boolean)
      .filter((value) => !isTechnicalLimitationText(value) || Boolean(limitationCodeKey(value)))
      .map((value) => friendlyLimitationLabel(value)),
  );
}

function EngineSection({
  title,
  status,
  statusLabel,
  children,
}: {
  title: string;
  status: string;
  statusLabel?: string;
  children?: ReactNode;
}) {
  return (
    <section className="rounded border border-border bg-elevated p-2.5">
      <div className="flex items-center justify-between gap-2">
        <h4 className="text-[10px] font-semibold uppercase tracking-wider text-muted-foreground">
          {title}
        </h4>
        <Status value={statusLabel ?? status} />
      </div>
      {children && <div className="mt-1.5 space-y-1 text-xs leading-5 text-foreground">{children}</div>}
    </section>
  );
}

function FriendlyLimitationList({ values }: { values: string[] }) {
  const items = userFacingLimitations(values);
  if (items.length === 0) return null;
  return (
    <ul className="mt-1 space-y-1 text-[11px] text-muted-foreground">
      {items.map((item) => (
        <li key={item} className="break-words">
          {item}
        </li>
      ))}
    </ul>
  );
}

function DetailLine({ label, children }: { label: string; children: ReactNode }) {
  return (
    <p>
      <span className="text-muted-foreground">{label}: </span>
      {children}
    </p>
  );
}

function CompactOverview({ overview }: { overview: ClientIntelligenceOverview }) {
  const health = overview.project_health;
  const confidence = overview.delivery_confidence;
  const risk = overview.risk_transparency;
  const trend = overview.delivery_trend;
  const latestPoint = trend.trend_points.at(-1);
  const engineLimitationCodes = exactUnique([
    ...health.limitations,
    ...confidence.limitations,
    ...risk.limitations,
    ...trend.limitations,
    ...confidence.source_limitations,
    ...risk.source_limitations,
    ...trend.source_limitations,
  ]);
  const confidenceScore =
    confidence.score_pct === null ? "No score" : `${confidence.score_pct}%`;
  const previousHealth = health.history.previous_status;
  const engineLimitationItems = userFacingLimitations(engineLimitationCodes);
  const technicalLimitationDump = exactUnique([
    ...[
      ...engineLimitationCodes,
      ...overview.source_limitations,
      ...overview.visibility_limitations.map(
        (item) => `${item.source}: ${item.reason}: ${item.detail}`,
      ),
    ].filter(
      (item) => isTechnicalLimitationText(item) || /^[A-Z][A-Z0-9_]+$/.test(item.trim()),
    ),
    ...overview.data_quality.map((issue) => `${issue.source}: ${issue.state}: ${issue.detail}`),
  ]);

  return (
    <div className="space-y-3">
      <div className="rounded-md border border-border bg-elevated p-3 text-xs leading-5">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <span className="font-medium">{overview.project.project_name}</span>
          <Status value={overview.project.project_status} />
        </div>
        <div className="mt-1.5 space-y-0.5 text-[11px] text-muted-foreground">
          <p>Snapshot as of {formatDate(overview.as_of)}</p>
          <p>Last refreshed {formatDateTime(overview.generated_at)}</p>
          <p>
            Reporting period {formatDate(overview.reporting_period.start_date)} –{" "}
            {formatDate(overview.reporting_period.end_date)}
          </p>
          <p>
            Audience:{" "}
            {overview.visibility_mode === "client_safe" ? "Client-safe view" : "Internal team view"}
          </p>
        </div>
      </div>

      <div className="grid gap-2 sm:grid-cols-2 lg:grid-cols-1 xl:grid-cols-2">
        <EngineSection
          title="Project Health"
          status={health.status}
          statusLabel={healthStatusLabel(health.status)}
        >
          <DetailLine label="Overall status">{healthStatusLabel(health.status)}</DetailLine>
          <DetailLine label="Supporting data">
            {dataQualityPlainLabel(health.overall_data_quality)}
          </DetailLine>
          {previousHealth ? (
            <DetailLine label="Compared with last period">
              {healthStatusLabel(previousHealth)} · {healthTrendLabel(health.history.trend)}
            </DetailLine>
          ) : (
            <DetailLine label="Compared with last period">No previous assessment yet</DetailLine>
          )}
        </EngineSection>

        <EngineSection title="Delivery Confidence" status={confidence.availability}>
          <DetailLine label="Schedule confidence">{confidenceScore}</DetailLine>
          <DetailLine label="Confidence level">
            {confidenceBandLabel(confidence.confidence_band)}
          </DetailLine>
          <DetailLine label="Direction">{confidenceTrendLabel(confidence.trend)}</DetailLine>
          {confidence.previous_score_pct !== null && (
            <DetailLine label="Previous score">{confidence.previous_score_pct}%</DetailLine>
          )}
          {confidence.current_milestone ? (
            <DetailLine label="Current milestone">{confidence.current_milestone.name}</DetailLine>
          ) : (
            <DetailLine label="Current milestone">Not available</DetailLine>
          )}
          {confidence.forecast_completion_date ? (
            <DetailLine label="Forecast completion">
              {formatDate(confidence.forecast_completion_date)}
            </DetailLine>
          ) : (
            <DetailLine label="Forecast completion">Not available</DetailLine>
          )}
        </EngineSection>

        <EngineSection title="Risk Transparency" status={risk.availability}>
          <DetailLine label="Open items in this view">{risk.risk_items.length}</DetailLine>
          {risk.risk_items.slice(0, 2).map((item) => (
            <p key={`${item.source_type}:${item.source_row_id}`} className="text-muted-foreground">
              {labelToken(item.category)} · {labelToken(item.status)}
              {item.risk_tier ? ` · ${labelToken(item.risk_tier)} priority` : ""}
            </p>
          ))}
          {risk.risk_items.length === 0 && risk.availability !== "available" && (
            <p className="text-[11px] text-muted-foreground">
              No items are published for this assessment state.
            </p>
          )}
          {risk.risk_items.length === 0 && risk.availability === "available" && (
            <p className="text-[11px] text-muted-foreground">
              No open risk items are currently listed for this project.
            </p>
          )}
        </EngineSection>

        <EngineSection title="Delivery Trend" status={trend.availability}>
          <DetailLine label="Progress snapshots">
            {trend.trend_points.length} · {labelToken(trend.grain)} view
          </DetailLine>
          {latestPoint ? (
            <p>
              Latest {formatDate(latestPoint.snapshot_date)} · Actual{" "}
              {latestPoint.actual_units ?? labelToken(latestPoint.actual_state)} · Plan{" "}
              {latestPoint.plan_units ?? labelToken(latestPoint.plan_state)} · Forecast{" "}
              {latestPoint.forecast_units ?? labelToken(latestPoint.forecast_state)}
            </p>
          ) : (
            <p className="text-[11px] text-muted-foreground">
              No recent progress snapshot is available yet.
            </p>
          )}
        </EngineSection>
      </div>

      <DataQualitySummary
        overall={overview.overall_data_quality}
        issues={overview.data_quality}
      />

      <section className="grid gap-2 sm:grid-cols-2 lg:grid-cols-1 xl:grid-cols-2">
        <div>
          <h4 className="text-[10px] font-semibold uppercase tracking-wider text-muted-foreground">
            Source limitations
          </h4>
          <FriendlyLimitationList values={overview.source_limitations} />
          {userFacingLimitations(overview.source_limitations).length === 0 && (
            <p className="mt-1 text-[11px] text-muted-foreground">No source gaps reported.</p>
          )}
        </div>
        <div>
          <h4 className="text-[10px] font-semibold uppercase tracking-wider text-muted-foreground">
            Visibility limitations
          </h4>
          {overview.visibility_limitations.length > 0 ? (
            <ul className="mt-1 space-y-1 text-[11px] text-muted-foreground">
              {overview.visibility_limitations.map((limitation, index) => (
                <li key={`${limitation.source}:${limitation.reason}:${index}`}>
                  {friendlyDataQualitySource(limitation.source)} ·{" "}
                  {labelToken(limitation.reason)} · {friendlyDataQualityDetail(limitation.detail)}
                </li>
              ))}
            </ul>
          ) : (
            <p className="mt-1 text-[11px] text-muted-foreground">
              No visibility limitations returned.
            </p>
          )}
        </div>
      </section>

      {engineLimitationItems.length > 0 && (
        <details className="rounded border border-border bg-elevated/40 px-3 py-2 text-[11px] text-muted-foreground">
          <summary className="cursor-pointer select-none font-medium text-foreground">
            Engine limitations ({engineLimitationItems.length})
          </summary>
          <FriendlyLimitationList values={engineLimitationCodes} />
        </details>
      )}

      {technicalLimitationDump.length > 0 && (
        <details className="rounded border border-border bg-elevated/40 px-3 py-2 text-[11px] text-muted-foreground">
          <summary className="cursor-pointer select-none font-medium text-foreground">
            Technical details
          </summary>
          <ul className="mt-2 space-y-1 break-words">
            {technicalLimitationDump.map((item) => (
              <li key={item}>{item}</li>
            ))}
          </ul>
        </details>
      )}
    </div>
  );
}

function OverviewError({
  error,
  onRetry,
  onRefreshProjects,
}: {
  error: Error;
  onRetry: () => void;
  onRefreshProjects: () => void;
}) {
  const apiError = error instanceof ApiError ? error : null;
  let message = "Client Intelligence could not be loaded.";
  if (apiError?.status === 403) {
    message = "You do not have permission to view Client Intelligence for this project.";
  } else if (apiError?.status === 404) {
    message = "The selected project is no longer available. Refresh the project list.";
  } else if (apiError?.code === "CLIENT_INTELLIGENCE_INTEGRITY_ERROR") {
    message = apiError.message;
  } else if (apiError) {
    message = apiError.message;
  }

  return (
    <div role="alert" className="rounded-md border border-dashed border-border p-6 text-center">
      <div className="text-xs font-medium">Overview unavailable</div>
      <p className="mt-1 text-xs text-muted-foreground">{message}</p>
      <div className="mt-2 flex justify-center gap-1">
        <CompactButton onClick={onRetry}>Retry overview</CompactButton>
        {apiError?.status === 404 && (
          <CompactButton onClick={onRefreshProjects}>Refresh projects</CompactButton>
        )}
      </div>
    </div>
  );
}

function DraftReportsQueue({
  communications,
  loading,
  error,
  onRetry,
  pendingLifecycleKeys,
  lifecycleNotices,
  selectedProjectId,
  onEdit,
  onSubmitForReview,
  onApprove,
  onReject,
  onSend,
}: {
  communications: ClientCommunicationDraft[];
  loading: boolean;
  error: boolean;
  onRetry: () => void;
  pendingLifecycleKeys: ReadonlySet<string>;
  lifecycleNotices: Record<string, LifecycleNotice>;
  selectedProjectId: string;
  onEdit: (
    communication: ClientCommunicationDraft,
    subject: string,
    bodyDraft: string,
  ) => Promise<void>;
  onSubmitForReview: (communication: ClientCommunicationDraft) => Promise<void>;
  onApprove: (communication: ClientCommunicationDraft) => Promise<void>;
  onReject: (communication: ClientCommunicationDraft, reason: string) => Promise<void>;
  onSend: (communication: ClientCommunicationDraft) => Promise<void>;
}) {
  const drafts = communications.filter(
    (communication) =>
      communication.drafted_by_agent === "client_interaction_agent" &&
      ACTIVE_QUEUE_STATUSES.has(communication.status),
  );

  return (
    <section className="mb-4 rounded-md border border-border bg-elevated/40 p-3">
      <div className="mb-2 flex items-center justify-between gap-2">
        <div>
          <h4 className="text-xs font-semibold text-foreground">Draft Reports Queue</h4>
          <p className="text-[10px] text-muted-foreground">
            Evidence-backed drafts awaiting review.
          </p>
        </div>
        <span className="rounded-full bg-secondary px-2 py-0.5 text-[10px] text-muted-foreground">
          {drafts.length}
        </span>
      </div>

      {loading && (
        <div role="status" className="py-3 text-xs text-muted-foreground">
          Loading draft reports…
        </div>
      )}
      {error && (
        <div role="alert" className="py-2 text-xs text-muted-foreground">
          Draft reports could not be loaded.{" "}
          <button type="button" className="underline" onClick={onRetry}>
            Retry
          </button>
        </div>
      )}
      {!loading && !error && drafts.length === 0 && (
        <div className="rounded border border-dashed border-border p-3 text-center text-xs text-muted-foreground">
          No draft reports for this project.
        </div>
      )}
      {!loading && !error && drafts.length > 0 && (
        <div className="space-y-2">
          {drafts.map((draft) => (
            <DraftQueueItem
              key={draft.id}
              draft={draft}
              pendingLifecycleKeys={pendingLifecycleKeys}
              notice={
                lifecycleNotices[draft.id]?.projectId === selectedProjectId
                  ? lifecycleNotices[draft.id]
                  : null
              }
              onEdit={onEdit}
              onSubmitForReview={onSubmitForReview}
              onApprove={onApprove}
              onReject={onReject}
              onSend={onSend}
            />
          ))}
        </div>
      )}
    </section>
  );
}

function DraftQueueItem({
  draft,
  pendingLifecycleKeys,
  notice,
  onEdit,
  onSubmitForReview,
  onApprove,
  onReject,
  onSend,
}: {
  draft: ClientCommunicationDraft;
  pendingLifecycleKeys: ReadonlySet<string>;
  notice: LifecycleNotice | null | undefined;
  onEdit: (
    communication: ClientCommunicationDraft,
    subject: string,
    bodyDraft: string,
  ) => Promise<void>;
  onSubmitForReview: (communication: ClientCommunicationDraft) => Promise<void>;
  onApprove: (communication: ClientCommunicationDraft) => Promise<void>;
  onReject: (communication: ClientCommunicationDraft, reason: string) => Promise<void>;
  onSend: (communication: ClientCommunicationDraft) => Promise<void>;
}) {
  const subjectId = useId();
  const bodyId = useId();
  const rejectReasonId = useId();
  const [expanded, setExpanded] = useState(false);
  const [editing, setEditing] = useState(false);
  const [subject, setSubject] = useState(draft.subject);
  const [bodyDraft, setBodyDraft] = useState(draft.body_draft);
  const [editError, setEditError] = useState<string | null>(null);
  const [rejectOpen, setRejectOpen] = useState(false);
  const [sendOpen, setSendOpen] = useState(false);
  const [rejectReason, setRejectReason] = useState("");
  const [rejectError, setRejectError] = useState<string | null>(null);

  useEffect(() => {
    if (!editing) {
      setSubject(draft.subject);
      setBodyDraft(draft.body_draft);
      setEditError(null);
    }
  }, [draft.subject, draft.body_draft, draft.status, editing]);

  const isPendingFor = (action: LifecycleAction) =>
    pendingLifecycleKeys.has(lifecyclePendingKey(draft.id, action));
  const isAnyPending = [...pendingLifecycleKeys].some((key) => key.startsWith(`${draft.id}:`));
  const isUnchangedDraftEdit =
    draft.status === "draft" &&
    subject.trim() === draft.subject.trim() &&
    bodyDraft.trim() === draft.body_draft.trim();

  const startEdit = () => {
    setSubject(draft.subject);
    setBodyDraft(draft.body_draft);
    setEditError(null);
    setEditing(true);
    setExpanded(true);
  };

  const cancelEdit = () => {
    setSubject(draft.subject);
    setBodyDraft(draft.body_draft);
    setEditError(null);
    setEditing(false);
  };

  const saveEdit = () => {
    const nextSubject = subject.trim();
    const nextBody = bodyDraft.trim();
    if (!nextSubject || !nextBody) {
      setEditError("Subject and draft body are required.");
      return;
    }
    if (
      draft.status === "draft" &&
      nextSubject === draft.subject.trim() &&
      nextBody === draft.body_draft.trim()
    ) {
      setEditError("No changes to save.");
      return;
    }
    setEditError(null);
    void onEdit(draft, nextSubject, nextBody)
      .then(() => {
        setEditing(false);
      })
      .catch(() => {
        // Keep unsaved editor values for retry.
      });
  };

  const confirmReject = () => {
    const reason = rejectReason.trim();
    if (!reason) {
      setRejectError("Rejection reason is required.");
      return;
    }
    setRejectError(null);
    void onReject(draft, reason)
      .then(() => {
        setRejectOpen(false);
        setRejectReason("");
      })
      .catch(() => {
        // Keep dialog open with entered reason.
      });
  };

  const reviewedBody = (draft.body_approved || draft.body_draft).trim();

  return (
    <div className="rounded border border-border bg-card">
      <button
        type="button"
        aria-expanded={expanded}
        aria-controls={`draft-queue-panel-${draft.id}`}
        className="flex w-full cursor-pointer items-center justify-between gap-3 px-3 py-2 text-left"
        onClick={() => setExpanded((value) => !value)}
      >
        <div className="min-w-0">
          <div className="truncate text-xs font-medium">{draft.subject}</div>
          <div className="text-[10px] text-muted-foreground">
            {formatDateTime(draft.created_at)} · {draft.evidence_links.length} evidence link
            {draft.evidence_links.length === 1 ? "" : "s"}
          </div>
        </div>
        <Status value={draft.status} />
      </button>
      {expanded && (
        <div id={`draft-queue-panel-${draft.id}`} className="border-t border-border px-3 py-3">
          {notice && (
            <div
              role={notice.tone === "error" ? "alert" : "status"}
              aria-live="polite"
              className={`mb-2 rounded border px-2 py-1.5 text-[10px] ${
                notice.tone === "error"
                  ? "border-[color:var(--danger)]/30 bg-[color:var(--danger)]/10 text-[color:var(--danger)]"
                  : "border-[color:var(--success)]/30 bg-[color:var(--success)]/10 text-[color:var(--success)]"
              }`}
            >
              {notice.message}
            </div>
          )}
          {editing ? (
            <div className="space-y-2">
              <div>
                <label
                  htmlFor={subjectId}
                  className="text-[10px] font-semibold text-muted-foreground"
                >
                  Subject
                </label>
                <input
                  id={subjectId}
                  value={subject}
                  onChange={(event) => setSubject(event.target.value)}
                  disabled={isAnyPending}
                  className="mt-1 w-full rounded border border-border bg-background px-2 py-1 text-xs"
                />
              </div>
              <div>
                <label htmlFor={bodyId} className="text-[10px] font-semibold text-muted-foreground">
                  Draft body
                </label>
                <textarea
                  id={bodyId}
                  value={bodyDraft}
                  onChange={(event) => setBodyDraft(event.target.value)}
                  disabled={isAnyPending}
                  rows={6}
                  className="mt-1 w-full rounded border border-border bg-background px-2 py-1 text-xs leading-5"
                />
              </div>
              {editError && (
                <p role="alert" className="text-[10px] text-[color:var(--danger)]">
                  {editError}
                </p>
              )}
              <div className="flex flex-wrap gap-1">
                <CompactButton
                  onClick={saveEdit}
                  disabled={isAnyPending || isUnchangedDraftEdit}
                  ariaLabel={`Save draft ${draft.subject}`}
                >
                  {isPendingFor("edit") ? "Saving…" : "Save"}
                </CompactButton>
                <CompactButton
                  onClick={cancelEdit}
                  disabled={isAnyPending}
                  ariaLabel={`Cancel editing ${draft.subject}`}
                >
                  Cancel
                </CompactButton>
              </div>
            </div>
          ) : (
            <>
              <p className="whitespace-pre-wrap text-xs leading-5 text-foreground">
                {draft.status === "in_review" || draft.status === "approved"
                  ? reviewedBody || draft.body_draft
                  : draft.body_draft}
              </p>
              {draft.status === "in_review" && draft.reviewed_at && (
                <p className="mt-2 text-[10px] text-muted-foreground">
                  In review · reviewed {formatDateTime(draft.reviewed_at)}
                </p>
              )}
              {draft.status === "approved" && draft.approved_at && (
                <p className="mt-2 text-[10px] text-muted-foreground">
                  Approved · {formatDateTime(draft.approved_at)}
                </p>
              )}
              {draft.status === "rejected" && (
                <div className="mt-2 rounded border border-border bg-elevated/50 px-2 py-1.5 text-[10px]">
                  <div className="font-semibold text-foreground">Rejected</div>
                  <p className="mt-0.5 text-muted-foreground">
                    {draft.rejection_reason?.trim()
                      ? draft.rejection_reason
                      : "Rejection reason unavailable (legacy incomplete data)."}
                  </p>
                  {draft.rejected_at && (
                    <p className="mt-0.5 text-muted-foreground">
                      Rejected {formatDateTime(draft.rejected_at)}
                    </p>
                  )}
                </div>
              )}
              <div className="mt-3 flex flex-wrap gap-1">
                {draft.status === "draft" && (
                  <>
                    <CompactButton
                      onClick={startEdit}
                      disabled={isAnyPending}
                      ariaLabel={`Edit draft ${draft.subject}`}
                    >
                      Edit
                    </CompactButton>
                    <CompactButton
                      onClick={() => {
                        void onSubmitForReview(draft).catch(() => undefined);
                      }}
                      disabled={isAnyPending || !draft.body_draft.trim()}
                      ariaLabel={`Submit ${draft.subject} for review`}
                    >
                      {isPendingFor("submit_for_review") ? "Submitting…" : "Submit for review"}
                    </CompactButton>
                  </>
                )}
                {draft.status === "in_review" && (
                  <>
                    <CompactButton
                      onClick={() => {
                        void onApprove(draft).catch(() => undefined);
                      }}
                      disabled={isAnyPending}
                      ariaLabel={`Approve ${draft.subject}`}
                    >
                      {isPendingFor("approve") ? "Approving…" : "Approve"}
                    </CompactButton>
                    <CompactButton
                      onClick={() => {
                        setRejectReason("");
                        setRejectError(null);
                        setRejectOpen(true);
                      }}
                      disabled={isAnyPending}
                      ariaLabel={`Reject ${draft.subject}`}
                    >
                      Reject
                    </CompactButton>
                  </>
                )}
                {draft.status === "approved" && (
                  <CompactButton
                    onClick={() => setSendOpen(true)}
                    disabled={isAnyPending}
                    ariaLabel={`Send ${draft.subject}`}
                  >
                    {isPendingFor("send") ? "Sending…" : "Send"}
                  </CompactButton>
                )}
                {draft.status === "rejected" && (
                  <CompactButton
                    onClick={startEdit}
                    disabled={isAnyPending}
                    ariaLabel={`Edit and revise ${draft.subject}`}
                  >
                    Edit and revise
                  </CompactButton>
                )}
              </div>
            </>
          )}
          <div className="mt-3">
            <div className="text-[10px] font-semibold uppercase tracking-wider text-muted-foreground">
              Evidence
            </div>
            {draft.evidence_links.length > 0 ? (
              <ul className="mt-1 space-y-1 text-[10px] text-muted-foreground">
                {draft.evidence_links.map((link) => (
                  <li key={`${link.source_table}:${link.source_row_id}`}>
                    {link.source_table} · {link.description}
                  </li>
                ))}
              </ul>
            ) : (
              <p className="mt-1 text-[10px] text-muted-foreground">No evidence links returned.</p>
            )}
          </div>
        </div>
      )}

      <AlertDialog
        open={rejectOpen}
        onOpenChange={(open) => {
          if (!isPendingFor("reject")) {
            setRejectOpen(open);
            if (!open) {
              setRejectReason("");
              setRejectError(null);
            }
          }
        }}
      >
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>Reject {draft.subject}</AlertDialogTitle>
            <AlertDialogDescription>
              Provide a rejection reason. The communication will return to rejected status for
              revision.
            </AlertDialogDescription>
          </AlertDialogHeader>
          <div>
            <label htmlFor={rejectReasonId} className="text-xs font-medium">
              Rejection reason
            </label>
            <textarea
              id={rejectReasonId}
              value={rejectReason}
              onChange={(event) => setRejectReason(event.target.value)}
              rows={4}
              disabled={isPendingFor("reject")}
              className="mt-1 w-full rounded border border-border bg-background px-2 py-1 text-sm"
            />
            {rejectError && (
              <p role="alert" className="mt-1 text-xs text-[color:var(--danger)]">
                {rejectError}
              </p>
            )}
          </div>
          <AlertDialogFooter>
            <AlertDialogCancel disabled={isPendingFor("reject")}>Cancel</AlertDialogCancel>
            <button
              type="button"
              disabled={isPendingFor("reject")}
              aria-label={`Confirm reject ${draft.subject}`}
              className="inline-flex h-10 items-center justify-center rounded-md bg-primary px-4 text-sm font-medium text-primary-foreground disabled:opacity-50"
              onClick={confirmReject}
            >
              {isPendingFor("reject") ? "Rejecting…" : "Reject"}
            </button>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>

      <AlertDialog
        open={sendOpen}
        onOpenChange={(open) => {
          if (!isPendingFor("send")) setSendOpen(open);
        }}
      >
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>Send {draft.subject}?</AlertDialogTitle>
            <AlertDialogDescription>
              Sending makes this communication client-visible in the portal. This does not send
              external email.
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel disabled={isPendingFor("send")}>Cancel</AlertDialogCancel>
            <button
              type="button"
              disabled={isPendingFor("send")}
              aria-label={`Confirm send ${draft.subject}`}
              className="inline-flex h-10 items-center justify-center rounded-md bg-primary px-4 text-sm font-medium text-primary-foreground disabled:opacity-50"
              onClick={() => {
                void onSend(draft)
                  .then(() => setSendOpen(false))
                  .catch(() => undefined);
              }}
            >
              {isPendingFor("send") ? "Sending…" : "Send"}
            </button>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </div>
  );
}

function dedupeReportHistoryItems(
  items: ClientIntelligenceReportHistoryItem[],
): ClientIntelligenceReportHistoryItem[] {
  const seen = new Set<string>();
  const deduped: ClientIntelligenceReportHistoryItem[] = [];
  for (const item of items) {
    if (seen.has(item.communication_id)) continue;
    seen.add(item.communication_id);
    deduped.push(item);
  }
  return deduped;
}

function ApprovedSentReportsHistory({ projectId }: { projectId: string }) {
  const [statusFilter, setStatusFilter] = useState<ReportHistoryStatusFilter>("all");
  const [expandedIds, setExpandedIds] = useState<Set<string>>(() => new Set());

  useEffect(() => {
    setStatusFilter("all");
    setExpandedIds(new Set());
  }, [projectId]);

  const historyQuery = useClientIntelligenceReportHistoryQuery(projectId, statusFilter);
  const items = useMemo(
    () => dedupeReportHistoryItems(historyQuery.data?.pages.flatMap((page) => page.items) ?? []),
    [historyQuery.data],
  );
  const total = historyQuery.data?.pages[0]?.total ?? 0;
  const isInitialLoading = historyQuery.isLoading;
  const isError = historyQuery.isError;
  const isFetchingNext = historyQuery.isFetchingNextPage;
  const hasMore = Boolean(historyQuery.hasNextPage);

  const emptyLabel =
    statusFilter === "all"
      ? "No approved or sent reports for this project."
      : statusFilter === "approved"
        ? "No approved reports for this project."
        : "No sent reports for this project.";

  const toggleExpanded = (id: string) => {
    setExpandedIds((previous) => {
      const next = new Set(previous);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  };

  return (
    <section
      className="mb-4 rounded-md border border-border bg-elevated/40 p-3"
      aria-label="Approved and sent report history"
    >
      <div className="mb-2 flex items-center justify-between gap-2">
        <div>
          <h4 className="text-xs font-semibold text-foreground">Approved & Sent Reports</h4>
          <p className="text-[10px] text-muted-foreground">
            Governed Client Intelligence report history.
          </p>
        </div>
        <span className="rounded-full bg-secondary px-2 py-0.5 text-[10px] text-muted-foreground">
          {total}
        </span>
      </div>

      <div className="mb-2 flex flex-wrap gap-1" role="group" aria-label="Report history filters">
        {(
          [
            ["all", "Show all reports", "All"],
            ["approved", "Show approved reports", "Approved"],
            ["sent", "Show sent reports", "Sent"],
          ] as const
        ).map(([value, ariaLabel, label]) => (
          <CompactButton
            key={value}
            ariaLabel={ariaLabel}
            disabled={statusFilter === value}
            onClick={() => setStatusFilter(value)}
          >
            {label}
          </CompactButton>
        ))}
      </div>

      {isInitialLoading && (
        <div role="status" aria-live="polite" className="py-3 text-xs text-muted-foreground">
          Loading report history…
        </div>
      )}
      {isError && (
        <div role="alert" className="py-2 text-xs text-muted-foreground">
          Report history could not be loaded.{" "}
          <button
            type="button"
            className="underline"
            aria-label="Retry report history"
            onClick={() => void historyQuery.refetch()}
          >
            Retry
          </button>
        </div>
      )}
      {!isInitialLoading && !isError && items.length === 0 && (
        <div className="rounded border border-dashed border-border p-3 text-center text-xs text-muted-foreground">
          {emptyLabel}
        </div>
      )}
      {!isInitialLoading && !isError && items.length > 0 && (
        <div className="space-y-2">
          {items.map((item) => {
            const expanded = expandedIds.has(item.communication_id);
            const panelId = `report-history-panel-${item.communication_id}`;
            return (
              <div key={item.communication_id} className="rounded border border-border bg-card">
                <button
                  type="button"
                  aria-expanded={expanded}
                  aria-controls={panelId}
                  aria-label={
                    expanded ? `Collapse report ${item.subject}` : `Expand report ${item.subject}`
                  }
                  className="flex w-full cursor-pointer items-center justify-between gap-3 px-3 py-2 text-left"
                  onClick={() => toggleExpanded(item.communication_id)}
                >
                  <div className="min-w-0">
                    <div className="truncate text-xs font-medium">{item.subject}</div>
                    <div className="text-[10px] text-muted-foreground">
                      {labelToken(item.report_type)} · {labelToken(item.status)}
                      {item.history_at ? ` · ${formatDateTime(item.history_at)}` : ""}
                      {` · ${item.evidence_links.length} evidence`}
                      {` · ${labelToken(item.provenance_availability)}`}
                    </div>
                  </div>
                  <Status value={item.status} />
                </button>
                {expanded && (
                  <div id={panelId} className="border-t border-border px-3 py-3">
                    {item.provenance_availability === "unavailable" ? (
                      <p className="text-xs text-muted-foreground">
                        Approved body unavailable for this legacy record.
                      </p>
                    ) : (
                      <p className="whitespace-pre-wrap text-xs leading-5 text-foreground">
                        {item.approved_body}
                      </p>
                    )}
                    <div className="mt-2 space-y-1 text-[10px] text-muted-foreground">
                      {item.approved_at && (
                        <p>
                          Approved {formatDateTime(item.approved_at)}
                          {item.approved_by ? " · Approval recorded" : ""}
                        </p>
                      )}
                      {item.sent_at && <p>Sent {formatDateTime(item.sent_at)}</p>}
                      {item.reviewed_at && (
                        <p>
                          Reviewed {formatDateTime(item.reviewed_at)}
                          {item.reviewed_by ? " · Reviewer recorded" : ""}
                        </p>
                      )}
                    </div>
                    {item.limitations.length > 0 && <LimitationItems values={item.limitations} />}
                    <div className="mt-3">
                      <div className="text-[10px] font-semibold uppercase tracking-wider text-muted-foreground">
                        Evidence
                      </div>
                      {item.evidence_links.length > 0 ? (
                        <ul className="mt-1 space-y-1 text-[10px] text-muted-foreground">
                          {item.evidence_links.map((link) => (
                            <li key={`${link.source_table}:${link.source_row_id}`}>
                              {link.source_table} · {link.description}
                            </li>
                          ))}
                        </ul>
                      ) : (
                        <p className="mt-1 text-[10px] text-muted-foreground">
                          No evidence links returned.
                        </p>
                      )}
                    </div>
                  </div>
                )}
              </div>
            );
          })}
        </div>
      )}
      {!isInitialLoading && !isError && hasMore && (
        <div className="mt-2">
          <CompactButton
            ariaLabel="Load more report history"
            disabled={isFetchingNext}
            onClick={() => void historyQuery.fetchNextPage()}
          >
            {isFetchingNext ? "Loading more…" : "Load more"}
          </CompactButton>
        </div>
      )}
    </section>
  );
}

function dedupeQueryHistoryItems(
  items: ClientIntelligenceQueryRead[],
): ClientIntelligenceQueryRead[] {
  const seen = new Set<string>();
  const deduped: ClientIntelligenceQueryRead[] = [];
  for (const item of items) {
    if (seen.has(item.query_id)) continue;
    seen.add(item.query_id);
    deduped.push(item);
  }
  return deduped;
}

function ClientIntelligenceQA({ projectId }: { projectId: string }) {
  const questionId = useId();
  const [question, setQuestion] = useState("");
  const [validationError, setValidationError] = useState<string | null>(null);
  const [askNotice, setAskNotice] = useState<{ tone: "success" | "error"; message: string } | null>(
    null,
  );
  const [expandedIds, setExpandedIds] = useState<Set<string>>(() => new Set());
  const askInFlightRef = useRef(false);
  const projectIdRef = useRef(projectId);
  projectIdRef.current = projectId;

  useEffect(() => {
    setQuestion("");
    setValidationError(null);
    setAskNotice(null);
    setExpandedIds(new Set());
    askInFlightRef.current = false;
  }, [projectId]);

  const historyQuery = useClientIntelligenceQueryHistoryQuery(projectId);
  const items = useMemo(
    () => dedupeQueryHistoryItems(historyQuery.data?.pages.flatMap((page) => page.items) ?? []),
    [historyQuery.data],
  );
  const firstPage = historyQuery.data?.pages[0];
  const historySource = firstPage?.history_source;
  const historyIsAuthoritative = !historySource || historySource === "server";
  const total = historyIsAuthoritative ? (firstPage?.total ?? 0) : items.length;
  const isInitialLoading = historyQuery.isLoading;
  const isError = historyQuery.isError;
  const showLocalPersistedHistory =
    historySource === "local_pending" || historySource === "unavailable";
  const showHistoryItems = items.length > 0 && (!isError || showLocalPersistedHistory);
  const showHistoryError = isError && !showLocalPersistedHistory;
  const serverHistoryUnavailable = historySource === "unavailable";
  const isFetchingNext = historyQuery.isFetchingNextPage;
  const hasMore = Boolean(historyQuery.hasNextPage) && historyIsAuthoritative;

  const askMutation = useCreateClientIntelligenceQueryMutation();

  const toggleExpanded = (id: string) => {
    setExpandedIds((previous) => {
      const next = new Set(previous);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  };

  const submitQuestion = () => {
    if (askInFlightRef.current) return;
    const trimmed = question.trim();
    if (!trimmed) {
      setValidationError("Enter a question before asking.");
      return;
    }
    const submittedProjectId = projectId;
    setValidationError(null);
    setAskNotice(null);
    askInFlightRef.current = true;
    askMutation.mutate(
      { projectId: submittedProjectId, question: trimmed },
      {
        onSuccess: (result) => {
          if (projectIdRef.current !== submittedProjectId) return;
          if (result.project_id !== submittedProjectId) return;
          setQuestion("");
          setAskNotice({ tone: "success", message: "Answer ready." });
        },
        onError: () => {
          if (projectIdRef.current !== submittedProjectId) return;
          setAskNotice({
            tone: "error",
            message: "Client Intelligence could not answer this question.",
          });
        },
        onSettled: () => {
          if (projectIdRef.current === submittedProjectId) {
            askInFlightRef.current = false;
          }
        },
      },
    );
  };

  return (
    <section
      className="mb-4 rounded-md border border-border bg-elevated/40 p-3"
      aria-label="Client Intelligence Q&A"
    >
      <div className="mb-2 flex items-center justify-between gap-2">
        <div>
          <h4 className="text-xs font-semibold text-foreground">Client Intelligence Q&A</h4>
          <p className="text-[10px] text-muted-foreground">
            Evidence-backed answers grounded in this project&apos;s governed data.
          </p>
        </div>
        <span className="rounded-full bg-secondary px-2 py-0.5 text-[10px] text-muted-foreground">
          {total}
        </span>
      </div>

      <div className="mb-3">
        <label htmlFor={questionId} className="text-[10px] font-semibold text-muted-foreground">
          Client Intelligence question
        </label>
        <textarea
          id={questionId}
          value={question}
          onChange={(event) => {
            setQuestion(event.target.value);
            if (validationError) setValidationError(null);
          }}
          disabled={askMutation.isPending}
          rows={2}
          placeholder="Ask about health, confidence, milestones, risks, or reports…"
          className="mt-1 w-full rounded border border-border bg-background px-2 py-1 text-xs leading-5"
        />
        {validationError && (
          <p role="alert" className="mt-1 text-[10px] text-[color:var(--danger)]">
            {validationError}
          </p>
        )}
        {askNotice && (
          <div
            role={askNotice.tone === "error" ? "alert" : "status"}
            aria-live="polite"
            className={`mt-1 rounded border px-2 py-1.5 text-[10px] ${
              askNotice.tone === "error"
                ? "border-[color:var(--danger)]/30 bg-[color:var(--danger)]/10 text-[color:var(--danger)]"
                : "border-[color:var(--success)]/30 bg-[color:var(--success)]/10 text-[color:var(--success)]"
            }`}
          >
            {askNotice.message}
          </div>
        )}
        <div className="mt-2">
          <CompactButton
            ariaLabel="Ask Client Intelligence"
            disabled={askMutation.isPending}
            onClick={submitQuestion}
          >
            {askMutation.isPending ? "Asking…" : "Ask Client Intelligence"}
          </CompactButton>
        </div>
      </div>

      <div aria-label="Client Intelligence query history">
        {isInitialLoading && !showHistoryItems && (
          <div role="status" aria-live="polite" className="py-3 text-xs text-muted-foreground">
            Loading Client Intelligence query history…
          </div>
        )}
        {showHistoryError && (
          <div role="alert" className="py-2 text-xs text-muted-foreground">
            Client Intelligence query history could not be loaded.{" "}
            <button
              type="button"
              className="underline"
              aria-label="Retry Client Intelligence query history"
              onClick={() => void historyQuery.refetch()}
            >
              Retry
            </button>
          </div>
        )}
        {serverHistoryUnavailable && (
          <div role="status" className="mb-2 py-1 text-[10px] text-muted-foreground">
            Showing the latest confirmed answer. Full query history is temporarily unavailable.
          </div>
        )}
        {historySource === "local_pending" && (
          <div role="status" className="mb-2 py-1 text-[10px] text-muted-foreground">
            Showing the latest confirmed answer while query history refreshes…
          </div>
        )}
        {!isInitialLoading && !showHistoryError && !showHistoryItems && (
          <div className="rounded border border-dashed border-border p-3 text-center text-xs text-muted-foreground">
            No questions have been asked for this project yet.
          </div>
        )}
        {showHistoryItems && (
          <div className="space-y-2">
            {items.map((item) => {
              const expanded = expandedIds.has(item.query_id);
              const panelId = `client-intelligence-query-panel-${item.query_id}`;
              const isUnansweredOutcome = item.answer_availability !== "answered";
              return (
                <div key={item.query_id} className="rounded border border-border bg-card">
                  <button
                    type="button"
                    aria-expanded={expanded}
                    aria-controls={panelId}
                    aria-label={
                      expanded
                        ? `Collapse answer for ${item.question}`
                        : `Expand answer for ${item.question}`
                    }
                    className="flex w-full cursor-pointer items-center justify-between gap-3 px-3 py-2 text-left"
                    onClick={() => toggleExpanded(item.query_id)}
                  >
                    <div className="min-w-0">
                      <div className="truncate text-xs font-medium">{item.question}</div>
                      <div className="text-[10px] text-muted-foreground">
                        {formatDateTime(item.created_at)} · {formatLatency(item.latency_ms)} ·{" "}
                        {labelToken(item.confidence_level)} confidence
                        {item.escalation_required ? " · Escalation required" : ""}
                      </div>
                    </div>
                    <Status value={item.answer_availability} />
                  </button>
                  {expanded && (
                    <div id={panelId} className="border-t border-border px-3 py-3">
                      {isUnansweredOutcome && (
                        <div className="mb-2 rounded border border-[color:var(--warning)]/30 bg-[color:var(--warning)]/10 px-2 py-1.5 text-[10px] text-[color:var(--warning)]">
                          {item.insufficient_evidence
                            ? "Insufficient evidence to answer this question."
                            : `Answer unavailable: ${labelToken(item.answer_availability)}.`}
                        </div>
                      )}
                      <p className="whitespace-pre-wrap text-xs leading-5 text-foreground">
                        {item.answer_text}
                      </p>
                      {item.next_step && !item.escalation_required && (
                        <p className="mt-2 text-[10px] text-muted-foreground">
                          Next step: {item.next_step}
                        </p>
                      )}
                      {item.escalation_required && (
                        <div className="mt-2 rounded border border-border bg-elevated/50 px-2 py-1.5 text-[10px]">
                          <div className="font-semibold text-foreground">Escalation required</div>
                          <p className="mt-0.5 text-muted-foreground">{item.next_step}</p>
                        </div>
                      )}
                      {item.limitations.length > 0 && <LimitationItems values={item.limitations} />}
                      <div className="mt-2 text-[10px] text-muted-foreground">
                        Latency {formatLatency(item.latency_ms)}
                        {item.model_used ? ` · Model ${item.model_used}` : ""}
                        {item.source_agents.length > 0
                          ? ` · Sources ${item.source_agents.map(labelToken).join(", ")}`
                          : ""}
                        {item.evidence_links.length > 0
                          ? ` · ${item.evidence_links.length} evidence link(s)`
                          : ""}
                      </div>
                      <div className="mt-3">
                        <div className="text-[10px] font-semibold uppercase tracking-wider text-muted-foreground">
                          Evidence
                        </div>
                        {item.evidence_links.length > 0 ? (
                          <ul className="mt-1 space-y-1 text-[10px] text-muted-foreground">
                            {item.evidence_links.map((link) => (
                              <li key={`${link.source_table}:${link.source_row_id}`}>
                                {link.source_table} · {link.description}
                              </li>
                            ))}
                          </ul>
                        ) : (
                          <p className="mt-1 text-[10px] text-muted-foreground">
                            No evidence links returned.
                          </p>
                        )}
                      </div>
                    </div>
                  )}
                </div>
              );
            })}
          </div>
        )}
        {!isInitialLoading && !showHistoryError && hasMore && (
          <div className="mt-2">
            <CompactButton
              ariaLabel="Load more Client Intelligence queries"
              disabled={isFetchingNext}
              onClick={() => void historyQuery.fetchNextPage()}
            >
              {isFetchingNext ? "Loading more…" : "Load more"}
            </CompactButton>
          </div>
        )}
      </div>
    </section>
  );
}

function ClientDetail({
  selectedProject,
  overview,
  loading,
  fetching,
  error,
  draftNotice,
  communications,
  communicationsLoading,
  communicationsError,
  pendingLifecycleKeys,
  lifecycleNotices,
  sendLiveNotice,
  onRetry,
  onRetryCommunications,
  onRefreshProjects,
  onRefreshOverview,
  onEditCommunication,
  onSubmitForReview,
  onApproveCommunication,
  onRejectCommunication,
  onSendCommunication,
}: {
  selectedProject: ProjectRead | undefined;
  overview: ClientIntelligenceOverview | undefined;
  loading: boolean;
  fetching: boolean;
  error: Error | null;
  draftNotice: { tone: "success" | "error"; message: string } | null;
  communications: ClientCommunicationDraft[];
  communicationsLoading: boolean;
  communicationsError: boolean;
  pendingLifecycleKeys: ReadonlySet<string>;
  lifecycleNotices: Record<string, LifecycleNotice>;
  sendLiveNotice: { projectId: string; message: string } | null;
  onRetry: () => void;
  onRetryCommunications: () => void;
  onRefreshProjects: () => void;
  onRefreshOverview: () => void;
  onEditCommunication: (
    communication: ClientCommunicationDraft,
    subject: string,
    bodyDraft: string,
  ) => Promise<void>;
  onSubmitForReview: (communication: ClientCommunicationDraft) => Promise<void>;
  onApproveCommunication: (communication: ClientCommunicationDraft) => Promise<void>;
  onRejectCommunication: (communication: ClientCommunicationDraft, reason: string) => Promise<void>;
  onSendCommunication: (communication: ClientCommunicationDraft) => Promise<void>;
}) {
  return (
    <>
      <SectionHeader
        title={selectedProject ? `${selectedProject.name} · Detail` : "Client Detail"}
        sub={selectedProject ? "Governed project intelligence" : "Select a project row"}
        right={
          selectedProject ? (
            <CompactButton
              onClick={onRefreshOverview}
              disabled={loading || fetching}
              ariaLabel="Refresh overview"
            >
              <RefreshCw className={`h-3 w-3 ${fetching ? "animate-spin" : ""}`} />
            </CompactButton>
          ) : null
        }
      />
      {draftNotice && (
        <div
          role={draftNotice.tone === "error" ? "alert" : "status"}
          className={`mb-3 rounded-md border px-3 py-2 text-xs ${
            draftNotice.tone === "error"
              ? "border-[color:var(--danger)]/30 bg-[color:var(--danger)]/10 text-[color:var(--danger)]"
              : "border-[color:var(--success)]/30 bg-[color:var(--success)]/10 text-[color:var(--success)]"
          }`}
        >
          {draftNotice.message}
        </div>
      )}
      {selectedProject && sendLiveNotice && sendLiveNotice.projectId === selectedProject.id && (
        <div
          role="status"
          aria-live="polite"
          className="mb-3 rounded-md border border-[color:var(--success)]/30 bg-[color:var(--success)]/10 px-3 py-2 text-xs text-[color:var(--success)]"
        >
          {sendLiveNotice.message}
        </div>
      )}
      {!selectedProject && (
        <div className="rounded-md border border-dashed border-border p-6 text-center text-xs text-muted-foreground">
          Select a project row to view governed Client Intelligence.
        </div>
      )}
      {selectedProject && (
        <>
          <DraftReportsQueue
            communications={communications}
            loading={communicationsLoading}
            error={communicationsError}
            onRetry={onRetryCommunications}
            pendingLifecycleKeys={pendingLifecycleKeys}
            lifecycleNotices={lifecycleNotices}
            selectedProjectId={selectedProject.id}
            onEdit={onEditCommunication}
            onSubmitForReview={onSubmitForReview}
            onApprove={onApproveCommunication}
            onReject={onRejectCommunication}
            onSend={onSendCommunication}
          />
          <ApprovedSentReportsHistory projectId={selectedProject.id} />
          <ClientIntelligenceQA key={selectedProject.id} projectId={selectedProject.id} />
        </>
      )}
      {selectedProject && loading && (
        <div
          role="status"
          aria-live="polite"
          className="rounded-md border border-dashed border-border p-6 text-center text-xs text-muted-foreground"
        >
          Loading Client Intelligence overview…
        </div>
      )}
      {selectedProject && error && (
        <OverviewError error={error} onRetry={onRetry} onRefreshProjects={onRefreshProjects} />
      )}
      {selectedProject && overview && !error && <CompactOverview overview={overview} />}
    </>
  );
}

export function ClientIntelligenceDashboard() {
  const queryClient = useQueryClient();
  const projectsQuery = useProjectsQuery();
  const masterQuery = useClientMasterQuery();
  const summaryQuery = useClientIntelligenceSummaryQuery();
  const projects = useMemo(() => projectsQuery.data ?? [], [projectsQuery.data]);
  const masterByProjectId = useMemo(
    () => new Map((masterQuery.data ?? []).map((row) => [row.project_id, row])),
    [masterQuery.data],
  );
  const [selectedProjectId, setSelectedProjectId] = useState<string | null>(null);
  const [searchQuery, setSearchQuery] = useState("");
  const [draftNotice, setDraftNotice] = useState<{
    tone: "success" | "error";
    message: string;
  } | null>(null);
  const [lifecycleNotices, setLifecycleNotices] = useState<Record<string, LifecycleNotice>>({});
  const [sendLiveNotice, setSendLiveNotice] = useState<{
    projectId: string;
    message: string;
  } | null>(null);
  const [pendingLifecycleKeys, setPendingLifecycleKeys] = useState<ReadonlySet<string>>(
    () => new Set(),
  );
  const pendingLifecycleRef = useRef<Set<string>>(new Set());
  const selectedProjectIdRef = useRef<string | null>(null);
  const draftMutation = useMutation({
    mutationFn: createClientIntelligenceDraft,
    onMutate: (projectId) => {
      setSelectedProjectId(projectId);
      setDraftNotice(null);
    },
    onSuccess: (draft) => {
      setDraftNotice({
        tone: "success",
        message: `Draft created: ${draft.subject}`,
      });
      void Promise.all([
        queryClient.invalidateQueries({
          queryKey: queryKeys.clientIntelligenceMaster,
          exact: true,
        }),
        queryClient.invalidateQueries({
          queryKey: queryKeys.clientIntelligenceSummary,
          exact: true,
        }),
        queryClient.invalidateQueries({
          queryKey: queryKeys.clientIntelligenceProjectSummary(draft.project_id),
          exact: true,
        }),
        queryClient.invalidateQueries({
          queryKey: queryKeys.clientIntelligenceCommunications(draft.project_id),
          exact: true,
        }),
      ]);
    },
    onError: (error) => {
      setDraftNotice({
        tone: "error",
        message:
          error instanceof ApiError
            ? error.message
            : "The evidence-backed draft could not be created.",
      });
    },
  });

  const invalidateLifecycleReads = (projectId: string) =>
    Promise.all([
      queryClient.invalidateQueries({
        queryKey: queryKeys.clientIntelligenceCommunications(projectId),
        exact: true,
      }),
      queryClient.invalidateQueries({
        queryKey: queryKeys.clientIntelligenceMaster,
        exact: true,
      }),
      queryClient.invalidateQueries({
        queryKey: queryKeys.clientIntelligenceSummary,
        exact: true,
      }),
      queryClient.invalidateQueries({
        queryKey: queryKeys.clientIntelligenceProjectSummary(projectId),
        exact: true,
      }),
      queryClient.invalidateQueries({
        queryKey: ["client-intelligence", "reports", projectId],
      }),
    ]);

  const runLifecycleAction = async (vars: LifecycleMutationVars): Promise<void> => {
    const key = lifecyclePendingKey(vars.communicationId, vars.action);
    if (pendingLifecycleRef.current.has(key)) {
      throw new Error("Lifecycle action already in progress.");
    }
    pendingLifecycleRef.current.add(key);
    setPendingLifecycleKeys(new Set(pendingLifecycleRef.current));
    setLifecycleNotices((previous) => {
      if (!(vars.communicationId in previous)) return previous;
      const next = { ...previous };
      delete next[vars.communicationId];
      return next;
    });

    const messages: Record<LifecycleAction, string> = {
      edit: "Draft updated",
      submit_for_review: "Submitted for review",
      approve: "Approved",
      reject: "Rejected",
      send: "Sent",
    };

    try {
      let result: ClientCommunicationDraft;
      switch (vars.action) {
        case "edit":
          result = await editClientIntelligenceDraft(vars.communicationId, {
            subject: vars.subject ?? "",
            body_draft: vars.body_draft ?? "",
          });
          break;
        case "submit_for_review":
          result = await submitClientIntelligenceDraftForReview(vars.communicationId, {
            body_approved: vars.body_approved ?? "",
          });
          break;
        case "approve":
          result = await approveClientIntelligenceCommunication(vars.communicationId);
          break;
        case "reject":
          result = await rejectClientIntelligenceCommunication(vars.communicationId, {
            rejection_reason: vars.rejection_reason ?? "",
          });
          break;
        case "send":
          result = await sendClientIntelligenceCommunication(vars.communicationId);
          break;
      }
      void invalidateLifecycleReads(vars.projectId);
      if (vars.action === "send") {
        setSendLiveNotice({
          projectId: vars.projectId,
          message: `Sent: ${result.subject}`,
        });
      }
      if (selectedProjectIdRef.current === vars.projectId) {
        setLifecycleNotices((previous) => ({
          ...previous,
          [vars.communicationId]: {
            projectId: vars.projectId,
            tone: "success",
            message: `${messages[vars.action]}: ${result.subject}`,
          },
        }));
      }
    } catch (error) {
      if (selectedProjectIdRef.current === vars.projectId) {
        setLifecycleNotices((previous) => ({
          ...previous,
          [vars.communicationId]: {
            projectId: vars.projectId,
            tone: "error",
            message:
              error instanceof ApiError
                ? error.message
                : "The communication lifecycle action could not be completed.",
          },
        }));
      }
      throw error;
    } finally {
      pendingLifecycleRef.current.delete(key);
      setPendingLifecycleKeys(new Set(pendingLifecycleRef.current));
    }
  };

  const effectiveProjectId =
    selectedProjectId && projects.some((project) => project.id === selectedProjectId)
      ? selectedProjectId
      : null;

  selectedProjectIdRef.current = effectiveProjectId;

  useEffect(() => {
    if (selectedProjectId !== null && effectiveProjectId === null) {
      setSelectedProjectId(null);
    }
  }, [effectiveProjectId, selectedProjectId]);

  const selectedProject = projects.find((project) => project.id === effectiveProjectId);
  // Sparkline uses the selected project when set; otherwise the first authorized project
  // so the Delivery Confidence card keeps the historical value+chart layout with real history.
  const sparklineProjectId = effectiveProjectId ?? projects[0]?.id ?? null;
  const overviewQuery = useClientIntelligenceOverviewQuery(effectiveProjectId);
  const confidenceHistoryQuery =
    useClientIntelligenceDeliveryConfidenceHistoryQuery(sparklineProjectId);
  const communicationsQuery = useClientIntelligenceCommunicationsQuery(effectiveProjectId);
  const selectedSummaryQuery = useClientIntelligenceProjectSummaryQuery(effectiveProjectId);
  const activeCapabilitySummary = effectiveProjectId
    ? selectedSummaryQuery.data
    : summaryQuery.data;
  const activeCapabilityLoading = effectiveProjectId
    ? selectedSummaryQuery.isLoading
    : summaryQuery.isLoading;
  const activeCapabilityError = effectiveProjectId
    ? selectedSummaryQuery.isError
    : summaryQuery.isError;

  const refreshProjects = () => {
    const refreshes = [
      queryClient.invalidateQueries({
        queryKey: projectsQueryOptions.queryKey,
        exact: true,
      }),
      queryClient.invalidateQueries({
        queryKey: queryKeys.clientIntelligenceSummary,
        exact: true,
      }),
      queryClient.invalidateQueries({
        queryKey: queryKeys.clientIntelligenceMaster,
        exact: true,
      }),
    ];
    if (effectiveProjectId) {
      refreshes.push(
        queryClient.invalidateQueries({
          queryKey: queryKeys.clientIntelligenceProjectSummary(effectiveProjectId),
          exact: true,
        }),
        queryClient.invalidateQueries({
          queryKey: queryKeys.clientIntelligenceCommunications(effectiveProjectId),
          exact: true,
        }),
      );
    }
    void Promise.all(refreshes);
  };

  return (
    <div className="space-y-5">
      <div
        className="grid grid-cols-2 gap-4 lg:grid-cols-4"
        data-testid="client-intelligence-summary-grid"
      >
        <DeliveryConfidenceCard
          overview={overviewQuery.data}
          selectedProjectName={selectedProject?.name}
          loading={overviewQuery.isLoading && Boolean(effectiveProjectId)}
          error={overviewQuery.isError}
          summary={summaryQuery.data?.delivery_confidence}
          summaryLoading={summaryQuery.isLoading}
          summaryError={summaryQuery.isError}
          history={confidenceHistoryQuery.isError ? undefined : confidenceHistoryQuery.data}
          historyLoading={confidenceHistoryQuery.isLoading && Boolean(sparklineProjectId)}
          historyError={confidenceHistoryQuery.isError}
          historyEnabled={Boolean(sparklineProjectId)}
        />
        <SummaryCapabilityCards
          summary={activeCapabilitySummary}
          loading={activeCapabilityLoading}
          error={activeCapabilityError}
          scopeLabel={selectedProject?.name ?? "Authorized scope"}
        />
      </div>

      <div
        className="grid grid-cols-1 gap-5 lg:grid-cols-5"
        data-testid="client-intelligence-main-grid"
      >
        <Card className="min-h-[535px] lg:col-span-3">
          {projectsQuery.isLoading || projectsQuery.isError ? (
            <>
              <SectionHeader title="Client Projects" />
              <ProjectListState
                loading={projectsQuery.isLoading}
                error={projectsQuery.isError}
                onRetry={() => void projectsQuery.refetch()}
              />
            </>
          ) : (
            <ProjectTable
              projects={projects}
              selectedProjectId={effectiveProjectId}
              overview={overviewQuery.data}
              overviewLoading={overviewQuery.isLoading}
              overviewError={overviewQuery.isError}
              masterByProjectId={masterByProjectId}
              query={searchQuery}
              onQueryChange={setSearchQuery}
              onSelect={(projectId) => {
                setSelectedProjectId(projectId);
                setDraftNotice(null);
                setSendLiveNotice(null);
              }}
              onDraft={(projectId) => {
                setSelectedProjectId(projectId);
                draftMutation.mutate(projectId);
              }}
              draftingProjectId={draftMutation.isPending ? (draftMutation.variables ?? null) : null}
              onRefresh={refreshProjects}
            />
          )}
        </Card>

        <Card className="min-h-[535px] lg:col-span-2">
          <ClientDetail
            selectedProject={selectedProject}
            overview={overviewQuery.data}
            loading={overviewQuery.isLoading}
            fetching={overviewQuery.isFetching}
            error={overviewQuery.isError ? overviewQuery.error : null}
            draftNotice={draftNotice}
            communications={communicationsQuery.data ?? []}
            communicationsLoading={communicationsQuery.isLoading}
            communicationsError={communicationsQuery.isError}
            pendingLifecycleKeys={pendingLifecycleKeys}
            lifecycleNotices={lifecycleNotices}
            sendLiveNotice={sendLiveNotice}
            onRetry={() => void overviewQuery.refetch()}
            onRetryCommunications={() => void communicationsQuery.refetch()}
            onRefreshProjects={refreshProjects}
            onRefreshOverview={() =>
              void Promise.all([
                overviewQuery.refetch(),
                selectedSummaryQuery.refetch(),
                communicationsQuery.refetch(),
                confidenceHistoryQuery.refetch(),
                queryClient.invalidateQueries({
                  queryKey: ["client-intelligence", "reports", effectiveProjectId],
                }),
                queryClient.invalidateQueries({
                  queryKey: queryKeys.clientIntelligenceQueryHistory(effectiveProjectId ?? ""),
                }),
              ])
            }
            onEditCommunication={(communication, subject, bodyDraft) =>
              runLifecycleAction({
                communicationId: communication.id,
                projectId: communication.project_id,
                action: "edit",
                subject,
                body_draft: bodyDraft,
              })
            }
            onSubmitForReview={(communication) =>
              runLifecycleAction({
                communicationId: communication.id,
                projectId: communication.project_id,
                action: "submit_for_review",
                body_approved: communication.body_draft,
              })
            }
            onApproveCommunication={(communication) =>
              runLifecycleAction({
                communicationId: communication.id,
                projectId: communication.project_id,
                action: "approve",
              })
            }
            onRejectCommunication={(communication, reason) =>
              runLifecycleAction({
                communicationId: communication.id,
                projectId: communication.project_id,
                action: "reject",
                rejection_reason: reason,
              })
            }
            onSendCommunication={(communication) =>
              runLifecycleAction({
                communicationId: communication.id,
                projectId: communication.project_id,
                action: "send",
              })
            }
          />
        </Card>
      </div>
    </div>
  );
}
