import { describe, expect, it } from "vitest";

import { queryKeys } from "@/lib/queries/keys";
import { absoluteFavorabilityLabel } from "@/components/bsg/time-series/favorability";

describe("time-series query keys", () => {
  it("builds stable kpi trend keys", () => {
    const key = queryKeys.kpiTrend("quality.gold_set_accuracy", {
      project_id: "p1",
      interval: "week",
    });
    expect(key[0]).toBe("time-series");
    expect(key[2]).toBe("quality.gold_set_accuracy");
    expect(key[3]).toBe("trend");
  });

  it("namespaces recommendation timeline by subject", () => {
    const key = queryKeys.recommendationTimeline("subj-1", { limit: 20 });
    expect(key).toEqual([
      "time-series",
      "recommendations",
      "subj-1",
      "timeline",
      { limit: 20 },
    ]);
  });
});

describe("semantic favorability labels", () => {
  it("maps improving/declining for display", () => {
    expect(absoluteFavorabilityLabel("improving")).toBe("Improving");
    expect(absoluteFavorabilityLabel("off_target")).toBe("Off target");
    expect(absoluteFavorabilityLabel("unknown")).toBe("Unknown");
  });
});
