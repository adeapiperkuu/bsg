import { describe, expect, it } from "vitest";

function metricValue(metrics: Record<string, unknown> | undefined, key: string): string {
  const raw = metrics?.[key];
  if (raw == null) return "—";
  if (typeof raw === "number") return String(raw);
  if (typeof raw === "object" && raw !== null && "value" in raw) {
    const value = (raw as { value: number | null }).value;
    return value == null ? "—" : `${value}%`;
  }
  return String(raw);
}

describe("recommendation optimization frontend helpers", () => {
  it("formats nested rate metrics", () => {
    expect(
      metricValue(
        {
          acceptance_rate: { value: 55.5, numerator: 11, denominator: 20 },
        },
        "acceptance_rate",
      ),
    ).toBe("55.5%");
  });

  it("formats null rates as em dash", () => {
    expect(
      metricValue(
        {
          acceptance_rate: { value: null, null_reason: "no_reviewed" },
        },
        "acceptance_rate",
      ),
    ).toBe("—");
  });

  it("formats volume counts", () => {
    expect(metricValue({ volume: 42 }, "volume")).toBe("42");
  });
});
