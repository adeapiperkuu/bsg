import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { WorkforceRecommendationsPanel } from "./WorkforceRecommendationsPanel";

vi.mock("@/features/mitigation-recommendations/hooks/useProjectRecommendations", () => ({
  useProjectRecommendationsQuery: () => ({
    data: {
      data: [
        {
          title: "Certify backup SMEs",
          severity: "high",
          confidence_score: 0.75,
          is_estimated: true,
          project_id: "project-1",
          risks: [
            {
              recommendation_id: "rec-1",
              source_risk_id: "risk-1",
              source_risk_title: "SME coverage below target",
              source_risk_type: "workforce_imbalance",
              description: "Train two backup SMEs for the impacted workflow.",
              status: "pending",
              confidence_score: 0.75,
              is_estimated: true,
              owner_type: null,
              owner_id: null,
              owner_label: null,
            },
          ],
          statuses: ["pending"],
          descriptions: ["Train two backup SMEs for the impacted workflow."],
        },
        {
          title: "Protect delivery milestone",
          severity: "high",
          confidence_score: 0.8,
          is_estimated: false,
          project_id: "project-1",
          risks: [
            {
              recommendation_id: "rec-2",
              source_risk_id: "risk-2",
              source_risk_title: "Milestone is at risk",
              source_risk_type: "schedule_slippage",
              description: "Replan the milestone.",
              status: "pending",
              confidence_score: 0.8,
              is_estimated: false,
              owner_type: null,
              owner_id: null,
              owner_label: null,
            },
          ],
          statuses: ["pending"],
          descriptions: ["Replan the milestone."],
        },
      ],
    },
    isLoading: false,
    isError: false,
  }),
  useAcceptRecommendationMutation: () => ({ mutate: vi.fn(), isPending: false }),
  useRejectRecommendationMutation: () => ({ mutate: vi.fn(), isPending: false }),
}));

describe("WorkforceRecommendationsPanel", () => {
  it("shows grouped workforce recommendations and filters out non-workforce ones", () => {
    render(<WorkforceRecommendationsPanel projectId="project-1" canManage />);

    expect(screen.getByText("Certify backup SMEs")).toBeInTheDocument();
    expect(
      screen.getByText("Train two backup SMEs for the impacted workflow."),
    ).toBeInTheDocument();
    expect(screen.getByText("Linked gap: SME coverage below target")).toBeInTheDocument();
    expect(screen.queryByText("Protect delivery milestone")).not.toBeInTheDocument();
    expect(screen.queryByText("No workforce recommendations yet")).not.toBeInTheDocument();
  });
});
