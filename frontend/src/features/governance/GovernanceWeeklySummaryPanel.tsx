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
import { DeliveryMarkdown } from "@/components/delivery/delivery-markdown";
import { Button } from "@/components/ui/button";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import {
  approveGovernanceWeeklySummary,
  exportGovernanceWeeklySummary,
  generateGovernanceWeeklySummary,
  governanceWeeklySummariesQueryOptions,
  governanceWeeklySummaryQueryOptions,
} from "@/lib/queries/governance";
import { queryKeys } from "@/lib/queries/keys";
import type { GovernanceWeeklySummary } from "@/types/governance";

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

export function GovernanceWeeklySummaryPanel({ canManage }: { canManage: boolean }) {
  const queryClient = useQueryClient();
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [downloading, setDownloading] = useState<"pdf" | "docx" | null>(null);

  const latestQuery = useQuery(governanceWeeklySummaryQueryOptions);
  const historyQuery = useQuery(governanceWeeklySummariesQueryOptions);
  const versions = useMemo(() => {
    if (historyQuery.data?.length) {
      return historyQuery.data.map((summary) =>
        summary.id === latestQuery.data?.id ? latestQuery.data : summary,
      );
    }
    return latestQuery.data ? [latestQuery.data] : [];
  }, [historyQuery.data, latestQuery.data]);
  const selected = useMemo(
    () =>
      versions.find((summary) => summary.id === selectedId) ??
      latestQuery.data ??
      versions[0] ??
      null,
    [latestQuery.data, selectedId, versions],
  );

  const refreshSummaryCache = async (summary: GovernanceWeeklySummary) => {
    queryClient.setQueryData(queryKeys.governanceWeeklySummary, summary);
    setSelectedId(summary.id);
    await queryClient.invalidateQueries({ queryKey: queryKeys.governanceWeeklySummaries });
  };
  const generateMutation = useMutation({
    mutationFn: generateGovernanceWeeklySummary,
    onSuccess: async (summary) => {
      await refreshSummaryCache(summary);
      toast.success("Weekly governance summary generated for review.");
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
  const busy = generateMutation.isPending || approveMutation.isPending;

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
          <Select
            value={selected?.id ?? ""}
            onValueChange={setSelectedId}
            disabled={versions.length === 0 || historyQuery.isLoading}
          >
            <SelectTrigger className="h-8 w-56 text-xs">
              <SelectValue placeholder="Version history" />
            </SelectTrigger>
            <SelectContent data-governance-select-content>
              {versions.map((summary, index) => (
                <SelectItem key={summary.id} value={summary.id}>
                  v{versions.length - index} - {formatWeek(summary.summary_week)} -{" "}
                  {summary.status === "approved" ? "Approved" : "Draft"}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        }
      />

      <div className="flex min-h-0 flex-1 flex-col">
        <div className="flex min-h-0 flex-1 flex-col rounded-md border border-border bg-elevated p-3">
          {latestQuery.isLoading || historyQuery.isLoading ? (
            <div
              role="status"
              aria-label="Loading weekly governance summary"
              className="flex flex-1 items-center gap-2 text-sm text-muted-foreground"
            >
              <Loader2 className="h-4 w-4 animate-spin" />
              Loading weekly summaries...
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
          ) : selected ? (
            <div className="flex min-h-0 flex-1 flex-col">
              <div className="mb-3 flex flex-wrap items-center gap-2">
                <StatusPill status={selected.status === "approved" ? "Approved" : "Draft"} />
                {selected.generated_by_ai && <AiBadge label="AI Generated" />}
                <span className="text-[10px] text-muted-foreground">
                  {formatWeek(selected.summary_week)} generated{" "}
                  {formatTimestamp(selected.created_at)}
                </span>
                <span className="text-[10px] text-muted-foreground">
                  {selected.evidence_links.length} evidence item
                  {selected.evidence_links.length === 1 ? "" : "s"}
                </span>
              </div>
              {selected.approved_at && (
                <p className="mb-2 text-[10px] text-muted-foreground">
                  Approved {formatTimestamp(selected.approved_at)}
                  {selected.approved_by_name ? ` by ${selected.approved_by_name}` : ""}
                </p>
              )}
              <div className="min-h-0 flex-1 overflow-y-auto rounded border border-border bg-background/60 p-3">
                <DeliveryMarkdown content={selected.summary_text} />
              </div>
              <div className="mt-3 flex shrink-0 flex-wrap items-center gap-2">
                <Button
                  type="button"
                  size="sm"
                  variant="outline"
                  className="h-7 text-[11px]"
                  disabled={downloading === "pdf"}
                  onClick={() => void download(selected, "pdf")}
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
                  disabled={downloading === "docx"}
                  onClick={() => void download(selected, "docx")}
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
                  {selected.status === "approved"
                    ? "Official governance summary"
                    : "Human approval required before this summary becomes official"}
                </span>
              </div>
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
                {generateMutation.isPending ? (
                  <Loader2 className="mr-1 h-3.5 w-3.5 animate-spin" />
                ) : selected ? (
                  <RefreshCw className="mr-1 h-3.5 w-3.5" />
                ) : (
                  <Sparkles className="mr-1 h-3.5 w-3.5" />
                )}
                {selected ? "Generate new version" : "Generate summary"}
              </Button>
            )}
            {canManage && selected?.status === "draft" && (
              <Button
                type="button"
                size="sm"
                disabled={busy}
                onClick={() => approveMutation.mutate(selected.id)}
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
