import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, renderHook, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { detectProjectCapabilityGaps, generateWorkforceRecommendations } from "@/lib/api";
import { queryKeys } from "@/lib/queries/keys";
import type { WorkforceRecommendationGenerateResponse } from "@/types/workforce";
import { useWorkforceCapabilityGapActions } from "./useWorkforceCapabilityGapActions";

vi.mock("@/lib/api", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/lib/api")>();
  return {
    ...actual,
    detectProjectCapabilityGaps: vi.fn(),
    generateWorkforceRecommendations: vi.fn(),
    updateCapabilityGap: vi.fn(),
  };
});

const mockedDetect = vi.mocked(detectProjectCapabilityGaps);
const mockedGenerate = vi.mocked(generateWorkforceRecommendations);

function createWrapper(queryClient: QueryClient) {
  return function Wrapper({ children }: { children: ReactNode }) {
    return <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>;
  };
}

afterEach(() => {
  vi.clearAllMocks();
});

describe("useWorkforceCapabilityGapActions", () => {
  it("invalidates dashboard and recommendations when generating recommendations", async () => {
    const projectId = "project-1";
    const queryClient = new QueryClient({
      defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
    });
    const invalidateSpy = vi.spyOn(queryClient, "invalidateQueries");
    mockedGenerate.mockResolvedValue({
      project_id: projectId,
      recommendations_created: 2,
      recommendations: [],
    });

    const { result } = renderHook(() => useWorkforceCapabilityGapActions(projectId), {
      wrapper: createWrapper(queryClient),
    });

    await act(async () => {
      result.current.triggerGenerateRecommendations();
    });

    await waitFor(() => {
      expect(result.current.generateRecommendationsMutation.isSuccess).toBe(true);
    });

    expect(invalidateSpy).toHaveBeenCalledTimes(2);
    expect(invalidateSpy).toHaveBeenCalledWith({
      queryKey: queryKeys.projectWorkforceDashboard(projectId),
      exact: true,
    });
    expect(invalidateSpy).toHaveBeenCalledWith({
      queryKey: queryKeys.projectRecommendations(projectId),
      exact: true,
    });
    expect(invalidateSpy).not.toHaveBeenCalledWith(
      expect.objectContaining({ queryKey: queryKeys.projectCapabilityGaps(projectId) }),
    );
    expect(invalidateSpy).not.toHaveBeenCalledWith(
      expect.objectContaining({ queryKey: queryKeys.projectWorkforceSummary(projectId) }),
    );
  });

  it("invalidates dashboard, capability gaps, and recommendations on detect", async () => {
    const projectId = "project-1";
    const queryClient = new QueryClient({
      defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
    });
    const invalidateSpy = vi.spyOn(queryClient, "invalidateQueries");
    mockedDetect.mockResolvedValue({
      project_id: projectId,
      detected_count: 1,
      created_count: 1,
      gaps: [],
      risk_alerts_created: 1,
      recommendations_created: 1,
    });

    const { result } = renderHook(() => useWorkforceCapabilityGapActions(projectId), {
      wrapper: createWrapper(queryClient),
    });

    await act(async () => {
      result.current.triggerDetectGaps();
    });

    await waitFor(() => {
      expect(result.current.detectGapsMutation.isSuccess).toBe(true);
    });

    expect(invalidateSpy).toHaveBeenCalledWith({
      queryKey: queryKeys.projectWorkforceDashboard(projectId),
      exact: true,
    });
    expect(invalidateSpy).toHaveBeenCalledWith({
      queryKey: queryKeys.projectCapabilityGaps(projectId),
      exact: true,
    });
    expect(invalidateSpy).toHaveBeenCalledWith({
      queryKey: queryKeys.projectRecommendations(projectId),
      exact: true,
    });
  });

  it("ignores duplicate generate clicks while a mutation is pending", async () => {
    const projectId = "project-1";
    const queryClient = new QueryClient({
      defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
    });
    let resolveGenerate: ((value: WorkforceRecommendationGenerateResponse) => void) | undefined;
    mockedGenerate.mockImplementation(
      () =>
        new Promise((resolve) => {
          resolveGenerate = resolve;
        }),
    );

    const { result } = renderHook(() => useWorkforceCapabilityGapActions(projectId), {
      wrapper: createWrapper(queryClient),
    });

    act(() => {
      result.current.triggerGenerateRecommendations();
      result.current.triggerGenerateRecommendations();
    });

    await waitFor(() => {
      expect(mockedGenerate).toHaveBeenCalledTimes(1);
    });

    await act(async () => {
      resolveGenerate?.({
        project_id: projectId,
        recommendations_created: 0,
        recommendations: [],
      });
      await Promise.resolve();
    });
  });
});
