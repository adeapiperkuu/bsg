/**
 * PM Reports workflow console (`/reports`).
 *
 * Product boundary (do not merge with `/client/reports`):
 * - `/reports` — PM workflow: draft, in_review, approved, sent, rejected + lifecycle actions
 * - `/client/reports` — client published archive: sent communications only, read-only
 */

import { useEffect, useRef, useState } from "react";
import { getRouteApi, useNavigate } from "@tanstack/react-router";

import { PageLoadingScreen } from "@/components/bsg/PageLoadingScreen";
import { GenerateReportDialog } from "@/features/reports/GenerateReportDialog";
import { ReportsInboxPanel } from "@/features/reports/ReportsInboxPanel";
import { ReportWorkspacePanel } from "@/features/reports/ReportWorkspacePanel";
import { deriveCommunicationCapabilities } from "@/features/reports/reportPermissions";
import {
  inboxFilterToApiStatus,
  parseInboxFilter,
  type ReportInboxFilter,
} from "@/features/reports/report-status";
import { userFacingReportsError, reportProjectLabel } from "@/features/reports/report-utils";
import { useReportMutations } from "@/features/reports/useReportMutations";
import { useReportsQueries } from "@/features/reports/useReportsQueries";
import { ApiError } from "@/lib/api";
import { useAuthStore } from "@/stores/useAuthStore";
import type { CommunicationListItem, CommunicationType } from "@/types/communications";

const reportsRoute = getRouteApi("/reports");
const EMPTY_REPORTS: CommunicationListItem[] = [];

export function ReportsPage() {
  const navigate = useNavigate({ from: "/reports" });
  const search = reportsRoute.useSearch();
  const activeFilter = parseInboxFilter(search.status);

  const user = useAuthStore((s) => s.user);
  const capabilities = deriveCommunicationCapabilities(user);

  const [dialogOpen, setDialogOpen] = useState(false);
  const [generateProjectId, setGenerateProjectId] = useState<string | null>(null);
  const [generateCommType, setGenerateCommType] = useState<CommunicationType | null>(null);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [sendPartialFailure, setSendPartialFailure] = useState<string | null>(null);
  const [mobileWorkspaceOpen, setMobileWorkspaceOpen] = useState(false);
  const generateButtonRef = useRef<HTMLButtonElement>(null);

  const apiStatus = inboxFilterToApiStatus(activeFilter);
  const { listQuery, detailQuery } = useReportsQueries({
    status: apiStatus ?? null,
    selectedId,
  });
  const mutations = useReportMutations(null);

  const reports = listQuery.data?.data ?? EMPTY_REPORTS;
  const selectedListItem = reports.find((r) => r.id === selectedId) ?? null;
  const detail = detailQuery.data ?? null;
  const projectName = selectedListItem
    ? reportProjectLabel(selectedListItem)
    : (detail?.project_name ?? null);

  useEffect(() => {
    if (listQuery.isLoading || listQuery.isError) return;
    if (selectedId && reports.some((r) => r.id === selectedId)) return;
    if (selectedId && detail?.id === selectedId) return;
    if (reports.length === 0) {
      if (selectedId !== null) setSelectedId(null);
      return;
    }
    setSelectedId(reports[0]?.id ?? null);
  }, [listQuery.isLoading, listQuery.isError, reports, selectedId, detail?.id]);

  function setFilter(filter: ReportInboxFilter) {
    void navigate({
      search: (prev) => ({
        ...prev,
        status: filter === "all" ? undefined : filter,
      }),
      replace: true,
    });
  }

  function openGenerate(opts?: {
    projectId?: string | null;
    commType?: CommunicationType | null;
  }) {
    setGenerateProjectId(opts?.projectId ?? null);
    setGenerateCommType(opts?.commType ?? null);
    setDialogOpen(true);
  }

  function closeGenerateDialog() {
    if (mutations.draftCommunication.isPending) return;
    setDialogOpen(false);
    setGenerateProjectId(null);
    setGenerateCommType(null);
    queueMicrotask(() => generateButtonRef.current?.focus());
  }

  const listError = listQuery.isError
    ? userFacingReportsError(listQuery.error, "Failed to load reports.")
    : null;
  const detailError = detailQuery.isError
    ? userFacingReportsError(detailQuery.error, "Failed to load this report.")
    : null;

  const actionPending =
    mutations.update.isPending ||
    mutations.review.isPending ||
    mutations.approve.isPending ||
    mutations.reject.isPending ||
    mutations.send.isPending;

  if (listQuery.isLoading && reports.length === 0 && !listQuery.isError) {
    return <PageLoadingScreen />;
  }

  return (
    <div className="grid grid-cols-1 gap-5 lg:grid-cols-3">
      <ReportsInboxPanel
        reports={reports}
        selectedId={selectedId}
        activeFilter={activeFilter}
        onFilterChange={setFilter}
        onSelect={(id) => {
          setSendPartialFailure(null);
          setSelectedId(id);
          setMobileWorkspaceOpen(true);
        }}
        onGenerateClick={() => openGenerate()}
        canGenerate={capabilities.canGenerateCommunications}
        isLoading={listQuery.isLoading || listQuery.isFetching}
        isError={listQuery.isError}
        errorMessage={listError}
        onRetry={() => void listQuery.refetch()}
        hiddenOnMobile={mobileWorkspaceOpen && Boolean(selectedId)}
        generateButtonRef={generateButtonRef}
      />
      <div className={mobileWorkspaceOpen || !selectedId ? "lg:col-span-2" : "hidden lg:block lg:col-span-2"}>
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
          projectName={projectName}
          isLoading={Boolean(selectedId) && detailQuery.isLoading && !detail}
          isError={Boolean(selectedId) && detailQuery.isError && !detail}
          errorMessage={detailError}
          onRetry={() => void detailQuery.refetch()}
          capabilities={capabilities}
          onGenerateNew={() =>
            openGenerate({
              projectId: detail?.project_id ?? null,
              commType: detail?.comm_type ?? null,
            })
          }
          isGenerating={mutations.draftCommunication.isPending}
          actionPending={actionPending}
          sendPartialFailure={sendPartialFailure}
          onDismissSendPartialFailure={() => setSendPartialFailure(null)}
          onSaveEdits={async ({ subject, body }) => {
            if (!detail) return;
            await mutations.update.mutateAsync({
              communicationId: detail.id,
              projectName,
              payload: { subject, body },
            });
          }}
          onSubmitReview={async (body) => {
            if (!detail) return;
            await mutations.review.mutateAsync({
              communicationId: detail.id,
              projectName,
              payload: { body_approved: body },
            });
          }}
          onApprove={async (body) => {
            if (!detail) return;
            setSendPartialFailure(null);
            await mutations.approve.mutateAsync({
              communicationId: detail.id,
              projectName,
              payload: { body_approved: body },
            });
          }}
          onReject={async () => {
            if (!detail) return;
            setSendPartialFailure(null);
            await mutations.reject.mutateAsync({
              communicationId: detail.id,
              projectName,
            });
          }}
          onSend={async () => {
            if (!detail) return;
            try {
              await mutations.send.mutateAsync({
                communicationId: detail.id,
                projectName,
              });
              setSendPartialFailure(null);
            } catch (error) {
              if (detail.status === "approved" || mutations.approve.isSuccess) {
                setSendPartialFailure(
                  "Report approved, but sending failed. You can retry sending.",
                );
                void detailQuery.refetch();
                void listQuery.refetch();
              }
              if (error instanceof ApiError && error.status === 409) {
                void detailQuery.refetch();
              }
              throw error;
            }
          }}
        />
      </div>
      <GenerateReportDialog
        open={dialogOpen}
        initialProjectId={generateProjectId}
        initialCommType={generateCommType}
        onClose={closeGenerateDialog}
        canGenerate={capabilities.canGenerateCommunications}
        isPending={mutations.draftCommunication.isPending}
        onGenerate={async (values) => {
          const response = await mutations.draftCommunication.mutateAsync({
            projectId: values.projectId,
            projectName: values.projectName,
            orgId: values.orgId,
            orgName: values.orgName,
            payload: {
              comm_type: values.commType,
              subject: values.subject,
              instructions: values.instructions || null,
            },
          });
          setSelectedId(response.id);
          setMobileWorkspaceOpen(true);
          closeGenerateDialog();
        }}
      />
    </div>
  );
}
