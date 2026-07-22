import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";

import {
  ReportApprovalActions,
  ReportExportButtons,
  ReportGenerationProgress,
  ReportHistoryList,
  ReportPreviewPanel,
  ReportScheduleForm,
  ReportSectionEditor,
  ReportTemplateList,
} from "@/components/bsg/reports";
import { Card, SectionHeader } from "@/components/bsg/widgets";
import { Button } from "@/components/ui/button";
import {
  approvePlatformReport,
  createReportSchedule,
  distributePlatformReport,
  generatePlatformReport,
  rejectPlatformReport,
  submitPlatformReport,
} from "@/lib/api/reports";
import {
  platformReportQueryOptions,
  platformReportsQueryOptions,
  reportApprovalsQueryOptions,
  reportPreviewQueryOptions,
  reportSchedulesQueryOptions,
  reportTemplatesQueryOptions,
} from "@/lib/queries/reports";
import { queryKeys } from "@/lib/queries/keys";
import type { ReportGenerateRequest, ReportScheduleCreate } from "@/types/reports";

/**
 * Shared Phase 18.3 reporting surface: templates, history, preview, approval,
 * exports, and draft-only schedules. Used by PM Reports and agent dashboards.
 */
export function PlatformReportsPanel({
  domain,
  projectId,
  compact = false,
  initiallyOpen = false,
}: {
  domain?: string;
  projectId?: string | null;
  compact?: boolean;
  initiallyOpen?: boolean;
}) {
  const queryClient = useQueryClient();
  const [open, setOpen] = useState(initiallyOpen);
  const [selectedTemplateId, setSelectedTemplateId] = useState<string | null>(null);
  const [selectedReportId, setSelectedReportId] = useState<string | null>(null);
  const [jobId, setJobId] = useState<string | null>(null);

  const templatesQuery = useQuery({
    ...reportTemplatesQueryOptions({ domain, status: "active" }),
    enabled: open,
  });
  const historyQuery = useQuery({
    ...platformReportsQueryOptions({
      domain,
      project_id: projectId ?? undefined,
      limit: 25,
    }),
    enabled: open,
  });
  const detailQuery = useQuery({
    ...platformReportQueryOptions(selectedReportId),
    enabled: open && Boolean(selectedReportId),
  });
  const previewQuery = useQuery({
    ...reportPreviewQueryOptions(selectedReportId),
    enabled: open && Boolean(selectedReportId),
  });
  const approvalsQuery = useQuery({
    ...reportApprovalsQueryOptions(selectedReportId),
    enabled: open && Boolean(selectedReportId),
  });
  const schedulesQuery = useQuery({
    ...reportSchedulesQueryOptions(),
    enabled: open && !compact,
  });

  const templates = templatesQuery.data ?? [];
  const reports = historyQuery.data ?? [];
  const selectedTemplate =
    templates.find((t) => t.id === selectedTemplateId) ?? templates[0] ?? null;

  const generateMutation = useMutation({
    mutationFn: (payload: ReportGenerateRequest) => generatePlatformReport(payload),
    onSuccess: async (job) => {
      setJobId(job.id);
      toast.success("Report generation queued");
      await queryClient.invalidateQueries({ queryKey: ["reports", "list"] });
    },
    onError: (error) =>
      toast.error(error instanceof Error ? error.message : "Failed to queue report"),
  });

  const scheduleMutation = useMutation({
    mutationFn: (payload: ReportScheduleCreate) => createReportSchedule(payload),
    onSuccess: async () => {
      toast.success("Draft-only schedule created");
      await queryClient.invalidateQueries({ queryKey: queryKeys.reportSchedules });
    },
    onError: () => toast.error("Failed to create schedule"),
  });

  const lifecycleBusy =
    generateMutation.isPending ||
    detailQuery.isFetching ||
    approvalsQuery.isFetching ||
    scheduleMutation.isPending;

  if (!open) {
    return (
      <Card>
        <SectionHeader
          title="Platform Reports"
          sub="Shared templates, exports, and draft-only schedules"
          right={
            <Button size="sm" variant="outline" onClick={() => setOpen(true)}>
              Open platform reports
            </Button>
          }
        />
        <p className="text-xs text-muted-foreground">
          Schedules create drafts only. Approve does not distribute. AI sections always
          require human approval.
        </p>
      </Card>
    );
  }

  return (
    <div className={compact ? "space-y-3" : "space-y-4"}>
      <Card>
        <SectionHeader
          title="Platform Reports"
          sub="Shared templates · human approval · draft-only schedules"
          right={
            <div className="flex gap-2">
              <Button size="sm" variant="ghost" onClick={() => setOpen(false)}>
                Hide
              </Button>
              <Button
                size="sm"
                disabled={!selectedTemplate || generateMutation.isPending}
                onClick={() => {
                  if (!selectedTemplate) return;
                  generateMutation.mutate({
                    template_key: selectedTemplate.template_key,
                    project_id: projectId ?? undefined,
                  });
                }}
              >
                Generate draft
              </Button>
            </div>
          }
        />
        <p className="text-xs text-muted-foreground">
          Schedules create drafts only. Approve does not distribute. AI sections always
          require human approval.
        </p>
      </Card>

      <div className={`grid gap-3 ${compact ? "grid-cols-1" : "grid-cols-1 lg:grid-cols-2"}`}>
        <ReportTemplateList
          templates={templates}
          selectedId={selectedTemplate?.id}
          onSelect={setSelectedTemplateId}
          loading={templatesQuery.isLoading}
        />
        <ReportHistoryList
          reports={reports}
          selectedId={selectedReportId}
          onSelect={setSelectedReportId}
          loading={historyQuery.isLoading}
        />
      </div>

      {selectedTemplate ? (
        <ReportSectionEditor sections={selectedTemplate.section_config} readOnly />
      ) : null}

      <ReportGenerationProgress jobId={jobId} />
      <ReportPreviewPanel
        preview={previewQuery.data}
        loading={previewQuery.isLoading && Boolean(selectedReportId)}
      />
      <ReportApprovalActions
        report={detailQuery.data}
        busy={lifecycleBusy}
        onSubmit={async () => {
          if (!selectedReportId) return;
          await submitPlatformReport(selectedReportId);
          await detailQuery.refetch();
          toast.success("Submitted for review");
        }}
        onApprove={async () => {
          if (!selectedReportId) return;
          await approvePlatformReport(selectedReportId);
          await detailQuery.refetch();
          toast.success("Approved (not distributed)");
        }}
        onReject={async (reason) => {
          if (!selectedReportId) return;
          await rejectPlatformReport(selectedReportId, reason);
          await detailQuery.refetch();
          toast.success("Rejected");
        }}
        onDistribute={async () => {
          if (!selectedReportId) return;
          await distributePlatformReport(selectedReportId);
          await detailQuery.refetch();
          toast.success("Marked distributed");
        }}
      />
      <ReportExportButtons reportId={selectedReportId} />
      {!compact && selectedTemplate ? (
        <ReportScheduleForm
          templateId={selectedTemplate.id}
          busy={scheduleMutation.isPending}
          onSubmit={async (payload) => {
            await scheduleMutation.mutateAsync({
              ...payload,
              project_id: projectId ?? undefined,
            });
          }}
        />
      ) : null}
      {!compact && (schedulesQuery.data?.length ?? 0) > 0 ? (
        <Card>
          <SectionHeader
            title="Active schedules"
            sub={`${schedulesQuery.data?.length ?? 0} draft-only`}
          />
          <ul className="space-y-1 text-xs text-muted-foreground">
            {(schedulesQuery.data ?? []).map((schedule) => (
              <li key={schedule.id}>
                {schedule.interval} · {schedule.is_enabled ? "enabled" : "disabled"} · creates{" "}
                {schedule.create_as_status}
              </li>
            ))}
          </ul>
        </Card>
      ) : null}
    </div>
  );
}
