import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { GovernanceRecordProvenancePanel } from "@/features/governance/GovernanceRecordProvenancePanel";
import type { GovernanceAction } from "@/types/governance";

const getActionSourceRecommendation = vi.fn();
const getActionEvidence = vi.fn();

vi.mock("@/lib/queries/governance", () => ({
  getActionSourceRecommendation: (...args: unknown[]) => getActionSourceRecommendation(...args),
  getActionEvidence: (...args: unknown[]) => getActionEvidence(...args),
  getEscalationSourceRecommendation: vi.fn(),
  getEscalationEvidence: vi.fn(),
}));

function action(overrides: Partial<GovernanceAction> = {}): GovernanceAction {
  return {
    id: "action-1",
    org_id: "org-1",
    project_id: "project-1",
    title: "Follow up",
    description: null,
    owner_id: null,
    due_date: null,
    status: "open",
    completed_at: null,
    created_by: null,
    updated_by: null,
    created_at: "2026-07-13T10:00:00Z",
    updated_at: "2026-07-13T10:00:00Z",
    project_name: "Alpha",
    owner_name: null,
    has_ai_source: true,
    evidence_link_count: 3,
    source_recommendation_id: "rec-1",
    source_recommendation_title: "Review blocker",
    ...overrides,
  };
}

function renderPanel(record: GovernanceAction, enabled = true) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return render(
    <QueryClientProvider client={client}>
      <GovernanceRecordProvenancePanel target={{ kind: "action", record }} enabled={enabled} />
    </QueryClientProvider>,
  );
}

describe("GovernanceRecordProvenancePanel", () => {
  beforeEach(() => {
    getActionSourceRecommendation.mockReset();
    getActionEvidence.mockReset();
  });

  it("renders nothing for manual records", () => {
    const { container } = renderPanel(action({ has_ai_source: false, evidence_link_count: 0 }));
    expect(container).toBeEmptyDOMElement();
    expect(getActionSourceRecommendation).not.toHaveBeenCalled();
  });

  it("lazy-loads source recommendation and evidence", async () => {
    getActionSourceRecommendation.mockResolvedValue({
      id: "rec-1",
      title: "Review blocker",
      recommendation_type: "general_governance",
      priority: "high",
      confidence: 0.8,
      generated_at: "2026-07-13T09:00:00Z",
      status: "active",
      accepted_at: null,
      source_type: "ai_recommendation",
      can_view: true,
      source_available: true,
    });
    getActionEvidence.mockResolvedValue([
      {
        id: "link-1",
        link_type: "ai_recommendation_source",
        source_type: "ai_recommendation",
        source_id: "rec-1",
        evidence_id: null,
        recommendation_id: "rec-1",
        conversion_id: "conv-1",
        title: "Review blocker",
        description: null,
        status: "active",
        severity: "high",
        project_id: "project-1",
        project_name: "Alpha",
        occurred_at: null,
        created_at: "2026-07-13T10:00:00Z",
        source_available: true,
        can_view_source: true,
      },
      {
        id: "link-2",
        link_type: "related_dependency",
        source_type: "dependency",
        source_id: "dep-1",
        evidence_id: "dependency:dep-1",
        recommendation_id: "rec-1",
        conversion_id: "conv-1",
        title: "Vendor blocker",
        description: null,
        status: "blocking",
        severity: "high",
        project_id: "project-1",
        project_name: "Alpha",
        occurred_at: null,
        created_at: "2026-07-13T10:00:00Z",
        source_available: true,
        can_view_source: true,
      },
    ]);

    renderPanel(action());

    await waitFor(() => {
      expect(screen.getByText("Review blocker")).toBeInTheDocument();
    });
    expect(screen.getByText("Vendor blocker")).toBeInTheDocument();
    expect(getActionSourceRecommendation).toHaveBeenCalledWith("action-1");
    expect(getActionEvidence).toHaveBeenCalledWith("action-1");
  });

  it("shows unavailable source state", async () => {
    getActionSourceRecommendation.mockResolvedValue({
      id: "rec-1",
      title: "Source unavailable",
      recommendation_type: null,
      priority: null,
      confidence: null,
      generated_at: null,
      status: null,
      accepted_at: null,
      source_type: "ai_recommendation",
      can_view: false,
      source_available: false,
    });
    getActionEvidence.mockResolvedValue([]);

    renderPanel(action({ evidence_link_count: 1 }));

    await waitFor(() => {
      expect(screen.getAllByText("Source unavailable").length).toBeGreaterThan(0);
    });
  });
});
