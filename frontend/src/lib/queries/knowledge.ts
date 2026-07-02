import {
  keepPreviousData,
  queryOptions,
  useMutation,
  useQuery,
  useQueryClient,
  type QueryClient,
} from "@tanstack/react-query";
import { useEffect } from "react";

import {
  ApiError,
  createKnowledgeFolder,
  deleteKnowledgeDocument,
  getKnowledgeBootstrap,
  getKnowledgeDocument,
  getKnowledgeLibraryHealth,
  getKnowledgeRetrievalSettings,
  listAgentQueries,
  listKnowledgeDocumentVersions,
  listKnowledgeDocuments,
  listKnowledgeLessons,
  reindexKnowledgeDocument,
  resolveKnowledgeGap,
  updateKnowledgeDocument,
  updateKnowledgeRetrievalSettings,
  uploadKnowledgeDocument,
} from "@/lib/api";
import { documentFromApi, documentSummaryFromApi } from "@/lib/knowledge-mappers";
import type { KnowledgeDocument } from "@/lib/knowledge-mappers";
import { KNOWLEDGE_BOOTSTRAP_STALE_TIME_MS, queryKeys, STALE_TIME_MS } from "@/lib/queries/keys";
import { useAuthStore } from "@/stores/useAuthStore";
import type {
  AgentQueryApi,
  KnowledgeBootstrapApi,
  KnowledgeLessonApi,
  KnowledgeLibraryHealthApi,
  KnowledgeRetrievalSettingsApi,
} from "@/types/knowledge";

function knowledgeRetry(failureCount: number, error: unknown) {
  if (error instanceof ApiError && (error.status === 401 || error.status === 403)) {
    return false;
  }
  return failureCount < 1;
}

export function useKnowledgeSessionReady() {
  const isLoading = useAuthStore((s) => s.isLoading);
  const isAuthenticated = useAuthStore((s) => s.isAuthenticated);
  return !isLoading && isAuthenticated;
}

const knowledgeQueryDefaults = {
  staleTime: STALE_TIME_MS,
  refetchOnMount: false as const,
  refetchOnWindowFocus: false as const,
  refetchOnReconnect: true as const,
  retry: knowledgeRetry,
};

const knowledgeBootstrapDefaults = {
  staleTime: KNOWLEDGE_BOOTSTRAP_STALE_TIME_MS,
  refetchOnMount: false as const,
  refetchOnWindowFocus: false as const,
  refetchOnReconnect: true as const,
  retry: knowledgeRetry,
};

export function invalidateKnowledgeLibrary(queryClient: QueryClient) {
  return Promise.all([
    queryClient.invalidateQueries({ queryKey: queryKeys.knowledgeBootstrap }),
    queryClient.invalidateQueries({ queryKey: queryKeys.knowledgeDocuments }),
    queryClient.invalidateQueries({ queryKey: queryKeys.knowledgeLibraryHealth }),
  ]);
}

export function invalidateKnowledgeAgentQueries(queryClient: QueryClient) {
  return queryClient.invalidateQueries({ queryKey: queryKeys.knowledgeAgentQueries });
}

export function patchKnowledgeDocumentsCache(
  queryClient: QueryClient,
  updater: (documents: KnowledgeDocument[]) => KnowledgeDocument[],
) {
  queryClient.setQueryData<KnowledgeDocument[]>(queryKeys.knowledgeDocuments, (current) => {
    if (!current) return current;
    return updater(current);
  });
}

export function seedKnowledgeDocumentsFromBootstrap(
  queryClient: QueryClient,
  bootstrap: KnowledgeBootstrapApi,
) {
  queryClient.setQueryData<KnowledgeDocument[]>(queryKeys.knowledgeDocuments, (current) => {
    if (current) return current;
    return (bootstrap.recent_documents ?? []).map(documentSummaryFromApi);
  });
}

export function knowledgeBootstrapQueryOptions(enabled = true) {
  return queryOptions({
    queryKey: queryKeys.knowledgeBootstrap,
    queryFn: getKnowledgeBootstrap,
    enabled,
    ...knowledgeBootstrapDefaults,
    placeholderData: keepPreviousData,
  });
}

export function knowledgeDocumentsQueryOptions(enabled = true, poll = false) {
  return queryOptions({
    queryKey: queryKeys.knowledgeDocuments,
    queryFn: async () => (await listKnowledgeDocuments()).map(documentFromApi),
    enabled,
    ...knowledgeQueryDefaults,
    refetchInterval: poll ? 2500 : false,
    placeholderData: keepPreviousData,
  });
}

export function knowledgeDocumentQueryOptions(documentId: string) {
  return queryOptions({
    queryKey: queryKeys.knowledgeDocument(documentId),
    queryFn: async () => documentFromApi(await getKnowledgeDocument(documentId)),
    enabled: Boolean(documentId),
    ...knowledgeQueryDefaults,
    placeholderData: keepPreviousData,
  });
}

export function knowledgeDocumentVersionsQueryOptions(documentId: string) {
  return queryOptions({
    queryKey: queryKeys.knowledgeDocumentVersions(documentId),
    queryFn: () => listKnowledgeDocumentVersions(documentId),
    enabled: Boolean(documentId),
    ...knowledgeQueryDefaults,
    placeholderData: keepPreviousData,
  });
}

export function knowledgeLessonsQueryOptions(enabled = true) {
  return queryOptions({
    queryKey: queryKeys.knowledgeLessons,
    queryFn: listKnowledgeLessons,
    enabled,
    ...knowledgeQueryDefaults,
    placeholderData: keepPreviousData,
  });
}

export function knowledgeAgentQueriesQueryOptions(enabled = true) {
  return queryOptions({
    queryKey: queryKeys.knowledgeAgentQueries,
    queryFn: () => listAgentQueries(30),
    enabled,
    ...knowledgeQueryDefaults,
    placeholderData: keepPreviousData,
  });
}

export function knowledgeLibraryHealthQueryOptions(enabled = true, poll = false) {
  return queryOptions({
    queryKey: queryKeys.knowledgeLibraryHealth,
    queryFn: getKnowledgeLibraryHealth,
    enabled,
    ...knowledgeQueryDefaults,
    refetchInterval: poll ? 2500 : false,
    placeholderData: keepPreviousData,
  });
}

export function knowledgeRetrievalSettingsQueryOptions(enabled = true) {
  return queryOptions({
    queryKey: queryKeys.knowledgeRetrievalSettings,
    queryFn: getKnowledgeRetrievalSettings,
    enabled,
    ...knowledgeQueryDefaults,
    placeholderData: keepPreviousData,
  });
}

export function useKnowledgeBootstrapQuery() {
  const queryClient = useQueryClient();
  const sessionReady = useKnowledgeSessionReady();
  const query = useQuery(knowledgeBootstrapQueryOptions(sessionReady));

  useEffect(() => {
    if (query.data) {
      seedKnowledgeDocumentsFromBootstrap(queryClient, query.data);
    }
  }, [query.data, queryClient]);

  return query;
}

export function useKnowledgeDocumentsQuery(
  enabled = true,
  poll = false,
  initialData?: KnowledgeDocument[],
) {
  const sessionReady = useKnowledgeSessionReady();
  return useQuery({
    ...knowledgeDocumentsQueryOptions(enabled && sessionReady, poll),
    initialData,
    initialDataUpdatedAt: initialData ? Date.now() : undefined,
  });
}

export function useKnowledgeLessonsQuery(enabled = true) {
  const sessionReady = useKnowledgeSessionReady();
  return useQuery(knowledgeLessonsQueryOptions(enabled && sessionReady));
}

export function useKnowledgeDocumentVersionsQuery(documentId: string, enabled = true) {
  const sessionReady = useKnowledgeSessionReady();
  return useQuery({
    ...knowledgeDocumentVersionsQueryOptions(documentId),
    enabled: enabled && sessionReady && Boolean(documentId),
  });
}

export function useKnowledgeLibraryHealthQuery(enabled = true, poll = false) {
  const sessionReady = useKnowledgeSessionReady();
  return useQuery(knowledgeLibraryHealthQueryOptions(enabled && sessionReady, poll));
}

export function useKnowledgeRetrievalSettingsQuery(enabled = true) {
  const sessionReady = useKnowledgeSessionReady();
  return useQuery(knowledgeRetrievalSettingsQueryOptions(enabled && sessionReady));
}

export function useKnowledgeAgentQueriesQuery(enabled = true) {
  const sessionReady = useKnowledgeSessionReady();
  return useQuery(knowledgeAgentQueriesQueryOptions(enabled && sessionReady));
}

export function useUploadKnowledgeDocumentMutation() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ file, fields }: { file: File; fields: Record<string, string> }) =>
      uploadKnowledgeDocument(file, fields),
    onSuccess: () => void invalidateKnowledgeLibrary(queryClient),
  });
}

export function useUpdateKnowledgeDocumentMutation() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ id, patch }: { id: string; patch: Record<string, string> }) =>
      updateKnowledgeDocument(id, patch),
    onSuccess: (row) => {
      const mapped = documentFromApi(row);
      patchKnowledgeDocumentsCache(queryClient, (documents) =>
        documents.map((item) => (item.id === mapped.id ? mapped : item)),
      );
      void queryClient.invalidateQueries({ queryKey: queryKeys.knowledgeDocument(mapped.id) });
    },
  });
}

export function useDeleteKnowledgeDocumentMutation() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (documentId: string) => deleteKnowledgeDocument(documentId),
    onSuccess: (_result, documentId) => {
      patchKnowledgeDocumentsCache(queryClient, (documents) =>
        documents.filter((item) => item.id !== documentId),
      );
      void invalidateKnowledgeLibrary(queryClient);
    },
  });
}

export function useReindexKnowledgeDocumentMutation() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (documentId: string) => reindexKnowledgeDocument(documentId),
    onSuccess: (row) => {
      const mapped = documentFromApi(row);
      patchKnowledgeDocumentsCache(queryClient, (documents) =>
        documents.map((item) => (item.id === mapped.id ? mapped : item)),
      );
    },
  });
}

export function useCreateKnowledgeFolderMutation() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: createKnowledgeFolder,
    onSuccess: () => void invalidateKnowledgeLibrary(queryClient),
  });
}

export function useResolveKnowledgeGapMutation() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (gapId: string) => resolveKnowledgeGap(gapId),
    onSuccess: () => void invalidateKnowledgeLibrary(queryClient),
  });
}

export function useUpdateKnowledgeRetrievalSettingsMutation() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: updateKnowledgeRetrievalSettings,
    onSuccess: (data) => {
      queryClient.setQueryData(queryKeys.knowledgeRetrievalSettings, data);
    },
  });
}
