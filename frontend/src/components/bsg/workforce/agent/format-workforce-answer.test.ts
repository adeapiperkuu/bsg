import { describe, expect, it } from "vitest";
import {
  formatDataFreshnessNotice,
  formatWorkforceAnswer,
  humanizeWording,
  isStaleUtilizationWarning,
} from "./format-workforce-answer";

const UTILIZATION_ANSWER = `Overloaded teams for Northwind Content Shield 4: 1 team(s) at or above 85%.
Overloaded: Northwind Content Shield 4 Team 1 is at 108%.
Caution: The latest utilization data is 15 days old, so confirm before acting.
Grounded in 23 workforce evidence record(s).
Confidence: Medium.`;

describe("humanizeWording", () => {
  it("replaces technical plural patterns", () => {
    expect(humanizeWording("1 team(s) at or above 85%")).toBe("1 team at or above 85%");
    expect(humanizeWording("Grounded in 23 workforce evidence record(s).")).toBe(
      "Grounded in 23 workforce records.",
    );
  });
});

describe("formatWorkforceAnswer", () => {
  it("formats utilization answers with headline, summary, and caution", () => {
    const formatted = formatWorkforceAnswer(UTILIZATION_ANSWER);

    expect(formatted.headline).toBe("1 team is overloaded");
    expect(formatted.summary).toContain("Northwind Content Shield 4 Team 1 is at 108%");
    expect(formatted.caution).toBeNull();
    expect(formatted.dataFreshness).toContain("15 days old");
    expect(formatted.dataFreshness).toMatch(/confirm the current workload/i);
    expect(formatted.nextStep).toBeNull();
    expect(formatted.parsedConfidence).toBe("Medium");
    expect(formatted.groundedIn).toContain("23 workforce records");
  });

  it("moves grounded and confidence wording out of the primary headline/summary", () => {
    const formatted = formatWorkforceAnswer(UTILIZATION_ANSWER);

    expect(formatted.headline).not.toContain("Grounded in");
    expect(formatted.summary).not.toContain("Confidence:");
    expect(formatted.summary).not.toContain("evidence record");
  });

  it("formats underloaded utilization answers with an underutilized headline", () => {
    const formatted = formatWorkforceAnswer(
      `Underloaded teams for Northwind Content Shield 4: 1 team(s) below 60%.
Underloaded: Northwind Content Shield 4 Team 2 (48%).
Confidence: High.`,
    );

    expect(formatted.headline).toBe("1 team is underutilized");
    expect(formatted.summary).toContain("Northwind Content Shield 4 Team 2 (48%)");
    expect(formatted.nextStep).toBeNull();
    expect(formatted.caution).toBeNull();
    expect(formatted.dataFreshness).toBeNull();
  });

  it("renders explicit next step only when present in the answer", () => {
    const formatted = formatWorkforceAnswer(
      `Overloaded teams for Project: 1 team(s) at or above 85%.
Overloaded: Pod A (108%).
Suggested next step: Rebalance workload from Pod A to Pod B this week.`,
    );

    expect(formatted.nextStep).toBe("Rebalance workload from Pod A to Pod B this week.");
  });

  it("does not invent caution or next step for plain utilization answers", () => {
    const formatted = formatWorkforceAnswer(
      `Underloaded teams for Project: 1 team(s) below 60%.
Underloaded: Pod B (48%).`,
    );

    expect(formatted.caution).toBeNull();
    expect(formatted.dataFreshness).toBeNull();
    expect(formatted.nextStep).toBeNull();
  });

  it("rewrites stale utilization backend notes as data freshness", () => {
    const formatted = formatWorkforceAnswer(
      `Capacity for Project: 12 active annotators across 2 teams.
Note: the latest utilization snapshot is 20 days old (older than 14 days), so live workload may be out of date.`,
    );

    expect(formatted.caution).toBeNull();
    expect(formatted.dataFreshness).toContain("20 days old");
    expect(formatted.dataFreshness).not.toMatch(/utilization snapshot/i);
  });

  it("keeps non-freshness cautions as caution", () => {
    const formatted = formatWorkforceAnswer(
      "Training gap: 4 annotators have incomplete mandatory training.\nCaution: Certification renewals are overdue.\nConfidence: Low.",
    );

    expect(formatted.caution).toContain("Certification renewals");
    expect(formatted.dataFreshness).toBeNull();
  });

  it("formats mixed utilization summaries without defaulting to overloaded headline", () => {
    const formatted = formatWorkforceAnswer(
      `Utilization for Northwind Content Shield 4: 1 team(s) at or above 85% and 1 below 60%.
Overloaded: Northwind Content Shield 4 Team 1 (108%).
Underloaded: Northwind Content Shield 4 Team 2 (48%).`,
    );

    expect(formatted.headline).toBe("Teams show mixed utilization");
  });

  it("includes snapshot date in data freshness when available in the answer", () => {
    expect(
      formatDataFreshnessNotice(
        "the latest utilization snapshot is 15 days old",
        "Latest team utilization 72% on 2026-06-22.",
      ),
    ).toBe(
      "This answer is based on utilization data from 2026-06-22. Because it is 15 days old, confirm the current workload before acting.",
    );
    expect(isStaleUtilizationWarning("the latest utilization data is 15 days old")).toBe(true);
    expect(isStaleUtilizationWarning("no utilization snapshots are available")).toBe(false);
  });
});
