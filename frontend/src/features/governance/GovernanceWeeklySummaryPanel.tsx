import { useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  AlertCircle,
  CalendarDays,
  Check,
  Download,
  Loader2,
  RefreshCw,
  ShieldCheck,
  Sparkles,
} from "lucide-react";
import { toast } from "sonner";

import { AiBadge, Card, SectionHeader, StatusPill } from "@/components/bsg/widgets";
import { ReportExportButtons } from "@/components/bsg/reports";
import { DeliveryMarkdown } from "@/components/delivery/delivery-markdown";
import { Button } from "@/components/ui/button";
import { GovernanceJobProgress } from "@/features/governance/GovernanceJobProgress";
import { useGovernanceJob } from "@/features/governance/useGovernanceJob";
import {
  approveGovernanceWeeklySummary,
  exportGovernanceWeeklySummary,
  generateGovernanceWeeklySummary,
  getGovernanceWeeklySummaryById,
  governanceWeeklySummariesQueryOptions,
  governanceWeeklySummaryDetailQueryOptions,
  governanceWeeklySummaryQueryOptions,
} from "@/lib/queries/governance";
import { queryKeys } from "@/lib/queries/keys";
import type { GovernanceWeeklySummary, GovernanceWeeklySummaryListItem } from "@/types/governance";

function formatTimestamp(value: string | null): string {
  if (!value) return "-";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return new Intl.DateTimeFormat(undefined, {
    dateStyle: "medium",
    timeStyle: "short",
  }).format(date);
}

function formatWeek(value: string): string {
  const date = new Date(`${value}T00:00:00`);
  return Number.isNaN(date.getTime())
    ? value
    : `Week of ${new Intl.DateTimeFormat(undefined, { dateStyle: "medium" }).format(date)}`;
}

function downloadBlob(blob: Blob, filename: string) {
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = filename;
  document.body.appendChild(anchor);
  anchor.click();
  anchor.remove();
  URL.revokeObjectURL(url);
}

function filenameFor(summary: GovernanceWeeklySummary, format: "pdf" | "docx"): string {
  return `governance_weekly_summary_${summary.summary_week}.${format}`;
}

type WeeklySummaryVersion = GovernanceWeeklySummary | GovernanceWeeklySummaryListItem;

function evidenceCount(summary: WeeklySummaryVersion): number {
  return "evidence_links" in summary ? summary.evidence_links.length : summary.evidence_link_count;
}

export function GovernanceWeeklySummaryPanel({ canManage }: { canManage: boolean }) {
  const queryClient = useQueryClient();
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [downloading, setDownloading] = useState<"pdf" | "docx" | null>(null);
  const [historyRequested, setHistoryRequested] = useState(false);

  const latestQuery = useQuery(governanceWeeklySummaryQueryOptions);
  const historyQuery = useQuery({
    ...governanceWeeklySummariesQueryOptions,
    enabled: historyRequested,
  });
  const versions = useMemo(() => {
    const latest = latestQuery.data;
    const history = historyQuery.data ?? [];
    if (history.length) {
      const byId = new Map<string, WeeklySummaryVersion>();
      for (const summary of history) byId.set(summary.id, summary);
      if (latest) byId.set(latest.id, latest);
      const ordered = history.map((summary) => byId.get(summary.id) ?? summary);
      if (latest && !history.some((summary) => summary.id === latest.id)) ordered.unshift(latest);
      return ordered;
    }
    return latest ? [latest] : [];
  }, [historyQuery.data, latestQuery.data]);
  const selectedVersion = useMemo(
    () =>
      versions.find((summary) => summary.id === selectedId) ??
      latestQuery.data ??
      versions[0] ??
      null,
    [latestQuery.data, selectedId, versions],
  );
  const selectedDetailId =
    selectedVersion?.id && selectedVersion.id !== latestQuery.data?.id ? selectedVersion.id : null;
  const selectedDetailQuery = useQuery({
    ...governanceWeeklySummaryDetailQueryOptions(selectedDetailId ?? "__none__"),
    enabled: Boolean(selectedDetailId),
  });
  const selected =
    selectedDetailId != null ? (selectedDetailQuery.data ?? null) : (latestQuery.data ?? null);
  const selectedMeta = selected ?? selectedVersion ?? latestQuery.data ?? null;
  const selectedDetailLoading = Boolean(selectedDetailId) && selectedDetailQuery.isLoading;
  const selectedDetailError = Boolean(selectedDetailId) && selectedDetailQuery.isError;

  const hydrateGeneratedSummary = async (summaryId: string) => {
    const summary = await getGovernanceWeeklySummaryById(summaryId);
    setSelectedId(summary.id);
    queryClient.setQueryData(queryKeys.governanceWeeklySummary, summary);
    queryClient.setQueryData(queryKeys.governanceWeeklySummaryDetail(summary.id), summary);
    queryClient.setQueryData<GovernanceWeeklySummaryListItem[] | undefined>(
      queryKeys.governanceWeeklySummaries,
      (existing) => {
        if (!existing) return existing;
        const next = {
          id: summary.id,
          org_id: summary.org_id,
          summary_week: summary.summary_week,
          status: summary.status,
          generated_by_ai: summary.generated_by_ai,
          approved_by: summary.approved_by,
          approved_at: summary.approved_at,
          created_at: summary.created_at,
          updated_at: summary.updated_at,
          evidence_link_count: summary.evidence_link_count ?? summary.evidence_links.length,
          approved_by_name: summary.approved_by_name,
        };
        return existing.some((row) => row.id === summary.id)
          ? existing.map((row) => (row.id === summary.id ? next : row))
          : [next, ...existing];
      },
    );
    await Promise.all([
      queryClient.invalidateQueries({
        queryKey: queryKeys.governanceWeeklySummary,
        refetchType: "inactive",
      }),
      queryClient.invalidateQueries({
        queryKey: queryKeys.governanceWeeklySummaries,
        refetchType: "inactive",
      }),
    ]);
  };

  const refreshSummaryCache = async (summary: GovernanceWeeklySummary) => {
    setSelectedId(summary.id);
    queryClient.setQueryData(queryKeys.governanceWeeklySummaryDetail(summary.id), summary);
    if (latestQuery.data?.id === summary.id) {
      queryClient.setQueryData(queryKeys.governanceWeeklySummary, summary);
    }
    await Promise.all([
      queryClient.invalidateQueries({ queryKey: queryKeys.governanceWeeklySummary }),
      queryClient.invalidateQueries({ queryKey: queryKeys.governanceWeeklySummaries }),
      queryClient.invalidateQueries({
        queryKey: queryKeys.governanceWeeklySummaryDetail(summary.id),
      }),
    ]);
  };
  const generationJob = useGovernanceJob({
    jobType: "weekly_summary_generate",
    enabled: canManage,
    onSucceeded: async (job) => {
      if (job.result_record_id) {
        await hydrateGeneratedSummary(job.result_record_id);
      } else {
        await queryClient.invalidateQueries({ queryKey: queryKeys.governanceWeeklySummary });
        await queryClient.invalidateQueries({ queryKey: queryKeys.governanceWeeklySummaries });
      }
      toast.success("Weekly governance summary generated for review.");
    },
  });
  const generateMutation = useMutation({
    mutationFn: generateGovernanceWeeklySummary,
    onSuccess: (started) => {
      generationJob.track(started);
      toast.message(
        started.deduplicated
          ? "Weekly summary job already active."
          : "Weekly summary generation queued.",
      );
    },
    onError: (error) => toast.error(error instanceof Error ? error.message : "Generation failed."),
  });
  const approveMutation = useMutation({
    mutationFn: approveGovernanceWeeklySummary,
    onSuccess: async (summary) => {
      await refreshSummaryCache(summary);
      toast.success("Weekly governance summary approved.");
    },
    onError: (error) => toast.error(error instanceof Error ? error.message : "Approval failed."),
  });
  const busy = generationJob.active || generateMutation.isPending || approveMutation.isPending;

  const download = async (summary: GovernanceWeeklySummary, format: "pdf" | "docx") => {
    setDownloading(format);
    try {
      const blob = await exportGovernanceWeeklySummary(summary.id, format);
      downloadBlob(blob, filenameFor(summary, format));
    } catch (error) {
      toast.error(
        error instanceof Error ? error.message : `Failed to export ${format.toUpperCase()}.`,
      );
    } finally {
      setDownloading(null);
    }
  };

  return (
    <Card id="governance-this-week" className="flex h-[640px] flex-col overflow-hidden">
      <SectionHeader
        title="Governance This Week"
        sub="AI-generated drafts, approval workflow, version history, and exports"
        right={
          <select
            aria-label="Weekly summary version history"
            className="h-8 w-56 rounded-md border border-input bg-transparent px-3 py-1 text-xs shadow-sm focus:outline-none focus:ring-1 focus:ring-ring disabled:cursor-not-allowed disabled:opacity-50"
            value={selectedMeta?.id ?? ""}
            onFocus={() => setHistoryRequested(true)}
            onMouseDown={() => setHistoryRequested(true)}
            onChange={(event) => {
              setSelectedId(event.target.value);
              setHistoryRequested(true);
            }}
            disabled={latestQuery.isLoading || (versions.length === 0 && historyQuery.isLoading)}
          >
            {versions.length === 0 && <option value="">Version history</option>}
            {versions.map((summary, index) => (
              <option key={summary.id} value={summary.id}>
                v{versions.length - index} - {formatWeek(summary.summary_week)} -{" "}
                {summary.status === "approved" ? "Approved" : "Draft"}
              </option>
            ))}
            {historyQuery.isLoading && (
              <option value="__loading_weekly_history__" disabled>
                Loading history...
              </option>
            )}
            {historyRequested && !historyQuery.isLoading && versions.length === 0 && (
              <option value="__empty_weekly_history__" disabled>
                No history available
              </option>
            )}
          </select>
        }
      />

      <div className="flex min-h-0 flex-1 flex-col">
        <div className="mb-3">
          <GovernanceJobProgress
            job={generationJob.job}
            onCancel={generationJob.cancel}
            onRetry={generationJob.retry}
            busy={generationJob.controlBusy}
          />
        </div>
        <div className="flex min-h-0 flex-1 flex-col rounded-md border border-border bg-elevated p-3">
          {latestQuery.isLoading ? (
            <div
              role="status"
              aria-label="Loading weekly governance summary"
              className="flex flex-1 items-center justify-center text-muted-foreground"
            >
              <Loader2 className="h-4 w-4 animate-spin" />
            </div>
          ) : latestQuery.isError ? (
            <div className="flex flex-1 flex-col items-center justify-center gap-3 text-center">
              <AlertCircle className="h-6 w-6 text-[color:var(--danger)]" />
              <div>
                <p className="text-sm font-medium">Weekly summary is unavailable</p>
                <p className="text-xs text-muted-foreground">
                  The rest of Governance remains available.
                </p>
              </div>
              <Button size="sm" variant="outline" onClick={() => void latestQuery.refetch()}>
                Retry
              </Button>
            </div>
          ) : selectedMeta ? (
            <div className="flex min-h-0 flex-1 flex-col">
              <div className="mb-3 flex flex-wrap items-center gap-2">
                <StatusPill status={selectedMeta.status === "approved" ? "Approved" : "Draft"} />
                {selectedMeta.generated_by_ai && <AiBadge label="AI Generated" />}
                <span className="text-[10px] text-muted-foreground">
                  {formatWeek(selectedMeta.summary_week)} generated{" "}
                  {formatTimestamp(selectedMeta.created_at)}
                </span>
                <span className="text-[10px] text-muted-foreground">
                  {evidenceCount(selectedMeta)} evidence item
                  {evidenceCount(selectedMeta) === 1 ? "" : "s"}
                </span>
                {historyQuery.isFetching && historyRequested && (
                  <span className="flex items-center gap-1 text-[10px] text-muted-foreground">
                    <Loader2 className="h-3 w-3 animate-spin" />
                    Loading history
                  </span>
                )}
              </div>
              {selectedMeta.approved_at && (
                <p className="mb-2 text-[10px] text-muted-foreground">
                  Approved {formatTimestamp(selectedMeta.approved_at)}
                  {selectedMeta.approved_by_name ? ` by ${selectedMeta.approved_by_name}` : ""}
                </p>
              )}
              <div className="min-h-0 flex-1 overflow-y-auto rounded border border-border bg-background/60 p-3">
                {selectedDetailLoading ? (
                  <div
                    role="status"
                    aria-label="Loading selected weekly governance summary"
                    className="flex h-full items-center justify-center text-muted-foreground"
                  >
                    <Loader2 className="h-4 w-4 animate-spin" />
                  </div>
                ) : selectedDetailError ? (
                  <div className="space-y-2 text-sm text-muted-foreground">
                    <p>Could not load the selected weekly summary.</p>
                    <Button
                      type="button"
                      variant="outline"
                      size="sm"
                      className="h-7 text-[11px]"
                      onClick={() => void selectedDetailQuery.refetch()}
                    >
                      Retry
                    </Button>
                  </div>
                ) : selected ? (
                  <DeliveryMarkdown content={selected.summary_text} />
                ) : null}
              </div>
              <div className="mt-3 flex shrink-0 flex-wrap items-center gap-2">
                <Button
                  type="button"
                  size="sm"
                  variant="outline"
                  className="h-7 text-[11px]"
                  disabled={!selected || downloading === "pdf"}
                  onClick={() => selected && void download(selected, "pdf")}
                >
                  {downloading === "pdf" ? (
                    <Loader2 className="mr-1 h-3 w-3 animate-spin" />
                  ) : (
                    <Download className="mr-1 h-3 w-3" />
                  )}
                  PDF
                </Button>
                <Button
                  type="button"
                  size="sm"
                  variant="outline"
                  className="h-7 text-[11px]"
                  disabled={!selected || downloading === "docx"}
                  onClick={() => selected && void download(selected, "docx")}
                >
                  {downloading === "docx" ? (
                    <Loader2 className="mr-1 h-3 w-3 animate-spin" />
                  ) : (
                    <Download className="mr-1 h-3 w-3" />
                  )}
                  DOCX
                </Button>
                <span className="flex items-center gap-1 text-[10px] text-muted-foreground">
                  <ShieldCheck className="h-3.5 w-3.5" />
                  {selectedMeta.status === "approved"
                    ? "Official governance summary"
                    : "Human approval required before this summary becomes official"}
                </span>
              </div>
              {selected?.platform_report_id ? (
                <div className="mt-2">
                  <ReportExportButtons reportId={selected.platform_report_id} />
                </div>
              ) : null}
            </div>
          ) : (
            <div className="flex flex-1 flex-col items-center justify-center text-center">
              <CalendarDays className="h-7 w-7 text-muted-foreground" />
              <p className="mt-2 text-sm font-medium">No weekly governance summary yet</p>
              <p className="mt-1 text-xs text-muted-foreground">
                {canManage
                  ? "Generate a draft when this week's governance evidence is ready."
                  : "An approved summary will appear here when available."}
              </p>
            </div>
          )}

          <div className="mt-3 flex shrink-0 flex-wrap gap-2">
            {canManage && (
              <Button
                type="button"
                size="sm"
                disabled={busy}
                onClick={() => generateMutation.mutate()}
              >
                {generateMutation.isPending || generationJob.active ? (
                  <Loader2 className="mr-1 h-3.5 w-3.5 animate-spin" />
                ) : selectedMeta ? (
                  <RefreshCw className="mr-1 h-3.5 w-3.5" />
                ) : (
                  <Sparkles className="mr-1 h-3.5 w-3.5" />
                )}
                {selectedMeta ? "Generate new version" : "Generate summary"}
              </Button>
            )}
            {canManage && selectedMeta?.status === "draft" && (
              <Button
                type="button"
                size="sm"
                disabled={busy}
                onClick={() => approveMutation.mutate(selectedMeta.id)}
              >
                {approveMutation.isPending ? (
                  <Loader2 className="mr-1 h-3.5 w-3.5 animate-spin" />
                ) : (
                  <Check className="mr-1 h-3.5 w-3.5" />
                )}
                Approve summary
              </Button>
            )}
          </div>
        </div>
      </div>
    </Card>
  );
}
