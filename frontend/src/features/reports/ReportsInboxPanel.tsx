import { useEffect, useState, type RefObject } from "react";
import { ChevronDown, ChevronRight } from "lucide-react";

import { Card, SectionHeader, StatusPill } from "@/components/bsg/widgets";
import { Skeleton } from "@/components/ui/skeleton";
import {
  COMMUNICATION_STATUS_FILTER_LABELS,
  COMMUNICATION_STATUS_LABELS,
  REPORT_INBOX_FILTERS,
  statusPillFor,
  typeLabel,
  type ReportInboxFilter,
} from "@/features/reports/report-status";
import { groupReportsByClientAndProject, reportListDate } from "@/features/reports/report-utils";
import type { CommunicationListItem } from "@/types/communications";

export interface ReportsInboxPanelProps {
  reports: CommunicationListItem[];
  selectedId: string | null;
  activeFilter: ReportInboxFilter;
  onFilterChange: (filter: ReportInboxFilter) => void;
  onSelect: (reportId: string) => void;
  onGenerateClick: () => void;
  canGenerate: boolean;
  isLoading: boolean;
  isError: boolean;
  errorMessage: string | null;
  onRetry: () => void;
  /** Read-only consumers can hide workflow filters while retaining the PM inbox design. */
  showFilters?: boolean;
  subtitle?: string;
  emptyTitle?: string;
  emptyBody?: string;
  /** Mobile master-detail: hide when workspace is focused. */
  hiddenOnMobile?: boolean;
  generateButtonRef?: RefObject<HTMLButtonElement | null>;
}

function InboxSkeleton() {
  return (
    <ul className="space-y-1.5" aria-busy="true" aria-label="Loading reports">
      {Array.from({ length: 6 }).map((_, i) => (
        <li key={i} className="rounded border border-border px-2.5 py-2">
          <Skeleton className="h-3 w-48" />
          <Skeleton className="mt-2 h-2.5 w-32" />
        </li>
      ))}
    </ul>
  );
}

function emptyCopy(filter: ReportInboxFilter): { title: string; body: string } {
  if (filter === "all") {
    return {
      title: "No reports yet",
      body: "Generate your first weekly summary.",
    };
  }
  const label = COMMUNICATION_STATUS_FILTER_LABELS[filter].toLowerCase();
  return {
    title: `No ${label} reports found.`,
    body: "Try another filter or generate a new report.",
  };
}

function toggleId(ids: Set<string>, id: string): Set<string> {
  const next = new Set(ids);
  if (next.has(id)) next.delete(id);
  else next.add(id);
  return next;
}

export function ReportsInboxPanel({
  reports,
  selectedId,
  activeFilter,
  onFilterChange,
  onSelect,
  onGenerateClick,
  canGenerate,
  isLoading,
  isError,
  errorMessage,
  onRetry,
  showFilters = true,
  subtitle,
  emptyTitle,
  emptyBody,
  hiddenOnMobile = false,
  generateButtonRef,
}: ReportsInboxPanelProps) {
  const empty = emptyCopy(activeFilter);
  const groups = groupReportsByClientAndProject(reports);
  const showClientHeaders = groups.length > 1;

  const [expandedClients, setExpandedClients] = useState<Set<string>>(() => new Set());
  const [expandedProjects, setExpandedProjects] = useState<Set<string>>(() => new Set());

  // Clients stay open by default; only the selected (or first) project expands.
  useEffect(() => {
    if (reports.length === 0) return;

    const orgIds = new Set(reports.map((r) => r.org_id || "unknown"));
    setExpandedClients((prev) => {
      let changed = false;
      const next = new Set(prev);
      for (const id of orgIds) {
        if (!next.has(id)) {
          next.add(id);
          changed = true;
        }
      }
      return changed ? next : prev;
    });

    if (selectedId) {
      const selected = reports.find((r) => r.id === selectedId);
      if (!selected) return;
      setExpandedProjects((prev) => {
        if (prev.has(selected.project_id)) return prev;
        const next = new Set(prev);
        next.add(selected.project_id);
        return next;
      });
      return;
    }

    const firstProjectId = reports[0]?.project_id;
    if (!firstProjectId) return;
    setExpandedProjects((prev) => (prev.size === 0 ? new Set([firstProjectId]) : prev));
  }, [reports, selectedId]);

  return (
    <Card className={`lg:col-span-1 ${hiddenOnMobile ? "hidden lg:block" : ""}`}>
      <SectionHeader
        title="Reports"
        sub={subtitle}
        right={
          canGenerate ? (
            <button
              ref={generateButtonRef}
              type="button"
              onClick={onGenerateClick}
              className="rounded bg-[color:var(--brand)] px-2.5 py-1 text-[11px] font-medium text-[color:var(--brand-foreground)]"
              aria-label="Generate Report"
            >
              Generate Report
            </button>
          ) : null
        }
      />
      {showFilters ? (
        <div
          className="mb-3 flex flex-wrap gap-1 text-[11px]"
          role="tablist"
          aria-label="Report status filters"
        >
          {REPORT_INBOX_FILTERS.map((key) => {
            const selected = activeFilter === key;
            return (
              <button
                key={key}
                type="button"
                role="tab"
                aria-selected={selected}
                onClick={() => onFilterChange(key)}
                className={`rounded border border-border bg-elevated px-2 py-0.5 ${
                  selected ? "ring-1 ring-[color:var(--brand)]" : ""
                }`}
              >
                {COMMUNICATION_STATUS_FILTER_LABELS[key]}
              </button>
            );
          })}
        </div>
      ) : null}

      {isError ? (
        <div className="rounded-md border border-border bg-elevated p-4 text-xs" role="alert">
          <p className="text-muted-foreground">{errorMessage ?? "Failed to load reports."}</p>
          <button
            type="button"
            onClick={onRetry}
            className="mt-2 rounded border border-border px-2.5 py-1 text-[11px] font-medium"
          >
            Retry
          </button>
        </div>
      ) : isLoading && reports.length === 0 ? (
        <InboxSkeleton />
      ) : reports.length === 0 ? (
        <div className="rounded-md border border-border bg-elevated p-4 text-xs text-muted-foreground">
          <p className="font-medium text-foreground">{emptyTitle ?? empty.title}</p>
          <p className="mt-1">{emptyBody ?? empty.body}</p>
          {canGenerate && activeFilter === "all" ? (
            <button
              type="button"
              onClick={onGenerateClick}
              className="mt-3 rounded bg-[color:var(--brand)] px-2.5 py-1 text-[11px] font-medium text-[color:var(--brand-foreground)]"
            >
              Generate Report
            </button>
          ) : null}
        </div>
      ) : (
        <div className="space-y-2 text-xs" role="listbox" aria-label="Reports inbox">
          {groups.map((client) => {
            const clientOpen = !showClientHeaders || expandedClients.has(client.orgId);
            return (
              <div key={client.orgId} className="rounded border border-border">
                {showClientHeaders ? (
                  <button
                    type="button"
                    className="flex w-full items-center gap-1.5 px-2.5 py-2 text-left font-medium"
                    aria-expanded={clientOpen}
                    onClick={() => setExpandedClients((prev) => toggleId(prev, client.orgId))}
                  >
                    {clientOpen ? (
                      <ChevronDown className="size-3.5 shrink-0 text-muted-foreground" />
                    ) : (
                      <ChevronRight className="size-3.5 shrink-0 text-muted-foreground" />
                    )}
                    <span className="min-w-0 flex-1 truncate">{client.orgName}</span>
                    <span className="shrink-0 text-[10px] font-normal text-muted-foreground">
                      {client.reportCount}
                    </span>
                  </button>
                ) : null}

                {clientOpen ? (
                  <div className={showClientHeaders ? "border-t border-border" : ""}>
                    {client.projects.map((project) => {
                      const projectOpen = expandedProjects.has(project.projectId);
                      const projectHasSelected = project.reports.some((r) => r.id === selectedId);
                      return (
                        <div
                          key={project.projectId}
                          className={
                            showClientHeaders ? "border-b border-border last:border-b-0" : ""
                          }
                        >
                          <button
                            type="button"
                            className={`flex w-full items-center gap-1.5 px-2.5 py-1.5 text-left ${
                              showClientHeaders ? "pl-4" : ""
                            } ${projectHasSelected ? "bg-elevated/60" : ""}`}
                            aria-expanded={projectOpen}
                            onClick={() =>
                              setExpandedProjects((prev) => toggleId(prev, project.projectId))
                            }
                          >
                            {projectOpen ? (
                              <ChevronDown className="size-3.5 shrink-0 text-muted-foreground" />
                            ) : (
                              <ChevronRight className="size-3.5 shrink-0 text-muted-foreground" />
                            )}
                            <span className="min-w-0 flex-1 truncate font-medium">
                              {project.projectName}
                            </span>
                            <span className="shrink-0 text-[10px] text-muted-foreground">
                              {project.reports.length}
                            </span>
                          </button>

                          {projectOpen ? (
                            <ul className="space-y-1 px-2 pb-2 pt-0.5">
                              {project.reports.map((r) => {
                                const selected = selectedId === r.id;
                                return (
                                  <li key={r.id} role="option" aria-selected={selected}>
                                    <button
                                      type="button"
                                      onClick={() => onSelect(r.id)}
                                      className={`flex w-full items-center justify-between gap-2 rounded border border-border px-2 py-1.5 text-left ${
                                        showClientHeaders ? "ml-2" : ""
                                      } ${
                                        selected
                                          ? "bg-elevated ring-1 ring-[color:var(--brand)]"
                                          : ""
                                      }`}
                                    >
                                      <span className="min-w-0">
                                        <div className="truncate font-medium">{r.subject}</div>
                                        <div className="truncate text-[10px] text-muted-foreground">
                                          {typeLabel(r.comm_type)} · {reportListDate(r)}
                                        </div>
                                      </span>
                                      <span className="flex shrink-0 flex-col items-end gap-0.5">
                                        <StatusPill status={statusPillFor(r.status)} />
                                        <span className="text-[10px] text-muted-foreground">
                                          {COMMUNICATION_STATUS_LABELS[r.status]}
                                        </span>
                                      </span>
                                    </button>
                                  </li>
                                );
                              })}
                            </ul>
                          ) : null}
                        </div>
                      );
                    })}
                  </div>
                ) : null}
              </div>
            );
          })}
        </div>
      )}
    </Card>
  );
}
