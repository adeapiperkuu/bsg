import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { GovernanceRecommendationsSection } from "@/features/governance/GovernanceRecommendationsSection";

const listMock = vi.fn();
const generateMock = vi.fn();
const dismissMock = vi.fn();
const feedbackMock = vi.fn();
const regenerateMock = vi.fn();
const jobsMock = vi.fn();
const jobMock = vi.fn();

Object.defineProperty(Element.prototype, "scrollIntoView", {
  configurable: true,
  value: vi.fn(),
});

vi.mock("@/lib/queries/governance", async () => {
  const actual = await vi.importActual<typeof import("@/lib/queries/governance")>(
    "@/lib/queries/governance",
  );
  return {
    ...actual,
    listGovernanceAIRecommendations: (...args: unknown[]) => listMock(...args),
    generateGovernanceAIRecommendations: (...args: unknown[]) => generateMock(...args),
    dismissGovernanceAIRecommendation: (...args: unknown[]) => dismissMock(...args),
    submitGovernanceAIRecommendationFeedback: (...args: unknown[]) => feedbackMock(...args),
    regenerateGovernanceAIRecommendation: (...args: unknown[]) => regenerateMock(...args),
    governanceAIRecommendationsQueryOptions: (params: Record<string, unknown> = {}) => ({
      queryKey: ["governance", "ai-recommendations", params],
      queryFn: () => listMock(params),
    }),
    governanceJobsQueryOptions: (params: Record<string, unknown> = {}) => ({
      queryKey: ["governance", "jobs", params],
      queryFn: () => jobsMock(params),
    }),
    governanceJobQueryOptions: (jobId: string) => ({
      queryKey: ["governance", "jobs", jobId],
      queryFn: () => jobMock(jobId),
    }),
  };
});

vi.mock("sonner", () => ({
  toast: {
    success: vi.fn(),
    warning: vi.fn(),
    error: vi.fn(),
    message: vi.fn(),
  },
}));

function renderSection(enabled = true) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return render(
    <QueryClientProvider client={client}>
      <GovernanceRecommendationsSection canWrite enabled={enabled} />
    </QueryClientProvider>,
  );
}

function recommendationForProject(
  id: string,
  projectId: string,
  projectName: string,
  title: string,
) {
  return {
    id,
    scope: "project",
    project_id: projectId,
    project_name: projectName,
    recommendation_type: "dependency_mitigation",
    title,
    narrative: `${projectName} governance narrative.`,
    rationale: "Evidence-backed rationale.",
    priority: "medium",
    confidence: 0.8,
    suggested_actions: [],
    evidence: [],
    status: "active",
    generated_at: new Date().toISOString(),
    expires_at: null,
    can_regenerate: true,
    can_dismiss: true,
    is_ai_generated: true,
    source_type: "ai",
    is_stale: false,
    evidence_hash: `hash-${id}`,
  };
}

describe("GovernanceRecommendationsSection", () => {
  beforeEach(() => {
    listMock.mockReset();
    generateMock.mockReset();
    dismissMock.mockReset();
    feedbackMock.mockReset();
    regenerateMock.mockReset();
    jobsMock.mockReset();
    jobMock.mockReset();
    listMock.mockResolvedValue({
      items: [],
      rule_based: [],
      total: 0,
      ai_enabled: true,
      can_generate: true,
    });
    jobsMock.mockResolvedValue([]);
  });

  it("loads AI list without calling generate on mount", async () => {
    renderSection();
    await waitFor(() => expect(listMock).toHaveBeenCalled());
    expect(generateMock).not.toHaveBeenCalled();
    expect(screen.queryByText("Operational Recommendations")).not.toBeInTheDocument();
    expect(screen.queryByText("Rule-based")).not.toBeInTheDocument();
    expect(screen.queryByRole("tab", { name: "AI Recs" })).not.toBeInTheDocument();
    expect(screen.queryByText("Escalation Suggestions")).not.toBeInTheDocument();
  });

  it("does not load recommendation tools before the section is enabled", async () => {
    renderSection(false);

    await Promise.resolve();

    expect(listMock).not.toHaveBeenCalled();
  });

  it("generates on explicit button click and shows AI card", async () => {
    const user = userEvent.setup();
    listMock.mockResolvedValue({
      items: [],
      rule_based: [],
      total: 0,
      ai_enabled: true,
      can_generate: true,
    });
    generateMock.mockResolvedValue({
      job_id: "job-1",
      job_type: "ai_recommendation_generate",
      status: "queued",
      deduplicated: false,
    });
    jobMock.mockResolvedValue({
      id: "job-1",
      status: "succeeded",
      progress_stage: "completed",
      progress_percent: 100,
      attempt_count: 1,
      max_attempts: 3,
      retryable: false,
      cancellable: false,
      error_message: null,
    });

    renderSection();
    const generateButton = await screen.findByRole("button", {
      name: /^Generate$/i,
    });
    // After generate, list refetch returns the persisted card.
    listMock.mockResolvedValue({
      items: [
        {
          id: "rec-1",
          scope: "project",
          project_id: "p1",
          project_name: "Project Alpha",
          recommendation_type: "dependency_mitigation",
          title: "Prioritize vendor integration dependency",
          narrative: "Project Alpha has unresolved blocking dependencies.",
          rationale: "Blocking dependencies increase milestone risk.",
          priority: "high",
          confidence: 0.84,
          suggested_actions: [],
          evidence: [],
          status: "active",
          generated_at: new Date().toISOString(),
          expires_at: null,
          can_regenerate: true,
          can_dismiss: true,
          is_ai_generated: true,
          source_type: "ai",
          is_stale: false,
          evidence_hash: "abc",
        },
      ],
      rule_based: [],
      total: 1,
      ai_enabled: true,
      can_generate: true,
    });
    await user.click(generateButton);
    await waitFor(() => expect(generateMock).toHaveBeenCalledTimes(1));
    expect(generateMock).toHaveBeenCalledWith({ scope: "project", force: false });
    expect(listMock).toHaveBeenCalledWith(
      expect.objectContaining({ scope: "project", limit: 100 }),
    );
    await waitFor(() =>
      expect(screen.getByText("Prioritize vendor integration dependency")).toBeInTheDocument(),
    );
    expect(screen.queryByText(/AI Generated/)).not.toBeInTheDocument();
  });

  it("disables duplicate generation while the equivalent job is active", async () => {
    const user = userEvent.setup();
    generateMock.mockResolvedValue({
      job_id: "job-active",
      job_type: "ai_recommendation_generate",
      status: "queued",
      deduplicated: false,
    });
    jobMock.mockResolvedValue({
      id: "job-active",
      status: "running",
      progress_stage: "generating",
      progress_percent: 45,
      attempt_count: 1,
      max_attempts: 3,
      retryable: false,
      cancellable: true,
      error_message: null,
    });

    renderSection();
    const button = await screen.findByRole("button", { name: /^Generate$/i });
    await user.click(button);
    await waitFor(() => expect(button).toBeDisabled());
    await user.click(button);
    expect(generateMock).toHaveBeenCalledTimes(1);
  });

  it("filters project recommendations with a dropdown instead of one long list", async () => {
    const user = userEvent.setup();
    listMock.mockResolvedValue({
      items: [
        recommendationForProject("rec-a", "p1", "Project Alpha", "Alpha recommendation"),
        recommendationForProject("rec-b", "p2", "Project Beta", "Beta recommendation"),
      ],
      rule_based: [],
      total: 2,
      ai_enabled: true,
      can_generate: true,
    });

    renderSection();

    const projectSelect = await screen.findByRole("combobox", {
      name: "Recommendation project",
    });
    expect(projectSelect).toHaveTextContent("Project Alpha");
    expect(screen.getByText("Alpha recommendation")).toBeVisible();
    expect(screen.queryByText("Beta recommendation")).not.toBeInTheDocument();

    projectSelect.focus();
    await user.keyboard("{Enter}{ArrowDown}{Enter}");

    await waitFor(() => {
      expect(projectSelect).toHaveTextContent("Project Beta");
      expect(screen.getByText("Beta recommendation")).toBeVisible();
      expect(screen.queryByText("Alpha recommendation")).not.toBeInTheDocument();
    });
  });
});
