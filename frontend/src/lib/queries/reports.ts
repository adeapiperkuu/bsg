import { keepPreviousData, queryOptions, useQuery } from "@tanstack/react-query";
import {
  getPlatformReport,
  getReportJob,
  listPlatformReports,
  listReportApprovals,
  listReportExports,
  listReportSchedules,
  listReportTemplates,
  previewPlatformReport,
} from "@/lib/api/reports";
import { queryKeys, STALE_TIME_MS } from "@/lib/queries/keys";

export function reportTemplatesQueryOptions(params: {
  domain?: string;
  audience?: string;
  status?: string;
} = {}) {
  return queryOptions({
    queryKey: queryKeys.reportTemplates(params),
    queryFn: () => listReportTemplates(params),
    staleTime: STALE_TIME_MS,
  });
}

export function useReportTemplatesQuery(params: {
  domain?: string;
  audience?: string;
  status?: string;
} = {}) {
  return useQuery(reportTemplatesQueryOptions(params));
}

export function platformReportsQueryOptions(params: {
  status?: string;
  domain?: string;
  project_id?: string;
  template_key?: string;
  limit?: number;
  offset?: number;
} = {}) {
  return queryOptions({
    queryKey: queryKeys.reportList(params),
    queryFn: () => listPlatformReports(params),
    staleTime: STALE_TIME_MS,
    placeholderData: keepPreviousData,
  });
}

export function usePlatformReportsQuery(params: {
  status?: string;
  domain?: string;
  project_id?: string;
  template_key?: string;
  limit?: number;
  offset?: number;
} = {}) {
  return useQuery(platformReportsQueryOptions(params));
}

export function platformReportQueryOptions(reportId: string | null | undefined) {
  return queryOptions({
    queryKey: queryKeys.reportDetail(reportId ?? ""),
    queryFn: () => getPlatformReport(reportId!),
    enabled: Boolean(reportId),
    staleTime: STALE_TIME_MS,
  });
}

export function usePlatformReportQuery(reportId: string | null | undefined) {
  return useQuery(platformReportQueryOptions(reportId));
}

export function reportPreviewQueryOptions(reportId: string | null | undefined) {
  return queryOptions({
    queryKey: queryKeys.reportPreview(reportId ?? ""),
    queryFn: () => previewPlatformReport(reportId!),
    enabled: Boolean(reportId),
    staleTime: STALE_TIME_MS,
  });
}

export function useReportPreviewQuery(reportId: string | null | undefined) {
  return useQuery(reportPreviewQueryOptions(reportId));
}

export function reportExportsQueryOptions(reportId: string | null | undefined) {
  return queryOptions({
    queryKey: queryKeys.reportExports(reportId ?? ""),
    queryFn: () => listReportExports(reportId!),
    enabled: Boolean(reportId),
    staleTime: STALE_TIME_MS,
  });
}

export function useReportExportsQuery(reportId: string | null | undefined) {
  return useQuery(reportExportsQueryOptions(reportId));
}

export function reportApprovalsQueryOptions(reportId: string | null | undefined) {
  return queryOptions({
    queryKey: queryKeys.reportApprovals(reportId ?? ""),
    queryFn: () => listReportApprovals(reportId!),
    enabled: Boolean(reportId),
    staleTime: STALE_TIME_MS,
  });
}

export function useReportApprovalsQuery(reportId: string | null | undefined) {
  return useQuery(reportApprovalsQueryOptions(reportId));
}

export function reportSchedulesQueryOptions() {
  return queryOptions({
    queryKey: queryKeys.reportSchedules,
    queryFn: () => listReportSchedules(),
    staleTime: STALE_TIME_MS,
  });
}

export function useReportSchedulesQuery() {
  return useQuery(reportSchedulesQueryOptions());
}

export function reportJobQueryOptions(jobId: string | null | undefined) {
  return queryOptions({
    queryKey: queryKeys.reportJob(jobId ?? ""),
    queryFn: () => getReportJob(jobId!),
    enabled: Boolean(jobId),
    refetchInterval: (query) => {
      const status = query.state.data?.status;
      return status && ["queued", "running", "retry_scheduled"].includes(status) ? 2000 : false;
    },
  });
}

export function useReportJobQuery(jobId: string | null | undefined) {
  return useQuery(reportJobQueryOptions(jobId));
}
