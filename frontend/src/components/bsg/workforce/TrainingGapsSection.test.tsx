import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";
import type { TrainingGapRow, TrainingGapSummaryRead } from "@/types/workforce";
import { TrainingGapsSection } from "./TrainingGapsSection";

const rows: TrainingGapRow[] = [
  {
    team_id: "team-1",
    team_name: "Team 1",
    skill_id: null,
    skill_name: null,
    training_program_id: "training-1",
    training_program_name: "Mandatory security",
    certification_id: null,
    certification_name: null,
    gap_type: "mandatory_training_incomplete",
    affected_count: 45,
  },
  {
    team_id: "team-2",
    team_name: "Team 2",
    skill_id: null,
    skill_name: null,
    training_program_id: null,
    training_program_name: null,
    certification_id: "cert-1",
    certification_name: "Cloud certification",
    gap_type: "expired_certification",
    affected_count: 1,
  },
  {
    team_id: "team-3",
    team_name: "Team 3",
    skill_id: null,
    skill_name: null,
    training_program_id: null,
    training_program_name: null,
    certification_id: "cert-2",
    certification_name: "Quality certification",
    gap_type: "pending_certification_review",
    affected_count: 2,
  },
];

const summary: TrainingGapSummaryRead = {
  project_id: "project-1",
  total_training_gaps: 48,
  mandatory_training_incomplete: 45,
  expired_or_failed_training: 0,
  expired_certifications: 1,
  pending_certification_reviews: 2,
  rows,
};

function renderSection() {
  return render(
    <TrainingGapsSection
      canReadInternalWorkforce
      trainingGapsLoading={false}
      trainingGapsError={null}
      trainingGaps={summary}
      filteredTrainingGapRows={rows}
      trainingGapRowKey={(row, index) => `${row.gap_type}-${index}`}
      gapRowSubject={(row) => row.training_program_name ?? row.certification_name ?? "Missing"}
    />,
  );
}

describe("TrainingGapsSection", () => {
  it("filters rows when a training gap summary chip is clicked", async () => {
    const user = userEvent.setup();
    renderSection();

    expect(screen.getByText("Mandatory security")).toBeInTheDocument();
    expect(screen.getByText("Cloud certification")).toBeInTheDocument();
    expect(screen.getByText("Quality certification")).toBeInTheDocument();

    const expiredButton = screen.getByRole("button", { name: "1 expired certifications" });
    await user.click(expiredButton);

    expect(expiredButton).toHaveAttribute("aria-pressed", "true");
    expect(screen.queryByText("Mandatory security")).not.toBeInTheDocument();
    expect(screen.getByText("Cloud certification")).toBeInTheDocument();
    expect(screen.queryByText("Quality certification")).not.toBeInTheDocument();

    await user.click(expiredButton);

    expect(expiredButton).toHaveAttribute("aria-pressed", "false");
    expect(screen.getByText("Mandatory security")).toBeInTheDocument();
    expect(screen.getByText("Cloud certification")).toBeInTheDocument();
    expect(screen.getByText("Quality certification")).toBeInTheDocument();
  });

  it("marks all visible summary chips as buttons", () => {
    renderSection();

    expect(screen.getByRole("button", { name: "45 mandatory incomplete" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "1 expired certifications" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "2 pending reviews" })).toBeInTheDocument();
  });
});
