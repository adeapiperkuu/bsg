import { useMemo } from "react";

import { AiBadge, Card, SectionHeader, StatusPill } from "@/components/bsg/widgets";
import {
  useAcceptRecommendationMutation,
  useProjectRecommendationsQuery,
  useRejectRecommendationMutation,
} from "@/features/mitigation-recommendations/hooks/useProjectRecommendations";
import type {
  GroupedMitigationRecommendation,
  GroupedRecommendationRisk,
  ProjectRecommendationsResponse,
  RecommendationSeverity,
  RecommendationStatus,
} from "@/features/mitigation-recommendations/types";
import { SEVERITY_LABELS, SEVERITY_ORDER } from "@/features/mitigation-recommendations/types";
import { cn } from "@/lib/utils";

const WORKFORCE_SOURCE_RISK_TYPE = "workforce_imbalance";

function confidencePercent(score: number | string): number {
  const value = typeof score === "string" ? Number.parseFloat(score) : score;
  return Number.isFinite(value) ? Math.round(value * 100) : 0;
}

function workforceRisks(
  recommendation: GroupedMitigationRecommendation,
): GroupedRecommendationRisk[] {
  return recommendation.risks.filter(
    (risk) => risk.source_risk_type === WORKFORCE_SOURCE_RISK_TYPE,
  );
}

function sortRecommendations(
  recommendations: GroupedMitigationRecommendation[],
): GroupedMitigationRecommendation[] {
  return [...recommendations].sort((left, right) => {
    const severityDelta =
      SEVERITY_ORDER[left.severity as RecommendationSeverity] -
      SEVERITY_ORDER[right.severity as RecommendationSeverity];
    if (severityDelta !== 0) return severityDelta;
    return confidencePercent(right.confidence_score) - confidencePercent(left.confidence_score);
  });
}

function recommendationStatus(risks: GroupedRecommendationRisk[]): RecommendationStatus {
  if (risks.some((risk) => risk.status === "pending")) return "pending";
  if (risks.some((risk) => risk.status === "accepted")) return "accepted";
  return "rejected";
}

function actionableRisk(risks: GroupedRecommendationRisk[]): GroupedRecommendationRisk | null {
  return risks.find((risk) => risk.status === "pending") ?? risks[0] ?? null;
}

export function WorkforceRecommendationsPanel({
  projectId,
  canManage,
  bundledRecommendations,
  bundledLoading = false,
  bundledError = false,
}: {
  projectId: string | null;
  canManage: boolean;
  /** When provided (including null while loading), skip the separate recommendations fetch. */
  bundledRecommendations?: ProjectRecommendationsResponse | null;
  bundledLoading?: boolean;
  bundledError?: boolean;
}) {
  const useBundled = bundledRecommendations !== undefined;
  const query = useProjectRecommendationsQuery(projectId, !useBundled);
  const acceptMutation = useAcceptRecommendationMutation(projectId);
  const rejectMutation = useRejectRecommendationMutation(projectId);

  const data = useBundled ? bundledRecommendations : query.data;
  const isLoading = useBundled ? bundledLoading : query.isLoading;
  const isError = useBundled ? bundledError : query.isError;

  const recommendations = useMemo(
    () =>
      sortRecommendations(
        (data?.data ?? [])
          .map((item) => ({ ...item, risks: workforceRisks(item) }))
          .filter((item) => item.risks.length > 0),
      ),
    [data?.data],
  );

  return (
    <Card>
      <SectionHeader
        title="Workforce Recommendations"
        sub="Generated mitigations for detected capability gaps"
      />
      {isLoading ? (
        <div className="space-y-2">
          <div className="h-20 animate-pulse rounded-md bg-elevated" />
          <div className="h-20 animate-pulse rounded-md bg-elevated" />
        </div>
      ) : isError ? (
        <p className="text-sm text-[color:var(--danger)]">
          Unable to load workforce recommendations.
        </p>
      ) : recommendations.length === 0 ? (
        <div className="rounded-md border border-dashed border-border bg-elevated/50 px-4 py-8 text-center">
          <p className="text-sm font-medium text-muted-foreground">
            No workforce recommendations yet
          </p>
          <p className="mt-1 text-xs text-muted-foreground">
            {canManage
              ? "Detect capability gaps, then use Generate recommendations to create mitigations."
              : "No workforce recommendations have been generated for this project."}
          </p>
        </div>
      ) : (
        <div className="space-y-2">
          {recommendations.map((recommendation) => {
            const risk = actionableRisk(recommendation.risks);
            return (
              <WorkforceRecommendationCard
                key={recommendation.title}
                recommendation={recommendation}
                canManage={canManage}
                onAccept={() => risk && acceptMutation.mutate(risk.recommendation_id)}
                onReject={() => risk && rejectMutation.mutate(risk.recommendation_id)}
                isAccepting={
                  Boolean(risk) &&
                  acceptMutation.isPending &&
                  acceptMutation.variables === risk?.recommendation_id
                }
                isRejecting={
                  Boolean(risk) &&
                  rejectMutation.isPending &&
                  rejectMutation.variables === risk?.recommendation_id
                }
              />
            );
          })}
        </div>
      )}
    </Card>
  );
}

function WorkforceRecommendationCard({
  recommendation,
  canManage,
  onAccept,
  onReject,
  isAccepting,
  isRejecting,
}: {
  recommendation: GroupedMitigationRecommendation;
  canManage: boolean;
  onAccept: () => void;
  onReject: () => void;
  isAccepting: boolean;
  isRejecting: boolean;
}) {
  const status = recommendationStatus(recommendation.risks);
  const risk = actionableRisk(recommendation.risks);
  const isPending = status === "pending";
  const isAccepted = status === "accepted";
  const isRejected = status === "rejected";
  const busy = isAccepting || isRejecting;
  const description = recommendation.descriptions[0] ?? risk?.description;
  const linkedGapLabel =
    recommendation.risks.length === 1
      ? risk?.source_risk_title
      : `${recommendation.risks.length} linked workforce gaps`;

  return (
    <div
      className={cn(
        "rounded-md border p-3 transition-colors",
        isAccepted && "border-[color:var(--success)]/40 bg-[color:var(--success)]/5",
        isRejected && "border-border bg-elevated/50 opacity-60",
        isPending && "border-border bg-elevated",
      )}
    >
      <div className="flex flex-wrap items-center gap-2">
        <StatusPill status={SEVERITY_LABELS[recommendation.severity as RecommendationSeverity]} />
        <AiBadge confidence={confidencePercent(recommendation.confidence_score)} />
        {isAccepted && (
          <span className="rounded-full border border-[color:var(--success)]/30 bg-[color:var(--success)]/10 px-2 py-0.5 text-[10px] font-medium text-[color:var(--success)]">
            Accepted
          </span>
        )}
        {isRejected && (
          <span className="rounded-full border border-border bg-secondary px-2 py-0.5 text-[10px] font-medium text-muted-foreground">
            Rejected
          </span>
        )}
        {isPending && (
          <span className="rounded-full border border-[color:var(--warning)]/30 bg-[color:var(--warning)]/10 px-2 py-0.5 text-[10px] font-medium text-[color:var(--warning)]">
            Pending
          </span>
        )}
      </div>

      <div className={cn("mt-1.5 text-sm font-medium", isRejected && "text-muted-foreground")}>
        {recommendation.title}
      </div>
      {description ? <p className="mt-1 text-xs text-muted-foreground">{description}</p> : null}
      {linkedGapLabel ? (
        <p className="mt-1.5 text-[10px] text-muted-foreground">Linked gap: {linkedGapLabel}</p>
      ) : null}

      {canManage && isPending ? (
        <div className="mt-2 flex gap-1.5">
          <button
            type="button"
            disabled={busy}
            onClick={onAccept}
            className="rounded bg-[color:var(--brand)] px-2.5 py-1 text-[11px] font-medium text-[color:var(--brand-foreground)] disabled:opacity-50"
          >
            {isAccepting ? "Accepting..." : "Accept"}
          </button>
          <button
            type="button"
            disabled={busy}
            onClick={onReject}
            className="rounded border border-border px-2.5 py-1 text-[11px] disabled:opacity-50"
          >
            {isRejecting ? "Rejecting..." : "Reject"}
          </button>
        </div>
      ) : null}
    </div>
  );
}
