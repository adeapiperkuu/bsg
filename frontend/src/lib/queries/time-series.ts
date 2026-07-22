import { keepPreviousData, queryOptions, useQuery } from "@tanstack/react-query";
import {
  fetchKpiCompare,
  fetchKpiForecast,
  fetchKpiHistory,
  fetchKpiLatest,
  fetchKpiSeries,
  fetchKpiTrend,
  fetchRecommendationSubjects,
  fetchRecommendationTimeline,
  fetchTimeSeriesDimensions,
} from "@/lib/api/time-series";
import { queryKeys, STALE_TIME_MS } from "@/lib/queries/keys";
import type { TimeSeriesScopeParams } from "@/types/time-series";

export function kpiTrendQueryOptions(kpiKey: string, params: TimeSeriesScopeParams = {}) {
  return queryOptions({
    queryKey: queryKeys.kpiTrend(kpiKey, params),
    queryFn: () => fetchKpiTrend(kpiKey, params),
    enabled: Boolean(kpiKey),
    staleTime: STALE_TIME_MS,
    placeholderData: keepPreviousData,
  });
}

export function useKpiTrendQuery(kpiKey: string, params: TimeSeriesScopeParams = {}) {
  return useQuery(kpiTrendQueryOptions(kpiKey, params));
}

export function kpiSeriesQueryOptions(kpiKey: string, params: TimeSeriesScopeParams = {}) {
  return queryOptions({
    queryKey: queryKeys.kpiSeries(kpiKey, params),
    queryFn: () => fetchKpiSeries(kpiKey, params),
    enabled: Boolean(kpiKey),
    staleTime: STALE_TIME_MS,
    placeholderData: keepPreviousData,
  });
}

export function useKpiSeriesQuery(kpiKey: string, params: TimeSeriesScopeParams = {}) {
  return useQuery(kpiSeriesQueryOptions(kpiKey, params));
}

export function kpiHistoryQueryOptions(kpiKey: string, params: TimeSeriesScopeParams = {}) {
  return queryOptions({
    queryKey: queryKeys.kpiHistory(kpiKey, params),
    queryFn: () => fetchKpiHistory(kpiKey, params),
    enabled: Boolean(kpiKey),
    staleTime: STALE_TIME_MS,
  });
}

export function useKpiHistoryQuery(kpiKey: string, params: TimeSeriesScopeParams = {}) {
  return useQuery(kpiHistoryQueryOptions(kpiKey, params));
}

export function kpiLatestQueryOptions(kpiKey: string, params: TimeSeriesScopeParams = {}) {
  return queryOptions({
    queryKey: queryKeys.kpiLatest(kpiKey, params),
    queryFn: () => fetchKpiLatest(kpiKey, params),
    enabled: Boolean(kpiKey),
    staleTime: STALE_TIME_MS,
  });
}

export function useKpiLatestQuery(kpiKey: string, params: TimeSeriesScopeParams = {}) {
  return useQuery(kpiLatestQueryOptions(kpiKey, params));
}

export function kpiCompareQueryOptions(kpiKey: string, params: TimeSeriesScopeParams = {}) {
  return queryOptions({
    queryKey: queryKeys.kpiCompare(kpiKey, params),
    queryFn: () => fetchKpiCompare(kpiKey, params),
    enabled: Boolean(kpiKey),
    staleTime: STALE_TIME_MS,
  });
}

export function useKpiCompareQuery(kpiKey: string, params: TimeSeriesScopeParams = {}) {
  return useQuery(kpiCompareQueryOptions(kpiKey, params));
}

export function kpiForecastQueryOptions(kpiKey: string, params: TimeSeriesScopeParams = {}) {
  return queryOptions({
    queryKey: queryKeys.kpiForecast(kpiKey, params),
    queryFn: () => fetchKpiForecast(kpiKey, params),
    enabled: Boolean(kpiKey),
    staleTime: STALE_TIME_MS,
  });
}

export function useKpiForecastQuery(kpiKey: string, params: TimeSeriesScopeParams = {}) {
  return useQuery(kpiForecastQueryOptions(kpiKey, params));
}

export function timeSeriesDimensionsQueryOptions(orgId?: string) {
  return queryOptions({
    queryKey: queryKeys.timeSeriesDimensions(orgId),
    queryFn: () => fetchTimeSeriesDimensions(orgId),
    staleTime: STALE_TIME_MS,
  });
}

export function useTimeSeriesDimensionsQuery(orgId?: string) {
  return useQuery(timeSeriesDimensionsQueryOptions(orgId));
}

export function recommendationSubjectsQueryOptions(params: {
  domain?: string;
  project_id?: string;
  limit?: number;
  offset?: number;
} = {}) {
  return queryOptions({
    queryKey: queryKeys.recommendationSubjects(params),
    queryFn: () => fetchRecommendationSubjects(params),
    staleTime: STALE_TIME_MS,
  });
}

export function useRecommendationSubjectsQuery(params: {
  domain?: string;
  project_id?: string;
  limit?: number;
  offset?: number;
} = {}) {
  return useQuery(recommendationSubjectsQueryOptions(params));
}

export function recommendationTimelineQueryOptions(
  subjectId: string | null | undefined,
  params: { limit?: number; offset?: number } = {},
) {
  return queryOptions({
    queryKey: queryKeys.recommendationTimeline(subjectId ?? "", params),
    queryFn: () => fetchRecommendationTimeline(subjectId!, params),
    enabled: Boolean(subjectId),
    staleTime: STALE_TIME_MS,
  });
}

export function useRecommendationTimelineQuery(
  subjectId: string | null | undefined,
  params: { limit?: number; offset?: number } = {},
) {
  return useQuery(recommendationTimelineQueryOptions(subjectId, params));
}
