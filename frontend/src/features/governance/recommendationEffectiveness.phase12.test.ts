import { describe, expect, it } from "vitest";

import type { GovernanceEffectivenessMetric } from "@/types/governance";

function formatRate(metric?: GovernanceEffectivenessMetric | null): string {
  if (!metric || metric.value == null) return "—";
  return `${metric.value}%`;
}

describe("recommendation effectiveness frontend helpers", () => {
  it("renders null rates as em dash", () => {
    expect(
      formatRate({
        value: null,
        numerator: 0,
        denominator: 0,
        null_reason: "no_reviewed_recommendations",
      }),
    ).toBe("—");
  });

  it("renders numeric rates with percent", () => {
    expect(
      formatRate({
        value: 42.5,
        numerator: 17,
        denominator: 40,
        null_reason: null,
      }),
    ).toBe("42.5%");
  });
});
