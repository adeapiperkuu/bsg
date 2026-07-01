import { Card, SectionHeader } from "@/components/bsg/widgets";
import { WorkforcePlaceholder } from "@/components/bsg/workforce/WorkforcePlaceholder";
import { trainingGapTypeLabel, WORKFORCE_EMPTY_VALUE } from "@/lib/workforceLabels";
import type { TrainingGapRow, TrainingGapSummaryRead } from "@/types/workforce";

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
        <WorkforcePlaceholder
          title="No open training gaps"
          reason="Mandatory training, certifications, and training records are current for project teams."
        />
      ) : filteredTrainingGapRows.length === 0 ? (
        <WorkforcePlaceholder
          title="No training gaps match the current filters"
          reason="Change the site, domain, or skill category filter to review more gaps."
        />
      ) : (
        <>
          <div className="mb-4 flex flex-wrap gap-2">
            {trainingGaps!.mandatory_training_incomplete > 0 && (
              <span className="rounded border border-border bg-elevated px-2 py-1 text-[11px] text-muted-foreground">
                {trainingGaps!.mandatory_training_incomplete} mandatory incomplete
              </span>
            )}
            {trainingGaps!.expired_or_failed_training > 0 && (
              <span className="rounded border border-border bg-elevated px-2 py-1 text-[11px] text-muted-foreground">
                {trainingGaps!.expired_or_failed_training} expired/failed training
              </span>
            )}
            {trainingGaps!.expired_certifications > 0 && (
              <span className="rounded border border-border bg-elevated px-2 py-1 text-[11px] text-muted-foreground">
                {trainingGaps!.expired_certifications} expired certifications
              </span>
            )}
            {trainingGaps!.pending_certification_reviews > 0 && (
              <span className="rounded border border-border bg-elevated px-2 py-1 text-[11px] text-muted-foreground">
                {trainingGaps!.pending_certification_reviews} pending reviews
              </span>
            )}
          </div>
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
                {filteredTrainingGapRows.map((row, index) => (
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
        </>
      )}
    </Card>
  );
}
