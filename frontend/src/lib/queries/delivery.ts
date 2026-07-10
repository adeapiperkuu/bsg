import { queryOptions, useQuery } from "@tanstack/react-query";
import {
  fetchDeliveryDashboard,
  fetchDeliveryPortfolio,
  listDeliveryConversations,
  listOrganisations,
  listProjectDeliveryConfidence,
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

export function deliveryConversationsQueryOptions(projectId: string | null, enabled = true) {
  return queryOptions({
    queryKey: queryKeys.deliveryConversations(projectId),
    queryFn: () => listDeliveryConversations(projectId),
    enabled,
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

export function useProjectsQuery() {
  return useQuery(projectsQueryOptions);
}

export function useOrganisationsQuery() {
  return useQuery(organisationsQueryOptions);
}

export function useDeliveryPortfolioQuery() {
  return useQuery(deliveryPortfolioQueryOptions);
}

export function useDeliveryDashboardQuery(projectId: string | null, enabled = true) {
  return useQuery({
    ...deliveryDashboardQueryOptions(projectId),
    enabled: Boolean(projectId) && enabled,
  });
}

export function useDeliveryConversationsQuery(projectId: string | null, enabled = true) {
  return useQuery(deliveryConversationsQueryOptions(projectId, enabled));
}

export function useProjectDeliveryConfidenceQuery(projectId: string | null) {
  return useQuery(projectDeliveryConfidenceQueryOptions(projectId));
}
