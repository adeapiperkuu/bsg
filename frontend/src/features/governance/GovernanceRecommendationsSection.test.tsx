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

function renderSection() {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return render(
    <QueryClientProvider client={client}>
      <GovernanceRecommendationsSection focusProjectId="p1" canWrite />
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
    listMock.mockResolvedValue({
      items: [],
      rule_based: [],
      total: 0,
      ai_enabled: true,
      can_generate: true,
    });
  });

  it("loads AI list without calling generate on mount", async () => {
    renderSection();
    await waitFor(() => expect(listMock).toHaveBeenCalled());
    expect(generateMock).not.toHaveBeenCalled();
    expect(screen.queryByText("Operational Recommendations")).not.toBeInTheDocument();
    expect(screen.queryByText("Rule-based")).not.toBeInTheDocument();
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
      recommendations: [
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
          suggested_actions: [
            {
              label: "Assign owner",
              description: "Assign one accountable owner.",
              action_type: "assign_owner",
              target_entity_type: null,
              target_entity_id: null,
            },
          ],
          evidence: [
            {
              evidence_id: "dependency:1",
              entity_type: "dependency",
              entity_id: "1",
              project_id: "p1",
              title: "Vendor integration",
              summary: "blocking",
              status: "blocking",
              severity: "high",
              occurred_at: null,
            },
          ],
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
      rule_based_fallback: [],
      reused: false,
      fallback_used: false,
      fallback_reason: null,
      generation_request_id: "g1",
      evidence_hash: "abc",
      candidates_returned: 1,
      candidates_persisted: 1,
      candidates_rejected_grounding: 0,
      duplicates_suppressed: 0,
      duration_ms: 120,
      projects_attempted: 2,
      projects_with_recommendations: 2,
      projects_reused: 0,
      projects_using_fallback: 0,
      project_failures: {},
    });

    renderSection();
    const generateButton = await screen.findByRole("button", {
      name: /Generate AI recommendations/i,
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
    expect(screen.getByText(/AI Generated/)).toBeInTheDocument();
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
