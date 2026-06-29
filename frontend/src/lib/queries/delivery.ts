import { queryOptions, useQuery } from "@tanstack/react-query";
import {
  fetchDeliveryDashboard,
  fetchDeliveryPortfolio,
  listOrganisations,
  listProjectDeliveryConfidence,
  listProjectThroughput,
  listProjects,
} from "@/lib/api";
import { queryKeys, STALE_TIME_MS } from "@/lib/queries/keys";

export const projectsQueryOptions = queryOptions({
  queryKey: queryKeys.projects,
  queryFn: listProjects,
  staleTime: STALE_TIME_MS,
});

export const organisationsQueryOptions = queryOptions({
  queryKey: queryKeys.organisations,
  queryFn: listOrganisations,
  staleTime: STALE_TIME_MS,
});

export const deliveryPortfolioQueryOptions = queryOptions({
  queryKey: queryKeys.deliveryPortfolio,
  queryFn: fetchDeliveryPortfolio,
  staleTime: STALE_TIME_MS,
});

export function deliveryDashboardQueryOptions(projectId: string | null) {
  return queryOptions({
    queryKey: queryKeys.deliveryDashboard(projectId ?? ""),
    queryFn: () => fetchDeliveryDashboard(projectId!),
    enabled: Boolean(projectId),
    staleTime: STALE_TIME_MS,
  });
}

export function projectDeliveryConfidenceQueryOptions(projectId: string | null) {
  return queryOptions({
    queryKey: queryKeys.projectDeliveryConfidence(projectId ?? ""),
    queryFn: () => listProjectDeliveryConfidence(projectId!),
    enabled: Boolean(projectId),
    staleTime: STALE_TIME_MS,
  });
}

export function projectThroughputQueryOptions(projectId: string | null) {
  return queryOptions({
    queryKey: queryKeys.projectThroughput(projectId ?? ""),
    queryFn: () => listProjectThroughput(projectId!),
    enabled: Boolean(projectId),
    staleTime: STALE_TIME_MS,
  });
}

export function useProjectsQuery() {
  return useQuery(projectsQueryOptions);
}

export function useOrganisationsQuery() {
  return useQuery(organisationsQueryOptions);
}

export function useDeliveryPortfolioQuery() {
  return useQuery(deliveryPortfolioQueryOptions);
}

export function useDeliveryDashboardQuery(projectId: string | null) {
  return useQuery(deliveryDashboardQueryOptions(projectId));
}

export function useProjectDeliveryConfidenceQuery(projectId: string | null) {
  return useQuery(projectDeliveryConfidenceQueryOptions(projectId));
}

export function useProjectThroughputQuery(projectId: string | null) {
  return useQuery(projectThroughputQueryOptions(projectId));
}
