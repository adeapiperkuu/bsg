/** Display helpers for semantic KPI favorability. */

export function absoluteFavorabilityLabel(
  value:
    | "improving"
    | "declining"
    | "stable"
    | "on_target"
    | "off_target"
    | "unknown"
    | string,
): string {
  switch (value) {
    case "improving":
      return "Improving";
    case "declining":
      return "Declining";
    case "stable":
      return "Stable";
    case "on_target":
      return "On target";
    case "off_target":
      return "Off target";
    default:
      return "Unknown";
  }
}
