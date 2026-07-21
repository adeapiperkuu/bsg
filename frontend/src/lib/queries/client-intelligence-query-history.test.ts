import { describe, expect, it } from "vitest";

import {
  insertPersistedQueryIntoHistoryCache,
  localPendingQueryHistory,
  localUnavailableQueryHistory,
  mergeServerHistoryPageWithPersistedQuery,
  QUERY_HISTORY_PAGE_SIZE,
} from "@/lib/queries/client-intelligence-query-history";
import type {
  ClientIntelligenceQueryHistory,
  ClientIntelligenceQueryRead,
} from "@/types/client-intelligence";

const PROJECT_ID = "cccccccc-cccc-4ccc-8ccc-cccccccccccc";

function queryItem(
  overrides: Partial<ClientIntelligenceQueryRead> = {},
): ClientIntelligenceQueryRead {
  const id = overrides.query_id ?? "11111111-1111-4111-8111-111111111111";
  return {
    query_id: id,
    project_id: PROJECT_ID,
    question: overrides.question ?? `Question ${id}`,
    answer_text: overrides.answer_text ?? "Deterministic answer",
    answer_availability: "answered",
    confidence_level: "medium",
    limitations: [],
    next_step: null,
    escalation_required: false,
    source_agents: ["delivery_performance"],
    evidence_links: [],
    as_of: "2026-07-16",
    reporting_period_start: "2026-07-10",
    reporting_period_end: "2026-07-16",
    model_used: null,
    latency_ms: 100,
    created_at: "2026-07-16T12:00:00Z",
    category: "delivery_confidence",
    insufficient_evidence: false,
    ...overrides,
  };
}

function page(
  items: ClientIntelligenceQueryRead[],
  overrides: Partial<ClientIntelligenceQueryHistory> = {},
): ClientIntelligenceQueryHistory {
  return {
    project_id: PROJECT_ID,
    items,
    limit: QUERY_HISTORY_PAGE_SIZE,
    offset: 0,
    total: items.length,
    has_more: false,
    history_source: "server",
    ...overrides,
  };
}

describe("Client Intelligence query history pagination integrity", () => {
  it("prepends a new query, keeps first page at limit 20, increments total once, and resets later pages", () => {
    const firstItems = Array.from({ length: 20 }, (_, index) =>
      queryItem({
        query_id: `aaaaaaaa-aaaa-4aaa-8aaa-${String(index).padStart(12, "0")}`,
        question: `Q${index}`,
      }),
    );
    const twentieth = firstItems[19]!;
    const previous = {
      pages: [
        page(firstItems, { total: 25, has_more: true }),
        page(
          [
            queryItem({
              query_id: "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb",
              question: "Older page item",
            }),
          ],
          { offset: 20, total: 25, has_more: false },
        ),
      ],
      pageParams: [0, 20],
    };

    const created = queryItem({
      query_id: "dddddddd-dddd-4ddd-8ddd-dddddddddddd",
      question: "Brand new question",
    });
    const next = insertPersistedQueryIntoHistoryCache(previous, created, PROJECT_ID)!;

    expect(next.pages).toHaveLength(1);
    expect(next.pageParams).toEqual([0]);
    expect(next.pages[0]!.items).toHaveLength(20);
    expect(next.pages[0]!.items[0]!.query_id).toBe(created.query_id);
    expect(next.pages[0]!.total).toBe(26);
    expect(next.pages[0]!.has_more).toBe(true);
    expect(next.pages[0]!.items.map((item) => item.query_id)).not.toContain(twentieth.query_id);
    expect(new Set(next.pages[0]!.items.map((item) => item.query_id)).size).toBe(20);

    const nextOffset = next.pages[0]!.has_more
      ? next.pages[0]!.offset + next.pages[0]!.items.length
      : undefined;
    expect(nextOffset).toBe(20);
  });

  it("does not increment total again for a repeated success with the same query_id", () => {
    const existing = queryItem({
      query_id: "dddddddd-dddd-4ddd-8ddd-dddddddddddd",
      question: "Existing",
    });
    const previous = {
      pages: [
        page([existing, queryItem({ query_id: "eeeeeeee-eeee-4eee-8eee-eeeeeeeeeeee" })], {
          total: 2,
        }),
      ],
      pageParams: [0],
    };
    const next = insertPersistedQueryIntoHistoryCache(previous, existing, PROJECT_ID)!;
    expect(next.pages[0]!.total).toBe(2);
    expect(next.pages[0]!.items.filter((item) => item.query_id === existing.query_id)).toHaveLength(
      1,
    );
  });

  it("returns undefined when no history page is cached so callers do not fabricate total=1", () => {
    const created = queryItem();
    expect(insertPersistedQueryIntoHistoryCache(undefined, created, PROJECT_ID)).toBeUndefined();
    const pending = localPendingQueryHistory(PROJECT_ID, created);
    expect(pending.pages[0]!.total).toBe(0);
    expect(pending.pages[0]!.history_source).toBe("local_pending");
    expect(pending.pages[0]!.items[0]!.query_id).toBe(created.query_id);
  });

  it("keeps the persisted result visible when marking history unavailable after fetch failure", () => {
    const created = queryItem({ question: "Survives fetch failure" });
    const unavailable = localUnavailableQueryHistory(PROJECT_ID, created);
    expect(unavailable.pages[0]!.items).toHaveLength(1);
    expect(unavailable.pages[0]!.items[0]!.question).toBe("Survives fetch failure");
    expect(unavailable.pages[0]!.total).not.toBe(1);
    expect(unavailable.pages[0]!.history_source).toBe("unavailable");
  });

  it("merges a fetched first page with the persisted query without duplicate ids", () => {
    const created = queryItem({
      query_id: "dddddddd-dddd-4ddd-8ddd-dddddddddddd",
      question: "Newest",
    });
    const displaced = queryItem({
      query_id: "cccccccc-cccc-4ccc-8ccc-cccccccccccc",
      question: "Would be twentieth",
    });
    const serverItems = [
      created,
      ...Array.from({ length: 19 }, (_, index) =>
        queryItem({
          query_id: `aaaaaaaa-aaaa-4aaa-8aaa-${String(index).padStart(12, "0")}`,
          question: `Server Q${index}`,
        }),
      ),
    ];
    const merged = mergeServerHistoryPageWithPersistedQuery(
      page(serverItems, { total: 21, has_more: true }),
      created,
    );
    expect(merged.items).toHaveLength(20);
    expect(merged.total).toBe(21);
    expect(merged.has_more).toBe(true);
    expect(merged.items[0]!.query_id).toBe(created.query_id);
    expect(new Set(merged.items.map((item) => item.query_id)).size).toBe(20);

    const afterInsert = insertPersistedQueryIntoHistoryCache(
      {
        pages: [page([...serverItems.slice(1), displaced], { total: 21, has_more: true })],
        pageParams: [0],
      },
      created,
      PROJECT_ID,
    )!;
    expect(afterInsert.pages[0]!.items).toHaveLength(20);
    expect(afterInsert.pages[0]!.total).toBe(22);
    expect(afterInsert.pages[0]!.has_more).toBe(true);
    expect(afterInsert.pages[0]!.offset + afterInsert.pages[0]!.items.length).toBe(20);
  });
});
