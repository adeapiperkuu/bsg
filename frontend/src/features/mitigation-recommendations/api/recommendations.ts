import { apiFetch } from "@/lib/api";
import type {
  AssignOwnerPayload,
  MitigationRecommendation,
  ProjectRecommendationsResponse,
} from "@/features/mitigation-recommendations/types";

export async function fetchProjectRecommendations(
  projectId: string,
): Promise<ProjectRecommendationsResponse> {
  return apiFetch<ProjectRecommendationsResponse>(`/projects/${projectId}/recommendations`);
}

export async function acceptRecommendation(
  recommendationId: string,
): Promise<MitigationRecommendation> {
  const body = await apiFetch<{ data: MitigationRecommendation }>(
    `/recommendations/${recommendationId}/accept`,
    { method: "POST" },
  );
  return body.data;
}

export async function rejectRecommendation(
  recommendationId: string,
): Promise<MitigationRecommendation> {
  const body = await apiFetch<{ data: MitigationRecommendation }>(
    `/recommendations/${recommendationId}/reject`,
    { method: "POST" },
  );
  return body.data;
}

export async function assignRecommendationOwner(
  recommendationId: string,
  payload: AssignOwnerPayload,
): Promise<MitigationRecommendation> {
  const body = await apiFetch<{ data: MitigationRecommendation }>(
    `/recommendations/${recommendationId}/assign-owner`,
    {
      method: "POST",
      body: JSON.stringify(payload),
    },
  );
  return body.data;
}
