import type { InfiniteData } from "@tanstack/react-query";

import type {
  ClientIntelligenceQueryHistory,
  ClientIntelligenceQueryRead,
} from "@/types/client-intelligence";

export const QUERY_HISTORY_PAGE_SIZE = 20;

/**
 * Seeds a non-authoritative local history page so a just-persisted query stays
 * visible before the exact-project first page is fetched. Never claims total=1.
 */
export function localPendingQueryHistory(
  projectId: string,
  result: ClientIntelligenceQueryRead,
): InfiniteData<ClientIntelligenceQueryHistory> {
  return {
    pages: [
      {
        project_id: projectId,
        items: [result],
        limit: QUERY_HISTORY_PAGE_SIZE,
        offset: 0,
        total: 0,
        has_more: false,
        history_source: "local_pending",
      },
    ],
    pageParams: [0],
  };
}

/**
 * Keeps the persisted result visible after a failed first-page history fetch.
 */
export function localUnavailableQueryHistory(
  projectId: string,
  result: ClientIntelligenceQueryRead,
): InfiniteData<ClientIntelligenceQueryHistory> {
  return {
    pages: [
      {
        project_id: projectId,
        items: [result],
        limit: QUERY_HISTORY_PAGE_SIZE,
        offset: 0,
        total: 0,
        has_more: false,
        history_source: "unavailable",
      },
    ],
    pageParams: [0],
  };
}

/**
 * Merges a fetched first history page with the just-persisted query.
 * Server totals are authoritative once adjusted for a not-yet-listed row.
 */
export function mergeServerHistoryPageWithPersistedQuery(
  page: ClientIntelligenceQueryHistory,
  result: ClientIntelligenceQueryRead,
): ClientIntelligenceQueryHistory {
  const limit = page.limit > 0 ? page.limit : QUERY_HISTORY_PAGE_SIZE;
  const alreadyOnServer = page.items.some((item) => item.query_id === result.query_id);
  const withoutDup = page.items.filter((item) => item.query_id !== result.query_id);
  const items = [result, ...withoutDup].slice(0, limit);
  const total = alreadyOnServer ? page.total : page.total + 1;
  return {
    project_id: page.project_id,
    items,
    limit,
    offset: 0,
    total,
    has_more: total > items.length,
    history_source: "server",
  };
}

/**
 * Inserts a persisted query into an existing infinite-query history cache.
 * Preserves page limit, newest-first order, and truthful has_more / total.
 * Returns undefined when there is no cached page (caller must seed + fetch).
 */
export function insertPersistedQueryIntoHistoryCache(
  previous: InfiniteData<ClientIntelligenceQueryHistory> | undefined,
  result: ClientIntelligenceQueryRead,
  projectId: string,
): InfiniteData<ClientIntelligenceQueryHistory> | undefined {
  if (!previous?.pages?.length) {
    return undefined;
  }

  const first = previous.pages[0]!;
  const limit = first.limit > 0 ? first.limit : QUERY_HISTORY_PAGE_SIZE;
  const alreadyPresent = previous.pages.some((page) =>
    page.items.some((item) => item.query_id === result.query_id),
  );

  if (alreadyPresent) {
    const firstWithout = first.items.filter((item) => item.query_id !== result.query_id);
    const items = [result, ...firstWithout].slice(0, limit);
    const laterPages = previous.pages.slice(1).map((page) => ({
      ...page,
      items: page.items.filter((item) => item.query_id !== result.query_id),
    }));
    return {
      pages: [
        {
          ...first,
          items,
          has_more: first.offset + items.length < first.total,
          history_source: first.history_source ?? "server",
        },
        ...laterPages,
      ],
      pageParams: previous.pageParams,
    };
  }

  const firstWithout = first.items.filter((item) => item.query_id !== result.query_id);
  const trimmed = [result, ...firstWithout].slice(0, limit);
  const total = first.total + 1;
  return {
    pages: [
      {
        project_id: projectId,
        items: trimmed,
        limit,
        offset: 0,
        total,
        has_more: total > trimmed.length,
        history_source: "server",
      },
    ],
    pageParams: [0],
  };
}
