export function formatImpactPercent(value: number): number {
  if (!Number.isFinite(value) || value <= 0) return 0;
  return Math.round(value);
}

export function contributorsWithOther(
  contributors: Array<{ factor: string; label: string; impact_percent: number }>,
  limit = 4,
): Array<{ factor: string; label: string; impact_percent: number }> {
  const ranked = [...contributors]
    .filter((item) => item.impact_percent > 0)
    .sort((a, b) => b.impact_percent - a.impact_percent);
  if (ranked.length <= limit) return ranked.map((item) => ({
    ...item,
    impact_percent: formatImpactPercent(item.impact_percent),
  }));
  const top = ranked.slice(0, limit - 1);
  const other = ranked.slice(limit - 1);
  return [
    ...top.map((item) => ({
      ...item,
      impact_percent: formatImpactPercent(item.impact_percent),
    })),
    {
      factor: "other",
      label: "Other",
      impact_percent: formatImpactPercent(
        other.reduce((sum, item) => sum + item.impact_percent, 0),
      ),
    },
  ];
}
