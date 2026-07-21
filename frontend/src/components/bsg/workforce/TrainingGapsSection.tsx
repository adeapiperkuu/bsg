import { useMemo, useState } from "react";
import { Card, SectionHeader } from "@/components/bsg/widgets";
import { WorkforcePlaceholder } from "@/components/bsg/workforce/WorkforcePlaceholder";
import { cn } from "@/lib/utils";
import { trainingGapTypeLabel, WORKFORCE_EMPTY_VALUE } from "@/lib/workforceLabels";
import type { TrainingGapRow, TrainingGapSummaryRead, TrainingGapType } from "@/types/workforce";

type TrainingGapFilter = {
  type: TrainingGapType;
  count: number;
  label: string;
};

function TrainingGapFilterButton({
  filter,
  active,
  onClick,
}: {
  filter: TrainingGapFilter;
  active: boolean;
  onClick: () => void;
}) {
  return (
    <button
      type="button"
      aria-pressed={active}
      onClick={onClick}
      className={cn(
        "rounded border px-2 py-1 text-[11px] transition-colors",
        active
          ? "border-[color:var(--brand)] bg-[color:var(--brand)] text-[color:var(--brand-foreground)]"
          : "border-border bg-elevated text-muted-foreground hover:border-[color:var(--brand)]/35 hover:text-foreground",
      )}
    >
      {filter.count} {filter.label}
    </button>
  );
}

export function TrainingGapsSection({
  canReadInternalWorkforce,
  trainingGapsLoading,
  trainingGapsError,
  trainingGaps,
  filteredTrainingGapRows,
  trainingGapRowKey,
  gapRowSubject,
}: {
  canReadInternalWorkforce: boolean;
  trainingGapsLoading: boolean;
  trainingGapsError: string | null;
  trainingGaps: TrainingGapSummaryRead | undefined;
  filteredTrainingGapRows: TrainingGapRow[];
  trainingGapRowKey: (row: TrainingGapRow, index: number) => string;
  gapRowSubject: (row: TrainingGapRow) => string;
}) {
  const [activeGapType, setActiveGapType] = useState<TrainingGapType | null>(null);
  const gapFilters = useMemo<TrainingGapFilter[]>(() => {
    if (!trainingGaps) return [];
    const filters: TrainingGapFilter[] = [
      {
        type: "mandatory_training_incomplete",
        count: trainingGaps.mandatory_training_incomplete,
        label: "mandatory incomplete",
      },
      {
        type: "expired_or_failed_training",
        count: trainingGaps.expired_or_failed_training,
        label: "expired/failed training",
      },
      {
        type: "expired_certification",
        count: trainingGaps.expired_certifications,
        label: "expired certifications",
      },
      {
        type: "pending_certification_review",
        count: trainingGaps.pending_certification_reviews,
        label: "pending reviews",
      },
    ];
    return filters.filter((filter) => filter.count > 0);
  }, [trainingGaps]);
  const visibleTrainingGapRows = activeGapType
    ? filteredTrainingGapRows.filter((row) => row.gap_type === activeGapType)
    : filteredTrainingGapRows;
  const activeFilterLabel = gapFilters.find((filter) => filter.type === activeGapType)?.label;

  return (
    <Card>
      <SectionHeader title="Training Gaps" sub="Certification and training coverage gaps" />
      {!canReadInternalWorkforce ? (
        <WorkforcePlaceholder
          title="Training gaps restricted"
          reason="Internal workforce training and certification gaps are not available to client users."
        />
      ) : trainingGapsLoading ? (
        <div className="space-y-2">
          <div className="h-8 animate-pulse rounded-md bg-elevated" />
          <div className="h-10 animate-pulse rounded-md bg-elevated" />
          <div className="h-10 animate-pulse rounded-md bg-elevated" />
        </div>
      ) : trainingGapsError ? (
        <p className="text-sm text-[color:var(--danger)]">{trainingGapsError}</p>
      ) : (trainingGaps?.total_training_gaps ?? 0) === 0 ? (
        <div className="flex items-start gap-3 rounded-md border border-[color:var(--success)]/25 bg-[color:var(--success)]/5 px-3 py-2.5">
          <span className="mt-1 h-2 w-2 shrink-0 rounded-full bg-[color:var(--success)]" />
          <div>
            <p className="text-sm font-medium text-foreground">Training coverage is current</p>
            <p className="mt-0.5 text-xs text-muted-foreground">
              No mandatory, expired, or pending certification gaps for this project.
            </p>
          </div>
        </div>
      ) : filteredTrainingGapRows.length === 0 ? (
        <WorkforcePlaceholder
          title="No training gaps match the current filters"
          reason="Change the site, domain, or skill category filter to review more gaps."
        />
      ) : (
        <>
          <div className="mb-4 flex flex-wrap gap-2">
            {gapFilters.map((filter) => (
              <TrainingGapFilterButton
                key={filter.type}
                filter={filter}
                active={activeGapType === filter.type}
                onClick={() =>
                  setActiveGapType((current) => (current === filter.type ? null : filter.type))
                }
              />
            ))}
          </div>
          {visibleTrainingGapRows.length === 0 ? (
            <WorkforcePlaceholder
              title={`No ${activeFilterLabel ?? "training gap"} rows match the current filters`}
              reason="Change the site, domain, or skill category filter to review more gaps."
            />
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full text-xs">
                <thead className="text-left text-muted-foreground">
                  <tr className="border-b border-border">
                    <th className="py-2 pr-3 font-medium">Team</th>
                    <th className="py-2 pr-3 font-medium">Gap</th>
                    <th className="py-2 pr-3 font-medium">Subject</th>
                    <th className="py-2 pr-3 font-medium">Affected</th>
                  </tr>
                </thead>
                <tbody>
                  {visibleTrainingGapRows.map((row, index) => (
                    <tr key={trainingGapRowKey(row, index)} className="border-b border-border/50">
                      <td className="py-2.5 pr-3 font-medium">
                        {row.team_name ?? WORKFORCE_EMPTY_VALUE}
                      </td>
                      <td className="py-2.5 pr-3">
                        <span className="inline-block rounded bg-[color:var(--danger)]/10 px-2 py-1 text-[11px] font-medium text-[color:var(--danger)]">
                          {trainingGapTypeLabel(row.gap_type)}
                        </span>
                      </td>
                      <td className="py-2.5 pr-3 text-muted-foreground">{gapRowSubject(row)}</td>
                      <td className="py-2.5 pr-3">{row.affected_count}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </>
      )}
    </Card>
  );
}
