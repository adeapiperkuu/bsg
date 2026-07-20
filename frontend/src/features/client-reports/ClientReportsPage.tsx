/**
 * Client published archive (`/client/reports`).
 * Uses the PM report inbox/workspace design in a sent-only, read-only configuration.
 */

import { useEffect, useState } from "react";

import { ReportsInboxPanel } from "@/features/reports/ReportsInboxPanel";
import { ReportWorkspacePanel } from "@/features/reports/ReportWorkspacePanel";
import { useClientReportsQueries } from "@/features/client-reports/useClientReportsQueries";
import { userFacingReportsError } from "@/features/reports/report-utils";
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
