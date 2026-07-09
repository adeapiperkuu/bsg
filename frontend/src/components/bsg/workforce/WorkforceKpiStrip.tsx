import { KpiCard } from "@/components/bsg/widgets";
import { WORKFORCE_EMPTY_VALUE } from "@/lib/workforceLabels";

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
      <KpiCard
        label="Active Annotators"
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
      <KpiCard
        label="SME Coverage"
        value={workforceLoading ? WORKFORCE_EMPTY_VALUE : smeCoverageValue}
        delta={workforceLoading ? undefined : smeCoverageDelta}
        tone={smeCoveragePct !== null && smeCoveragePct < 50 ? "warning" : "default"}
      />
      <KpiCard
        label="Teams At Capacity"
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
      <KpiCard
        label="Training Gaps"
        value={trainingGapsValue}
        delta={trainingGapsDelta}
        tone={trainingGapsTone}
      />
    </div>
  );
}
