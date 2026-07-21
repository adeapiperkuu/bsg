import { describe, expect, it } from "vitest";

import type { DeliveryPortfolioResponse } from "@/lib/api";
import { summarizeClientPortfolio } from "./client-dashboard-utils";

function entry(
  id: string,
  name: string,
  confidence: number,
  trafficLight: "green" | "yellow" | "red",
  hasSufficientData = true,
): DeliveryPortfolioResponse["projects"][number] {
  return {
    project_id: id,
    dashboard: {
      overview: { project: { name }, has_sufficient_data: hasSufficientData },
      milestones: [],
      confidence,
      risks: [],
      bottlenecks: [],
      traffic_light: trafficLight,
      daily_summary: null,
    },
  };
}

describe("summarizeClientPortfolio", () => {
  it("averages confidence only across projects with sufficient data", () => {
    const result = summarizeClientPortfolio({
      projects: [
        entry("one", "Alpha", 92.4, "green"),
        entry("two", "Beta", 73.2, "yellow"),
        entry("three", "Gamma", 100, "green", false),
      ],
      milestones: [],
      total_count: 3,
    });

    expect(result.confidence).toBe(83);
    expect(result.projects[2]?.confidence).toBeNull();
    expect(result.onTrackProjects).toBe(1);
    expect(result.atRiskProjects).toBe(1);
    expect(result.waitingForDataProjects).toBe(1);
  });

  it("reports an empty portfolio without inventing a confidence score", () => {
    expect(summarizeClientPortfolio(undefined)).toEqual({
      confidence: null,
      projects: [],
      totalProjects: 0,
      onTrackProjects: 0,
      atRiskProjects: 0,
      waitingForDataProjects: 0,
      hasMoreProjects: false,
    });
  });

  it("flags a server-truncated project list", () => {
    const result = summarizeClientPortfolio({
      projects: [entry("one", "Alpha", 90, "green")],
      milestones: [],
      total_count: 2,
    });

    expect(result.hasMoreProjects).toBe(true);
    expect(result.totalProjects).toBe(2);
  });
});
