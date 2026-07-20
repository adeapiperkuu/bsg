import { QueryClient } from "@tanstack/react-query";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import {
  flushNavPrefetch,
  resetNavPrefetchStateForTests,
  scheduleNavPrefetch,
} from "@/lib/queries/nav-prefetch";

type PrefetchFn = (qc: QueryClient, signal: AbortSignal) => Promise<void>;

const { governanceNav, deliveryNav, knowledgeNav, reportsNav } = vi.hoisted(() => ({
  governanceNav: vi.fn<PrefetchFn>(),
  deliveryNav: vi.fn<PrefetchFn>(),
  knowledgeNav: vi.fn<PrefetchFn>(),
  reportsNav: vi.fn<PrefetchFn>(),
}));

vi.mock("@/features/governance/governance-prefetch", () => ({
  prefetchGovernanceNav: (qc: QueryClient, signal: AbortSignal) => governanceNav(qc, signal),
}));

vi.mock("@/lib/queries/delivery-prefetch", () => ({
  prefetchDeliveryNav: (qc: QueryClient, signal: AbortSignal) => deliveryNav(qc, signal),
}));

vi.mock("@/lib/queries/knowledge-prefetch", () => ({
  prefetchKnowledgeNav: (qc: QueryClient, signal: AbortSignal) => knowledgeNav(qc, signal),
}));

vi.mock("@/features/reports/reports-prefetch", () => ({
  prefetchReportsNav: (qc: QueryClient, signal: AbortSignal) => reportsNav(qc, signal),
}));

describe("nav-prefetch single-flight", () => {
  beforeEach(() => {
    vi.useFakeTimers();
    resetNavPrefetchStateForTests();
    governanceNav.mockReset();
    deliveryNav.mockReset();
    knowledgeNav.mockReset();
    reportsNav.mockReset();
    governanceNav.mockResolvedValue(undefined);
    deliveryNav.mockResolvedValue(undefined);
    knowledgeNav.mockResolvedValue(undefined);
    reportsNav.mockResolvedValue(undefined);
  });

  afterEach(() => {
    resetNavPrefetchStateForTests();
    vi.useRealTimers();
    vi.clearAllMocks();
  });

  it("lingers before starting a Governance bundle", async () => {
    const queryClient = new QueryClient();
    scheduleNavPrefetch(queryClient, "/governance");
    expect(governanceNav).not.toHaveBeenCalled();

    await vi.advanceTimersByTimeAsync(449);
    expect(governanceNav).not.toHaveBeenCalled();

    await vi.advanceTimersByTimeAsync(1);
    expect(governanceNav).toHaveBeenCalledTimes(1);
    expect(deliveryNav).not.toHaveBeenCalled();
  });

  it("keeps a single active agent bundle by aborting the previous path", async () => {
    const queryClient = new QueryClient();
    let resolveGovernance!: () => void;
    const governanceSignalRef: { current: AbortSignal | null } = { current: null };
    governanceNav.mockImplementation((_qc, signal) => {
      governanceSignalRef.current = signal;
      return new Promise<void>((resolve) => {
        resolveGovernance = resolve;
      });
    });

    flushNavPrefetch(queryClient, "/governance");
    expect(governanceNav).toHaveBeenCalledTimes(1);

    flushNavPrefetch(queryClient, "/delivery");
    expect(deliveryNav).toHaveBeenCalledTimes(1);
    expect(governanceSignalRef.current?.aborted).toBe(true);

    resolveGovernance();
    await Promise.resolve();
  });

  it("suppresses repeated Governance hover within the cooldown after completion", async () => {
    const queryClient = new QueryClient();
    flushNavPrefetch(queryClient, "/governance");
    await Promise.resolve();
    await Promise.resolve();

    expect(governanceNav).toHaveBeenCalledTimes(1);

    flushNavPrefetch(queryClient, "/governance");
    expect(governanceNav).toHaveBeenCalledTimes(1);
  });

  it("reuses the in-flight Governance bundle instead of starting a duplicate", async () => {
    const queryClient = new QueryClient();
    let resolveGovernance!: () => void;
    governanceNav.mockImplementation(
      () =>
        new Promise<void>((resolve) => {
          resolveGovernance = resolve;
        }),
    );

    flushNavPrefetch(queryClient, "/governance");
    flushNavPrefetch(queryClient, "/governance");
    expect(governanceNav).toHaveBeenCalledTimes(1);

    resolveGovernance();
    await Promise.resolve();
  });

  it("prefetches Knowledge bootstrap on nav hover", async () => {
    const queryClient = new QueryClient();
    scheduleNavPrefetch(queryClient, "/knowledge");
    expect(knowledgeNav).not.toHaveBeenCalled();

    await vi.advanceTimersByTimeAsync(450);
    expect(knowledgeNav).toHaveBeenCalledTimes(1);
    expect(governanceNav).not.toHaveBeenCalled();
  });

  it("prefetches reports list-only bundle on nav hover", async () => {
    const queryClient = new QueryClient();
    scheduleNavPrefetch(queryClient, "/reports");
    expect(reportsNav).not.toHaveBeenCalled();

    await vi.advanceTimersByTimeAsync(450);
    expect(reportsNav).toHaveBeenCalledTimes(1);
    expect(deliveryNav).not.toHaveBeenCalled();
  });
});
