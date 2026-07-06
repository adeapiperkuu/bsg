export const CHART_AXIS_STYLE = {
  tick: { fill: "#8b92a5", fontSize: 11 },
  axisLine: { stroke: "#2a2d3a" },
  tickLine: { stroke: "#2a2d3a" },
};

export const CHART_TOOLTIP_STYLE = {
  backgroundColor: "#20242f",
  border: "1px solid #2a2d3a",
  borderRadius: 8,
  fontSize: 12,
  color: "#f0f2f7",
};

export function fmtPct(v: number | null | undefined): string {
  if (v == null) return "—";
  return `${Number(v).toFixed(1)}%`;
}

export function fmtIaa(v: number | null | undefined): string {
  if (v == null) return "—";
  return Number(v).toFixed(2);
}

export type KpiKind = "accuracy" | "iaa" | "rework" | "alerts";

export function kpiTone(
  value: number | null | undefined,
  kind: KpiKind,
): "success" | "warning" | "danger" {
  if (value == null) return "warning";
  if (kind === "accuracy") return value >= 96 ? "success" : value >= 94 ? "warning" : "danger";
  if (kind === "iaa") return value >= 0.9 ? "success" : value >= 0.85 ? "warning" : "danger";
  if (kind === "rework") return value <= 3 ? "success" : value <= 5 ? "warning" : "danger";
  return value === 0 ? "success" : value <= 2 ? "warning" : "danger";
}
