import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import type { AgentQueryEvidenceLinkRead } from "@/types/workforce";
import { friendlySourceLabel, normalizeEvidenceLinks } from "./evidence-utils";
import { formatWorkforceAnswer } from "./format-workforce-answer";
import { WorkforceAgentAnswer } from "./WorkforceAgentAnswer";
import { WorkforceAgentEvidence } from "./WorkforceAgentEvidence";

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

describe("WorkforceAgentEvidence", () => {
  it("renders evidence when mounted directly", () => {
    render(
      <WorkforceAgentEvidence
        evidenceLinks={[
          buildLink({
            source_table: "utilization_snapshots",
            description: "Latest team utilization 72% on 2026-06-22.",
            source_row_id: "5ee6c6c2-aaaa-bbbb-cccc-dddddddddddd",
          }),
        ]}
      />,
    );

    expect(screen.getByText("Why this answer?")).toBeInTheDocument();
    expect(screen.getByText("Latest team utilization 72% on 2026-06-22.")).toBeInTheDocument();
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
  it("renders simplified utilization headline and data freshness callout", () => {
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
    expect(screen.getByText(/15 days old/)).toBeInTheDocument();
    expect(screen.getByText(/2026-06-22/)).toBeInTheDocument();
    expect(screen.getByText(/confirm the current workload before acting/i)).toBeInTheDocument();
    expect(screen.queryByText("Caution")).not.toBeInTheDocument();
    expect(screen.queryByText(/utilization snapshot/i)).not.toBeInTheDocument();
    expect(screen.queryByText("Suggested next step")).not.toBeInTheDocument();
    expect(screen.getByText("Confidence: Medium")).toBeInTheDocument();
  });

  it("renders stale underloaded answers as data freshness, not caution", () => {
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

    expect(screen.getByText("Data freshness")).toBeInTheDocument();
    expect(screen.getByText(/15 days old/)).toBeInTheDocument();
    expect(screen.queryByText("Caution")).not.toBeInTheDocument();
    expect(screen.queryByText(/utilization snapshot/i)).not.toBeInTheDocument();
  });

  it("does not render caution or next step when the answer omits them", () => {
    render(
      <WorkforceAgentAnswer
        answerText={`Underloaded teams for Northwind Content Shield 4: 1 team(s) below 60%.
Underloaded: Northwind Content Shield 4 Team 2 (48%).
Confidence: High.`}
        evidenceLinks={[]}
        confidenceLevel="high"
      />,
    );

    expect(screen.queryByText("Caution")).not.toBeInTheDocument();
    expect(screen.queryByText("Data freshness")).not.toBeInTheDocument();
    expect(screen.queryByText("Suggested next step")).not.toBeInTheDocument();
  });

  it("renders an explicit next step from the answer text", () => {
    render(
      <WorkforceAgentAnswer
        answerText={`Overloaded teams for Project: 1 team(s) at or above 85%.
Overloaded: Pod A (108%).
Suggested next step: Shift backlog items from Pod A to Pod B.`}
        evidenceLinks={[]}
        confidenceLevel="high"
      />,
    );

    expect(screen.getByText("Suggested next step")).toBeInTheDocument();
    expect(screen.getByText(/Shift backlog items from Pod A to Pod B/)).toBeInTheDocument();
  });

  it("renders underloaded utilization headline without overloaded content", () => {
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
    expect(screen.queryByText(/overloaded/i)).not.toBeInTheDocument();
  });

  it("hides evidence and technical sections from the normal answer view", () => {
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

    expect(screen.queryByText("Why this answer?")).not.toBeInTheDocument();
    expect(screen.queryByText("Top signals")).not.toBeInTheDocument();
    expect(
      screen.queryByText("Latest team utilization 72% on 2026-06-22."),
    ).not.toBeInTheDocument();
    expect(screen.queryByText(/Show all evidence/)).not.toBeInTheDocument();
    expect(screen.queryByText("Technical details")).not.toBeInTheDocument();
    expect(screen.queryByText("Full agent response")).not.toBeInTheDocument();
    expect(screen.queryByText("Response details")).not.toBeInTheDocument();
    expect(screen.queryByText(/Grounded in 23/)).not.toBeInTheDocument();
    expect(screen.queryByText(UTILIZATION_ANSWER)).not.toBeInTheDocument();
  });

  it("renders a concise answer for simple responses", () => {
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
    expect(screen.queryByText("Delivery team at 94% utilization")).not.toBeInTheDocument();
    expect(screen.queryByText("Why this answer?")).not.toBeInTheDocument();
  });
});
