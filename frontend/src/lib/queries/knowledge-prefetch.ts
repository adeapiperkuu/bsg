import type { QueryClient } from "@tanstack/react-query";

import {
  knowledgeBootstrapQueryOptions,
  seedKnowledgeDocumentsFromBootstrap,
  seedKnowledgeLibraryHealthFromBootstrap,
} from "@/lib/queries/knowledge";
import { queryKeys } from "@/lib/queries/keys";
import type { KnowledgeBootstrapApi } from "@/types/knowledge";

function throwIfAborted(signal: AbortSignal): void {
  if (signal.aborted) {
    throw new DOMException("The operation was aborted.", "AbortError");
  }
}

export function prefetchKnowledgeRouteModule(): void {
  void import("@/routes/knowledge");
}

/** Prefetch Knowledge first-paint bootstrap (folders, recent docs, health counts). */
export async function prefetchKnowledgeRouteData(
  queryClient: QueryClient,
  signal: AbortSignal = new AbortController().signal,
): Promise<void> {
  throwIfAborted(signal);
  await queryClient.prefetchQuery(knowledgeBootstrapQueryOptions(true));
  throwIfAborted(signal);
  const bootstrap = queryClient.getQueryData<KnowledgeBootstrapApi>(queryKeys.knowledgeBootstrap);
  if (bootstrap) {
    seedKnowledgeDocumentsFromBootstrap(queryClient, bootstrap);
    seedKnowledgeLibraryHealthFromBootstrap(queryClient, bootstrap);
  }
}

export async function prefetchKnowledgeNav(
  queryClient: QueryClient,
  signal: AbortSignal = new AbortController().signal,
): Promise<void> {
  prefetchKnowledgeRouteModule();
  await prefetchKnowledgeRouteData(queryClient, signal);
}
