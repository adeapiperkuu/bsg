/**
 * Client published archive (`/client/reports`).
 * Uses the PM report inbox/workspace design in a sent-only, read-only configuration.
 */

import { useEffect, useState } from "react";
import { Download } from "lucide-react";

import { PageLoadingScreen } from "@/components/bsg/PageLoadingScreen";
import { ReportsInboxPanel } from "@/features/reports/ReportsInboxPanel";
import { ReportWorkspacePanel } from "@/features/reports/ReportWorkspacePanel";
import { useClientReportsQueries } from "@/features/client-reports/useClientReportsQueries";
import { userFacingReportsError } from "@/features/reports/report-utils";
import { clientReportDownloadUrl } from "@/lib/api";
import type { CommunicationCapabilities, CommunicationListItem } from "@/types/communications";

const EMPTY: CommunicationListItem[] = [];
const CLIENT_READ_ONLY_CAPABILITIES: CommunicationCapabilities = {
  canGenerateCommunications: false,
  canReviewCommunications: false,
  canApproveCommunications: false,
  canRejectCommunications: false,
  canSendCommunications: false,
  canAccessReportsWorkflow: false,
  isReportsReadOnly: true,
};

export function ClientReportsPage() {
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [mobileWorkspaceOpen, setMobileWorkspaceOpen] = useState(false);
  const { listQuery, detailQuery } = useClientReportsQueries(selectedId);

  const reports = listQuery.data?.data ?? EMPTY;
  const selected = reports.find((report) => report.id === selectedId) ?? null;
  const detail = detailQuery.data ?? null;

  useEffect(() => {
    if (listQuery.isLoading || listQuery.isError) return;
    if (selectedId && reports.some((report) => report.id === selectedId)) return;
    if (selectedId && detail?.id === selectedId) return;
    if (reports.length === 0) {
      if (selectedId !== null) setSelectedId(null);
      return;
    }
    setSelectedId(reports[0]?.id ?? null);
  }, [detail?.id, listQuery.isError, listQuery.isLoading, reports, selectedId]);

  const listError = listQuery.isError
    ? userFacingReportsError(listQuery.error, "Failed to load reports.")
    : null;
  const detailError = detailQuery.isError
    ? userFacingReportsError(detailQuery.error, "Failed to load this report.")
    : null;

  if (listQuery.isLoading && reports.length === 0 && !listQuery.isError) {
    return <PageLoadingScreen />;
  }

  return (
    <div className="grid grid-cols-1 gap-5 lg:grid-cols-3">
      <ReportsInboxPanel
        reports={reports}
        selectedId={selectedId}
        activeFilter="sent"
        onFilterChange={() => undefined}
        onSelect={(id) => {
          setSelectedId(id);
          setMobileWorkspaceOpen(true);
        }}
        onGenerateClick={() => undefined}
        canGenerate={false}
        isLoading={listQuery.isLoading || listQuery.isFetching}
        isError={listQuery.isError}
        errorMessage={listError}
        onRetry={() => void listQuery.refetch()}
        showFilters={false}
        subtitle="Sent reports for your organisation"
        emptyTitle="No reports yet"
        emptyBody="Sent reports from your delivery team will appear here."
        hiddenOnMobile={mobileWorkspaceOpen && Boolean(selectedId)}
      />

      <div
        className={
          mobileWorkspaceOpen || !selectedId ? "lg:col-span-2" : "hidden lg:block lg:col-span-2"
        }
      >
        {mobileWorkspaceOpen ? (
          <button
            type="button"
            className="mb-3 rounded border border-border px-2.5 py-1 text-[11px] font-medium lg:hidden"
            onClick={() => setMobileWorkspaceOpen(false)}
          >
            Back to inbox
          </button>
        ) : null}
        {detail?.status === "sent" ? (
          <div className="mb-3 flex flex-wrap items-center justify-between gap-2 rounded-lg border border-border bg-card px-4 py-3">
            <div>
              <p className="text-xs font-semibold">Download report</p>
              <p className="mt-0.5 text-[10px] text-muted-foreground">
                Export this published report for offline use.
              </p>
            </div>
            <div className="flex gap-2">
              <a
                href={clientReportDownloadUrl(detail.id, "pdf")}
                className="inline-flex h-8 items-center gap-1.5 rounded-md border border-border px-3 text-[11px] font-semibold hover:bg-elevated"
              >
                <Download className="h-3.5 w-3.5" />
                PDF
              </a>
              <a
                href={clientReportDownloadUrl(detail.id, "csv")}
                className="inline-flex h-8 items-center gap-1.5 rounded-md border border-border px-3 text-[11px] font-semibold hover:bg-elevated"
              >
                <Download className="h-3.5 w-3.5" />
                CSV
              </a>
            </div>
          </div>
        ) : null}
        <ReportWorkspacePanel
          report={detail}
          projectName={selected?.project_name}
          isLoading={Boolean(selectedId) && detailQuery.isLoading && !detail}
          isError={Boolean(selectedId) && detailQuery.isError && !detail}
          errorMessage={detailError}
          onRetry={() => void detailQuery.refetch()}
          capabilities={CLIENT_READ_ONLY_CAPABILITIES}
        />
      </div>
    </div>
  );
}
