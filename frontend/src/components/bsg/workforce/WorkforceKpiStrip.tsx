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
    <Card className="relative isolate flex overflow-hidden border-border/70 bg-card p-4 shadow-sm transition-colors hover:border-foreground/20">
      <div className={cn("absolute inset-x-0 top-0 h-1", styles.accent)} />
      <div className="flex w-full flex-col">
        <div className="flex items-center justify-between gap-2">
          <div className="text-[11px] font-semibold uppercase leading-4 tracking-wider text-muted-foreground">
            {label}
          </div>
          <div
            aria-hidden="true"
            className={cn(
              "flex h-6 w-6 shrink-0 items-center justify-center rounded-md text-[10px] font-semibold",
              styles.surface,
            )}
          >
            {marker}
          </div>
        </div>

        <div className="mt-2 text-[28px] font-semibold leading-none tracking-normal text-foreground">
          {value}
        </div>

        {delta ? (
          <div className="mt-2.5">
            <span
              className={cn(
                "inline-flex max-w-full items-center rounded-md px-2 py-0.5 text-[11px] font-medium leading-4",
                styles.surface,
              )}
            >
              <span className={cn("mr-1.5 h-1.5 w-1.5 shrink-0 rounded-full", styles.accent)} />
              <span className="truncate">{delta}</span>
            </span>
          </div>
        ) : null}
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
        tone="default"
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
