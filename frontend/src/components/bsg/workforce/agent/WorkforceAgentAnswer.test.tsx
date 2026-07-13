import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import type { AgentQueryEvidenceLinkRead } from "@/types/workforce";
import { friendlySourceLabel, normalizeEvidenceLinks } from "./evidence-utils";
import { formatWorkforceAnswer } from "./format-workforce-answer";
import { WorkforceAgentAnswer } from "./WorkforceAgentAnswer";

const UTILIZATION_ANSWER = `Overloaded teams for Northwind Content Shield 4: 1 team(s) at or above 85%.
Overloaded: Northwind Content Shield 4 Team 1 is at 108%.
Caution: The latest utilization data is 15 days old, so confirm before acting.
Grounded in 23 workforce evidence record(s).
Confidence: Medium.`;

function buildLink(
  overrides: Partial<AgentQueryEvidenceLinkRead> & Pick<AgentQueryEvidenceLinkRead, "source_table">,
): AgentQueryEvidenceLinkRead {
  return {
    id: overrides.id ?? null,
    source_row_id: overrides.source_row_id ?? "abcd1234-5678-90ab-cdef-1234567890ab",
    description: overrides.description ?? "",
    created_at: null,
    ...overrides,
  };
}

describe("evidence-utils", () => {
  it("maps technical table names to friendly labels", () => {
    expect(friendlySourceLabel("utilization_snapshots")).toBe("Utilization snapshot");
    expect(friendlySourceLabel("capability_gaps")).toBe("Capability gap");
  });

  it("deduplicates repeated evidence entries", () => {
    const links = [
      buildLink({
        source_table: "utilization_snapshots",
        description: "Team Alpha at 92%",
        source_row_id: "11111111-aaaa-bbbb-cccc-dddddddddddd",
      }),
      buildLink({
        source_table: "utilization_snapshots",
        description: "Team Alpha at 92%",
        source_row_id: "22222222-aaaa-bbbb-cccc-dddddddddddd",
      }),
    ];

    expect(normalizeEvidenceLinks(links)).toHaveLength(1);
  });

  it("removes duplicate technical labels from descriptions", () => {
    const [item] = normalizeEvidenceLinks([
      buildLink({
        source_table: "utilization_snapshots",
        description: "utilization_snapshots",
      }),
    ]);

    expect(item?.description).toBe("");
    expect(item?.sourceLabel).toBe("Utilization snapshot");
  });
});

describe("formatWorkforceAnswer integration", () => {
  it("parses utilization overload answers", () => {
    const formatted = formatWorkforceAnswer(UTILIZATION_ANSWER);
    expect(formatted.headline).toBe("1 team is overloaded");
    expect(formatted.dataFreshness).toBeTruthy();
    expect(formatted.caution).toBeNull();
  });
});

describe("WorkforceAgentAnswer", () => {
  it("renders a reader-friendly utilization answer without technical evidence", () => {
    render(
      <WorkforceAgentAnswer
        answerText={UTILIZATION_ANSWER}
        evidenceLinks={[
          buildLink({
            source_table: "utilization_snapshots",
            description: "Latest team utilization 72% on 2026-06-22.",
            source_row_id: "5ee6c6c2-aaaa-bbbb-cccc-dddddddddddd",
          }),
        ]}
        confidenceLevel="medium"
        modelUsed={null}
        latencyMs={2607}
      />,
    );

    expect(screen.getByText("1 team is overloaded")).toBeInTheDocument();
    expect(screen.getByText(/Northwind Content Shield 4 Team 1 is at 108%/)).toBeInTheDocument();
    expect(screen.getByText("Data freshness")).toBeInTheDocument();
    expect(screen.getByText(/confirm the current workload before acting/i)).toBeInTheDocument();
    expect(screen.queryByText("Evidence (1)")).not.toBeInTheDocument();
    expect(screen.queryByText("Utilization snapshot")).not.toBeInTheDocument();
    expect(screen.queryByText(/Ref/)).not.toBeInTheDocument();
    expect(screen.getByText("Confidence: Medium")).toBeInTheDocument();
    expect(screen.queryByText("2607 ms")).not.toBeInTheDocument();
  });

  it("renders stale underloaded answers as data freshness, not raw warning text", () => {
    render(
      <WorkforceAgentAnswer
        answerText={`Underloaded teams for Northwind Content Shield 4: 1 team(s) below 60%.
Underloaded: Northwind Content Shield 4 Team 2 (48%).
Caution: the latest utilization snapshot is 15 days old (older than 14 days), so these figures may be stale.
Confidence: High.`}
        evidenceLinks={[]}
        confidenceLevel="high"
      />,
    );

    expect(screen.getByText("1 team is underutilized")).toBeInTheDocument();
    expect(screen.getByText("Data freshness")).toBeInTheDocument();
    expect(screen.getByText(/15 days old/)).toBeInTheDocument();
    expect(screen.getByText("Confidence: High")).toBeInTheDocument();
  });

  it("does not invent sections when the answer omits them", () => {
    render(
      <WorkforceAgentAnswer
        answerText={`Underloaded teams for Northwind Content Shield 4: 1 team(s) below 60%.
Underloaded: Northwind Content Shield 4 Team 2 (48%).
Confidence: High.`}
        evidenceLinks={[]}
        confidenceLevel="high"
      />,
    );

    expect(screen.queryByText("Data freshness")).not.toBeInTheDocument();
    expect(screen.queryByText("Recommended action")).not.toBeInTheDocument();
    expect(screen.getByText("1 team is underutilized")).toBeInTheDocument();
  });

  it("shows an explicit next step as a simple callout", () => {
    render(
      <WorkforceAgentAnswer
        answerText={`Overloaded teams for Project: 1 team(s) at or above 85%.
Overloaded: Pod A (108%).
Suggested next step: Shift backlog items from Pod A to Pod B.`}
        evidenceLinks={[]}
        confidenceLevel="high"
      />,
    );

    expect(screen.getByText("Recommended action")).toBeInTheDocument();
    expect(screen.getByText("Shift backlog items from Pod A to Pod B.")).toBeInTheDocument();
  });

  it("renders underloaded utilization as a clear headline", () => {
    render(
      <WorkforceAgentAnswer
        answerText={`Underloaded teams for Northwind Content Shield 4: 1 team(s) below 60%.
Underloaded: Northwind Content Shield 4 Team 2 (48%).
Confidence: High.`}
        evidenceLinks={[]}
        confidenceLevel="high"
      />,
    );

    expect(screen.getByText("1 team is underutilized")).toBeInTheDocument();
    expect(screen.getByText(/Team 2 \(48%\)/)).toBeInTheDocument();
  });

  it("hides evidence and grounded technical text from the main answer", () => {
    render(
      <WorkforceAgentAnswer
        answerText={UTILIZATION_ANSWER}
        evidenceLinks={[
          buildLink({
            source_table: "utilization_snapshots",
            description: "Latest team utilization 72% on 2026-06-22.",
            source_row_id: "5ee6c6c2-aaaa-bbbb-cccc-dddddddddddd",
          }),
        ]}
        confidenceLevel="medium"
        modelUsed={null}
        latencyMs={2607}
      />,
    );

    expect(screen.queryByText("Evidence (1)")).not.toBeInTheDocument();
    expect(screen.queryByText("Utilization snapshot")).not.toBeInTheDocument();
    expect(screen.queryByText(/Grounded in 23/)).not.toBeInTheDocument();
    expect(screen.queryByText(/Latest team utilization 72% on 2026-06-22/)).not.toBeInTheDocument();
  });

  it("renders a concise answer as the main message without evidence", () => {
    render(
      <WorkforceAgentAnswer
        answerText="Two teams are above the capacity threshold."
        evidenceLinks={[
          buildLink({
            source_table: "utilization_snapshots",
            description: "Delivery team at 94% utilization",
            source_row_id: "5ee6c6c2-aaaa-bbbb-cccc-dddddddddddd",
          }),
        ]}
        confidenceLevel="high"
        modelUsed={null}
        latencyMs={2607}
      />,
    );

    expect(
      screen.getByRole("heading", { name: "Two teams are above the capacity threshold." }),
    ).toBeInTheDocument();
    expect(screen.queryByText(/Delivery team at 94% utilization/)).not.toBeInTheDocument();
  });

  it("turns training gaps into a non-technical business summary", () => {
    render(
      <WorkforceAgentAnswer
        answerText={`Training gaps for Northwind Content Shield 4: 48 open (45 mandatory incomplete, 0 expired/failed).
Grounded in 23 workforce evidence record(s). Figures are aggregated at the team level; individual annotator details are not exposed.
Confidence: High.`}
        evidenceLinks={[
          buildLink({
            source_table: "training_programs",
            description: "gap (mandatory_training_incomplete) affecting 9 (aggregated).",
            source_row_id: "bcce8242-aaaa-bbbb-cccc-dddddddddddd",
          }),
        ]}
        confidenceLevel="high"
      />,
    );

    expect(screen.getByText("48 training gaps need attention")).toBeInTheDocument();
    expect(
      screen.getByText(
        "45 mandatory trainings are incomplete, no expired or failed trainings were found.",
      ),
    ).toBeInTheDocument();
    expect(screen.getByText("Confidence: High")).toBeInTheDocument();
    expect(screen.queryByText(/Evidence/)).not.toBeInTheDocument();
    expect(screen.queryByText(/Grounded in/)).not.toBeInTheDocument();
    expect(screen.queryByText(/Ref/)).not.toBeInTheDocument();
  });

  it("turns SME coverage into a scannable status and action", () => {
    render(
      <WorkforceAgentAnswer
        answerText={`SME coverage for Northwind Content Shield 4: 7 SME(s) (30% of 23 active annotators).
SME coverage is below 50%; consider certifying more annotators.
Confidence: High.`}
        evidenceLinks={[]}
        confidenceLevel="high"
      />,
    );

    expect(screen.getByText("Needs attention")).toBeInTheDocument();
    expect(screen.getByText("SME coverage is below target")).toBeInTheDocument();
    expect(screen.getByText("7 SMEs cover 30% of 23 active annotators.")).toBeInTheDocument();
    expect(screen.getByText("SME coverage is below 50%.")).toBeInTheDocument();
    expect(screen.getByText("Recommended action")).toBeInTheDocument();
    expect(screen.getByText("Certify more annotators.")).toBeInTheDocument();
  });
});
