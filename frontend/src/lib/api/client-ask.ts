import { apiFetch } from "../api";
import type {
  ClientIntelligenceQueryHistory,
  ClientIntelligenceQueryRead,
} from "@/types/client-intelligence";

export async function createClientAskQuery(
  projectId: string,
  question: string,
): Promise<ClientIntelligenceQueryRead> {
  const body = await apiFetch<{ data: ClientIntelligenceQueryRead }>("/client/ask/queries", {
    method: "POST",
    body: JSON.stringify({ project_id: projectId, question }),
  });
  return body.data;
}

export async function fetchClientAskQueryHistory(
  projectId: string,
  params: {
    limit?: number;
    offset?: number;
  } = {},
): Promise<ClientIntelligenceQueryHistory> {
  const search = new URLSearchParams();
  search.set("project_id", projectId);
  if (params.limit != null) search.set("limit", String(params.limit));
  if (params.offset != null) search.set("offset", String(params.offset));
  const body = await apiFetch<{ data: ClientIntelligenceQueryHistory }>(
    `/client/ask/queries?${search.toString()}`,
  );
  return body.data;
}
