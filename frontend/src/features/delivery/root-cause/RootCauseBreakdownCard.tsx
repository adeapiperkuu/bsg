import type { MainContributorRead, RootCauseFactorRead } from "@/lib/api";
import { formatImpactPercent } from "./format";

type Props = {
  confidence: number | null;
  confidenceLoss: number | null;
  contributors: MainContributorRead[];
  factors?: RootCauseFactorRead[];
  loading?: boolean;
  emptyMessage?: string;
};

export function RootCauseBreakdownCard({
  confidence,
  confidenceLoss,
  contributors,
  factors = [],
  loading = false,
  emptyMessage = "No confidence-loss contributors identified.",
}: Props) {
  if (loading) {
    return (
      <div className="space-y-3">
        <div className="h-8 w-24 animate-pulse rounded bg-elevated" />
        <div className="h-2 overflow-hidden rounded bg-elevated">
          <div className="h-full w-1/3 animate-pulse rounded bg-[color:var(--brand)]" />
        </div>
      </div>
    );
  }

  const confidenceLabel =
    confidence == null || !Number.isFinite(confidence) ? "—" : `${Math.round(confidence)}%`;

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <p className="text-xs uppercase tracking-wide text-muted-foreground">Confidence</p>
          <p className="text-3xl font-semibold tabular-nums text-foreground">{confidenceLabel}</p>
        </div>
        {confidenceLoss != null && confidenceLoss > 0 ? (
          <p className="text-xs text-muted-foreground">
            Shortfall vs on-track: {formatImpactPercent(confidenceLoss)} pts
          </p>
        ) : null}
      </div>

      <div>
        <p className="mb-2 text-xs uppercase tracking-wide text-muted-foreground">
          Main Contributors
        </p>
        {contributors.length === 0 ? (
          <p className="text-sm text-muted-foreground">{emptyMessage}</p>
        ) : (
          <div className="space-y-2.5">
            {contributors.map((item) => (
              <div key={item.factor}>
                <div className="mb-1 flex items-center justify-between text-xs">
                  <span>{item.label}</span>
                  <span className="text-muted-foreground">
                    {formatImpactPercent(item.impact_percent)}%
                  </span>
                </div>
                <div className="h-2 overflow-hidden rounded bg-elevated">
                  <div
                    className="h-full rounded bg-[color:var(--brand)]"
                    style={{ width: `${formatImpactPercent(item.impact_percent)}%` }}
                  />
                </div>
              </div>
            ))}
          </div>
        )}
      </div>

      {factors.length > 0 ? (
        <details className="rounded border border-border bg-elevated/40 px-3 py-2">
          <summary className="cursor-pointer text-xs text-muted-foreground">
            Why? Evidence & calculation
          </summary>
          <ul className="mt-2 space-y-2 text-xs text-muted-foreground">
            {factors
              .filter((factor) => factor.impact_percent > 0)
              .map((factor) => (
                <li key={factor.factor} className="border-t border-border/60 pt-2 first:border-0 first:pt-0">
                  <p className="font-medium text-foreground">
                    {factor.label} · {formatImpactPercent(factor.impact_percent)}% ·{" "}
                    {factor.impact_points} pts
                  </p>
                  <p>{factor.explanation}</p>
                  {factor.evidence_json?.why ? (
                    <p className="mt-1">Why: {String(factor.evidence_json.why)}</p>
                  ) : null}
                  {factor.evidence_json?.calculation ? (
                    <p>Calculation: {String(factor.evidence_json.calculation)}</p>
                  ) : null}
                  {Array.isArray(factor.evidence_json?.affected_kpis) ? (
                    <p>
                      Affected KPIs:{" "}
                      {(factor.evidence_json.affected_kpis as unknown[]).map(String).join(", ")}
                    </p>
                  ) : null}
                </li>
              ))}
          </ul>
        </details>
      ) : null}
    </div>
  );
}
