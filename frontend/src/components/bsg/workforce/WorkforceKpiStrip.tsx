import { Card } from "@/components/bsg/widgets";
import { cn } from "@/lib/utils";
import { WORKFORCE_EMPTY_VALUE } from "@/lib/workforceLabels";

const toneStyles = {
  default: {
    accent: "bg-muted-foreground",
    surface: "bg-secondary text-muted-foreground",
    text: "text-muted-foreground",
  },
  success: {
    accent: "bg-[color:var(--success)]",
    surface: "bg-[color:var(--success)]/10 text-[color:var(--success)]",
    text: "text-[color:var(--success)]",
  },
  warning: {
    accent: "bg-[color:var(--warning)]",
    surface: "bg-[color:var(--warning)]/10 text-[color:var(--warning)]",
    text: "text-[color:var(--warning)]",
  },
  danger: {
    accent: "bg-[color:var(--danger)]",
    surface: "bg-[color:var(--danger)]/10 text-[color:var(--danger)]",
    text: "text-[color:var(--danger)]",
  },
};

function WorkforceKpiCard({
  label,
  value,
  delta,
  marker,
  tone = "default",
}: {
  label: string;
  value: string | number;
  delta?: string;
  marker: string;
  tone?: "default" | "success" | "warning" | "danger";
}) {
  const styles = toneStyles[tone];

  return (
    <Card className="relative isolate flex min-h-[136px] overflow-hidden border-border/70 bg-card p-5 shadow-sm transition-colors hover:border-foreground/20">
      <div className={cn("absolute inset-x-0 top-0 h-1", styles.accent)} />
      <div className="flex w-full flex-col justify-between">
        <div className="flex min-h-9 items-start justify-between gap-3">
          <div className="max-w-[10rem] text-[11px] font-semibold uppercase leading-4 tracking-wider text-muted-foreground">
            {label}
          </div>
          <div
            aria-hidden="true"
            className={cn(
              "flex h-8 w-8 shrink-0 items-center justify-center rounded-md text-xs font-semibold",
              styles.surface,
            )}
          >
            {marker}
          </div>
        </div>

        <div className="mt-3 text-[32px] font-semibold leading-none tracking-normal text-foreground">
          {value}
        </div>

        <div className="mt-4 min-h-6">
          {delta ? (
            <span
              className={cn(
                "inline-flex max-w-full items-center rounded-md px-2 py-1 text-[12px] font-medium leading-4",
                styles.surface,
              )}
            >
              <span className={cn("mr-1.5 h-1.5 w-1.5 rounded-full", styles.accent)} />
              <span className="truncate">{delta}</span>
            </span>
          ) : (
            <span className={cn("block h-6 text-[12px]", styles.text)} />
          )}
        </div>
      </div>
    </Card>
  );
}

export function WorkforceKpiStrip({
  workforceLoading,
  canReadInternalWorkforce,
  activeAnnotatorCount,
  smeCoverageValue,
  smeCoverageDelta,
  smeCoveragePct,
  teamsAtCapacityValue,
  teamsAtCapacityDelta,
  teamsAtCapacityOverloaded,
  teamsAtCapacityTotal,
  trainingGapsValue,
  trainingGapsDelta,
  trainingGapsTone,
}: {
  workforceLoading: boolean;
  canReadInternalWorkforce: boolean;
  activeAnnotatorCount: number;
  smeCoverageValue: string;
  smeCoverageDelta: string;
  smeCoveragePct: number | null;
  teamsAtCapacityValue: string | number;
  teamsAtCapacityDelta: string | undefined;
  teamsAtCapacityOverloaded: number;
  teamsAtCapacityTotal: number;
  trainingGapsValue: string | number;
  trainingGapsDelta: string | undefined;
  trainingGapsTone: "default" | "success" | "warning" | "danger";
}) {
  return (
    <div className="grid grid-cols-2 gap-4 lg:grid-cols-4">
      <WorkforceKpiCard
        label="Active Annotators"
        marker="AA"
        value={
          workforceLoading
            ? WORKFORCE_EMPTY_VALUE
            : canReadInternalWorkforce
              ? activeAnnotatorCount
              : WORKFORCE_EMPTY_VALUE
        }
        delta={canReadInternalWorkforce ? undefined : "Internal only"}
        tone={activeAnnotatorCount > 0 ? "success" : "default"}
      />
      <WorkforceKpiCard
        label="SME Coverage"
        marker="%"
        value={workforceLoading ? WORKFORCE_EMPTY_VALUE : smeCoverageValue}
        delta={workforceLoading ? undefined : smeCoverageDelta}
        tone={smeCoveragePct !== null && smeCoveragePct < 50 ? "warning" : "default"}
      />
      <WorkforceKpiCard
        label="Teams At Capacity"
        marker="TC"
        value={teamsAtCapacityValue}
        delta={teamsAtCapacityDelta}
        tone={
          teamsAtCapacityOverloaded > 0
            ? "warning"
            : teamsAtCapacityTotal > 0
              ? "success"
              : "default"
        }
      />
      <WorkforceKpiCard
        label="Training Gaps"
        marker="TG"
        value={trainingGapsValue}
        delta={trainingGapsDelta}
        tone={trainingGapsTone}
      />
    </div>
  );
}
