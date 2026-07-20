import { describe, expect, it } from "vitest";
import { contributorsWithOther, formatImpactPercent } from "./format";

describe("root-cause format helpers", () => {
  it("rounds impact percents", () => {
    expect(formatImpactPercent(38.4)).toBe(38);
    expect(formatImpactPercent(0)).toBe(0);
    expect(formatImpactPercent(Number.NaN)).toBe(0);
  });

  it("collapses remainder into Other", () => {
    const rows = contributorsWithOther(
      [
        { factor: "review_turnaround", label: "Review turnaround", impact_percent: 38 },
        { factor: "rework", label: "Rework", impact_percent: 26 },
        { factor: "capacity", label: "Capacity", impact_percent: 18 },
        { factor: "blocked_work", label: "Blocked work", impact_percent: 11 },
        { factor: "queue", label: "Queue", impact_percent: 7 },
      ],
      4,
    );
    expect(rows).toHaveLength(4);
    expect(rows[3]?.factor).toBe("other");
    expect(rows[3]?.impact_percent).toBe(18);
  });

  it("returns empty list when no impacts", () => {
    expect(contributorsWithOther([])).toEqual([]);
  });
});
