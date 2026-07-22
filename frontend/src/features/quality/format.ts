/** Quality formatting helpers + chart tokens (re-exported from shared theme). */

export {
  CHART_AXIS_STYLE,
  CHART_TOOLTIP_STYLE,
} from "@/lib/charts/theme";

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
