import type { MainContributorRead } from "@/lib/api";
import { formatImpactPercent } from "./format";

type Props = {
  contributors: MainContributorRead[];
  loading?: boolean;
};

/** Thin distribution shell for Phase 15.6 chart polish. */
export function ImpactDistributionChart({ contributors, loading = false }: Props) {
  if (loading) {
    return <div className="h-16 animate-pulse rounded bg-elevated" />;
  }
  if (contributors.length === 0) {
    return null;
  }
  const total = contributors.reduce((sum, item) => sum + Math.max(0, item.impact_percent), 0) || 1;
  return (
    <div className="space-y-2">
      <div className="flex h-3 overflow-hidden rounded bg-elevated">
        {contributors.map((item, index) => {
          const width = (Math.max(0, item.impact_percent) / total) * 100;
          const opacity = 1 - index * 0.12;
          return (
            <div
              key={item.factor}
              className="h-full bg-[color:var(--brand)]"
              style={{ width: `${width}%`, opacity }}
              title={`${item.label}: ${formatImpactPercent(item.impact_percent)}%`}
            />
          );
        })}
      </div>
      <div className="flex flex-wrap gap-x-3 gap-y-1 text-[10px] text-muted-foreground">
        {contributors.map((item) => (
          <span key={item.factor}>
            {item.label} {formatImpactPercent(item.impact_percent)}%
          </span>
        ))}
      </div>
    </div>
  );
}
