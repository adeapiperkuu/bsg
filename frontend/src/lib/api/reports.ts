import { apiFetch, apiFetchBlob } from "../api";
import type {
  ReportApprovalEvent,
  ReportExport,
  ReportFormat,
  ReportGenerateRequest,
  ReportInstance,
  ReportInstanceListItem,
  ReportJobStart,
  ReportPreview,
  ReportSchedule,
  ReportScheduleCreate,
  ReportTemplate,
} from "@/types/reports";

function toQuery(params: Record<string, string | number | undefined | null>): string {
  const search = new URLSearchParams();
  for (const [key, value] of Object.entries(params)) {
    if (value === undefined || value === null || value === "") continue;
    search.set(key, String(value));
  }
  const qs = search.toString();
  return qs ? `?${qs}` : "";
}

export async function listReportTemplates(params: {
  domain?: string;
  audience?: string;
  status?: string;
} = {}): Promise<ReportTemplate[]> {
  const body = await apiFetch<{ data: ReportTemplate[] }>(
    `/reports/templates${toQuery(params)}`,
  );
  return body.data;
}

export async function getReportTemplate(templateId: string): Promise<ReportTemplate> {
  const body = await apiFetch<{ data: ReportTemplate }>(`/reports/templates/${templateId}`);
  return body.data;
}

export async function listPlatformReports(params: {
  status?: string;
  domain?: string;
  project_id?: string;
  template_key?: string;
  limit?: number;
  offset?: number;
} = {}): Promise<ReportInstanceListItem[]> {
  const body = await apiFetch<{ data: ReportInstanceListItem[] }>(
    `/reports${toQuery(params)}`,
  );
  return body.data;
}

export async function getPlatformReport(reportId: string): Promise<ReportInstance> {
  const body = await apiFetch<{ data: ReportInstance }>(`/reports/${reportId}`);
  return body.data;
}

export async function previewPlatformReport(reportId: string): Promise<ReportPreview> {
  const body = await apiFetch<{ data: ReportPreview }>(`/reports/${reportId}/preview`);
  return body.data;
}

export async function generatePlatformReport(
  payload: ReportGenerateRequest,
): Promise<ReportJobStart> {
  const body = await apiFetch<{ data: ReportJobStart }>("/reports/generate", {
    method: "POST",
    body: JSON.stringify(payload),
  });
  return body.data;
}

export async function generatePlatformReportSync(
  payload: ReportGenerateRequest,
): Promise<ReportInstance> {
  const body = await apiFetch<{ data: ReportInstance }>("/reports/generate/sync", {
    method: "POST",
    body: JSON.stringify(payload),
  });
  return body.data;
}

export async function getReportJob(jobId: string): Promise<ReportJobStart> {
  const body = await apiFetch<{ data: ReportJobStart }>(`/reports/jobs/${jobId}`);
  return body.data;
}

export async function submitPlatformReport(reportId: string): Promise<ReportInstance> {
  const body = await apiFetch<{ data: ReportInstance }>(`/reports/${reportId}/submit`, {
    method: "POST",
  });
  return body.data;
}

export async function approvePlatformReport(reportId: string): Promise<ReportInstance> {
  const body = await apiFetch<{ data: ReportInstance }>(`/reports/${reportId}/approve`, {
    method: "POST",
  });
  return body.data;
}

export async function rejectPlatformReport(
  reportId: string,
  reason: string,
): Promise<ReportInstance> {
  const body = await apiFetch<{ data: ReportInstance }>(
    `/reports/${reportId}/reject${toQuery({ reason })}`,
    { method: "POST" },
  );
  return body.data;
}

export async function distributePlatformReport(reportId: string): Promise<ReportInstance> {
  const body = await apiFetch<{ data: ReportInstance }>(`/reports/${reportId}/distribute`, {
    method: "POST",
  });
  return body.data;
}

export async function listReportApprovals(reportId: string): Promise<ReportApprovalEvent[]> {
  const body = await apiFetch<{ data: ReportApprovalEvent[] }>(
    `/reports/${reportId}/approvals`,
  );
  return body.data;
}

export async function requestReportExport(
  reportId: string,
  format: ReportFormat,
): Promise<ReportExport> {
  const body = await apiFetch<{ data: ReportExport }>(
    `/reports/${reportId}/exports/${format}`,
    { method: "POST" },
  );
  return body.data;
}

export async function listReportExports(reportId: string): Promise<ReportExport[]> {
  const body = await apiFetch<{ data: ReportExport[] }>(`/reports/${reportId}/exports`);
  return body.data;
}

export async function downloadReportExport(
  reportId: string,
  exportId: string,
): Promise<Blob> {
  return apiFetchBlob(`/reports/${reportId}/exports/${exportId}/download`);
}

export async function listReportSchedules(): Promise<ReportSchedule[]> {
  const body = await apiFetch<{ data: ReportSchedule[] }>("/reports/schedules");
  return body.data;
}

export async function createReportSchedule(
  payload: ReportScheduleCreate,
): Promise<ReportSchedule> {
  const body = await apiFetch<{ data: ReportSchedule }>("/reports/schedules", {
    method: "POST",
    body: JSON.stringify(payload),
  });
  return body.data;
}
