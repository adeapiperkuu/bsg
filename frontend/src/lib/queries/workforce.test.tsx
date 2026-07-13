import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { renderHook, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";

import {
  getProjectSkillMatrix,
  getProjectTrainingGaps,
  getProjectWorkforceDashboard,
  getProjectWorkforceSummary,
  listProjectCapabilityGaps,
  listProjectUtilization,
} from "@/lib/api";
import {
  WORKFORCE_CATALOG_STALE_TIME_MS,
  WORKFORCE_PROJECT_STALE_TIME_MS,
  queryKeys,
} from "@/lib/queries/keys";
import {
  projectCapabilityGapsQueryOptions,
  projectSkillMatrixQueryOptions,
  projectTrainingGapsQueryOptions,
  projectUtilizationQueryOptions,
  projectWorkforceDashboardQueryOptions,
  projectWorkforceSummaryQueryOptions,
  seedWorkforceSectionCaches,
  useProjectCapabilityGapsQuery,
  useProjectSkillMatrixQuery,
  useProjectTrainingGapsQuery,
  useProjectUtilizationQuery,
  useProjectWorkforceDashboardQuery,
  useProjectWorkforceSummary,
  workforceSkillsQueryOptions,
} from "@/lib/queries/workforce";
import type { ProjectWorkforceDashboardRead } from "@/types/workforce";

vi.mock("@/lib/api", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/lib/api")>();
  return {
    ...actual,
    getProjectWorkforceDashboard: vi.fn(),
    getProjectWorkforceSummary: vi.fn(),
    listProjectUtilization: vi.fn(),
    getProjectSkillMatrix: vi.fn(),
    getProjectTrainingGaps: vi.fn(),
    listProjectCapabilityGaps: vi.fn(),
  };
});

const mockedDashboard = vi.mocked(getProjectWorkforceDashboard);
const mockedSummary = vi.mocked(getProjectWorkforceSummary);
const mockedUtilization = vi.mocked(listProjectUtilization);
const mockedMatrix = vi.mocked(getProjectSkillMatrix);
const mockedTraining = vi.mocked(getProjectTrainingGaps);
const mockedGaps = vi.mocked(listProjectCapabilityGaps);

function createWrapper(queryClient: QueryClient) {
  return function Wrapper({ children }: { children: ReactNode }) {
    return <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>;
  };
}

function buildDashboard(projectId: string): ProjectWorkforceDashboardRead {
  return {
    project_id: projectId,
    summary: { project_id: projectId, teams: [], annotators: [] },
    utilization: [],
    skill_matrix: { project_id: projectId, rows: [] },
    training_gaps: {
      project_id: projectId,
      total_training_gaps: 0,
      mandatory_training_incomplete: 0,
      expired_or_failed_training: 0,
      expired_certifications: 0,
      pending_certification_reviews: 0,
      rows: [],
    },
    capability_gaps: [],
    recommendations: {
      data: [],
      assignable_owners: [],
      pagination: { limit: 100 },
    },
  };
}

afterEach(() => {
  vi.clearAllMocks();
});

describe("workforce query cache options", () => {
  it("uses longer staleTime for project workforce aggregates", () => {
    expect(projectWorkforceSummaryQueryOptions("p1").staleTime).toBe(
      WORKFORCE_PROJECT_STALE_TIME_MS,
    );
    expect(projectWorkforceDashboardQueryOptions("p1", true).staleTime).toBe(
      WORKFORCE_PROJECT_STALE_TIME_MS,
    );
    expect(projectSkillMatrixQueryOptions("p1", true).staleTime).toBe(
      WORKFORCE_PROJECT_STALE_TIME_MS,
    );
    expect(projectTrainingGapsQueryOptions("p1", true).staleTime).toBe(
      WORKFORCE_PROJECT_STALE_TIME_MS,
    );
    expect(projectCapabilityGapsQueryOptions("p1", true).staleTime).toBe(
      WORKFORCE_PROJECT_STALE_TIME_MS,
    );
    expect(projectUtilizationQueryOptions("p1", true).staleTime).toBe(
      WORKFORCE_PROJECT_STALE_TIME_MS,
    );
  });

  it("uses catalog staleTime for workforce taxonomies", () => {
    expect(workforceSkillsQueryOptions(true).staleTime).toBe(WORKFORCE_CATALOG_STALE_TIME_MS);
  });

  it("keeps previous project data while switching projects", () => {
    expect(projectWorkforceSummaryQueryOptions("p1").placeholderData).toBeTypeOf("function");
    expect(projectWorkforceDashboardQueryOptions("p1", true).placeholderData).toBeTypeOf(
      "function",
    );
    expect(projectSkillMatrixQueryOptions("p1", true).placeholderData).toBeTypeOf("function");
    expect(projectCapabilityGapsQueryOptions("p1", true).placeholderData).toBeTypeOf("function");
  });
});

describe("useProjectWorkforceDashboardQuery", () => {
  it("loads bundled dashboard without firing separate section queries", async () => {
    const projectId = "project-1";
    const queryClient = new QueryClient({
      defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
    });
    mockedDashboard.mockResolvedValue(buildDashboard(projectId));

    const { result } = renderHook(
      () => {
        const dashboard = useProjectWorkforceDashboardQuery(projectId, true);
        // Mirror Workforce page: keep section hooks disabled while dashboard is used.
        useProjectWorkforceSummary(null, false);
        useProjectUtilizationQuery(projectId, false);
        useProjectSkillMatrixQuery(projectId, false);
        useProjectTrainingGapsQuery(projectId, false);
        useProjectCapabilityGapsQuery(projectId, false);
        return dashboard;
      },
      { wrapper: createWrapper(queryClient) },
    );

    await waitFor(() => {
      expect(result.current.isSuccess).toBe(true);
    });

    expect(mockedDashboard).toHaveBeenCalledTimes(1);
    expect(mockedDashboard).toHaveBeenCalledWith(projectId);
    expect(mockedSummary).not.toHaveBeenCalled();
    expect(mockedUtilization).not.toHaveBeenCalled();
    expect(mockedMatrix).not.toHaveBeenCalled();
    expect(mockedTraining).not.toHaveBeenCalled();
    expect(mockedGaps).not.toHaveBeenCalled();
    expect(result.current.data?.project_id).toBe(projectId);
  });

  it("seeds section caches from bundled dashboard data", () => {
    const projectId = "project-1";
    const queryClient = new QueryClient();
    const dashboard = buildDashboard(projectId);
    dashboard.training_gaps.total_training_gaps = 3;

    seedWorkforceSectionCaches(queryClient, projectId, dashboard);

    expect(queryClient.getQueryData(queryKeys.projectWorkforceSummary(projectId))).toEqual(
      dashboard.summary,
    );
    expect(queryClient.getQueryData(queryKeys.projectTrainingGaps(projectId))).toEqual(
      dashboard.training_gaps,
    );
    expect(queryClient.getQueryData(queryKeys.projectRecommendations(projectId))).toEqual(
      dashboard.recommendations,
    );
  });
});
