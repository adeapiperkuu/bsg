import { apiFetch } from "../api";
import type {
  KpiCompare,
  KpiForecast,
  KpiObservation,
  KpiSeries,
  KpiTrendSummary,
  RecommendationSubjectSummary,
  RecommendationTimelineEvent,
  TimeSeriesDimensions,
  TimeSeriesScopeParams,
} from "@/types/time-series";

function toQuery(params: Record<string, string | number | undefined | null>): string {
  const search = new URLSearchParams();
  for (const [key, value] of Object.entries(params)) {
    if (value === undefined || value === null || value === "") continue;
    search.set(key, String(value));
  }
  const qs = search.toString();
  return qs ? `?${qs}` : "";
}

export async function fetchKpiHistory(
  kpiKey: string,
  params: TimeSeriesScopeParams = {},
): Promise<KpiObservation[]> {
  const body = await apiFetch<{ data: KpiObservation[] }>(
    `/kpis/${encodeURIComponent(kpiKey)}/history${toQuery(params)}`,
  );
  return body.data;
}

export async function fetchKpiLatest(
  kpiKey: string,
  params: TimeSeriesScopeParams = {},
): Promise<KpiObservation | null> {
  const body = await apiFetch<{ data: KpiObservation | null }>(
    `/kpis/${encodeURIComponent(kpiKey)}/latest${toQuery(params)}`,
  );
  return body.data;
}

export async function fetchKpiTrend(
  kpiKey: string,
  params: TimeSeriesScopeParams = {},
): Promise<KpiTrendSummary> {
  const body = await apiFetch<{ data: KpiTrendSummary }>(
    `/kpis/${encodeURIComponent(kpiKey)}/trend${toQuery(params)}`,
  );
  return body.data;
}

export async function fetchKpiSeries(
  kpiKey: string,
  params: TimeSeriesScopeParams = {},
): Promise<KpiSeries> {
  const body = await apiFetch<{ data: KpiSeries }>(
    `/kpis/${encodeURIComponent(kpiKey)}/series${toQuery(params)}`,
  );
  return body.data;
}

export async function fetchKpiCompare(
  kpiKey: string,
  params: TimeSeriesScopeParams = {},
): Promise<KpiCompare> {
  const body = await apiFetch<{ data: KpiCompare }>(
    `/kpis/${encodeURIComponent(kpiKey)}/compare${toQuery(params)}`,
  );
  return body.data;
}

export async function fetchKpiForecast(
  kpiKey: string,
  params: TimeSeriesScopeParams = {},
): Promise<KpiForecast> {
  const body = await apiFetch<{ data: KpiForecast }>(
    `/kpis/${encodeURIComponent(kpiKey)}/forecast${toQuery(params)}`,
  );
  return body.data;
}

export async function fetchTimeSeriesDimensions(
  orgId?: string,
): Promise<TimeSeriesDimensions> {
  const body = await apiFetch<{ data: TimeSeriesDimensions }>(
    `/time-series/dimensions${toQuery({ org_id: orgId })}`,
  );
  return body.data;
}

export async function fetchRecommendationSubjects(params: {
  domain?: string;
  project_id?: string;
  limit?: number;
  offset?: number;
} = {}): Promise<RecommendationSubjectSummary[]> {
  const body = await apiFetch<{ data: RecommendationSubjectSummary[] }>(
    `/time-series/recommendations${toQuery(params)}`,
  );
  return body.data;
}

export async function fetchRecommendationTimeline(
  subjectId: string,
  params: { limit?: number; offset?: number } = {},
): Promise<RecommendationTimelineEvent[]> {
  const body = await apiFetch<{ data: RecommendationTimelineEvent[] }>(
    `/time-series/recommendations/${encodeURIComponent(subjectId)}/timeline${toQuery(params)}`,
  );
  return body.data;
}
