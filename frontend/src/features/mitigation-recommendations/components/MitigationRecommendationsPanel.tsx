import { Card, EvidenceBadge, SectionHeader } from "@/components/bsg/widgets";
import { RecommendationCard } from "@/features/mitigation-recommendations/components/RecommendationCard";
import {
  useAcceptRecommendationMutation,
  useAssignRecommendationOwnerMutation,
  useProjectRecommendationsQuery,
  useRejectRecommendationMutation,
} from "@/features/mitigation-recommendations/hooks/useProjectRecommendations";
import type {
  GroupedMitigationRecommendation,
  RecommendationSeverity,
} from "@/features/mitigation-recommendations/types";
import { SEVERITY_LABELS } from "@/features/mitigation-recommendations/types";
import { useMemo } from "react";

type MitigationRecommendationsPanelProps = {
  projectId: string | null;
};

function groupBySeverity(
  recommendations: GroupedMitigationRecommendation[],
): Array<{ severity: RecommendationSeverity; items: GroupedMitigationRecommendation[] }> {
  const groups = new Map<RecommendationSeverity, GroupedMitigationRecommendation[]>();
  for (const item of recommendations) {
    const bucket = groups.get(item.severity) ?? [];
    bucket.push(item);
    groups.set(item.severity, bucket);
  }
  return (["high", "medium", "low"] as const)
    .filter((severity) => groups.has(severity))
    .map((severity) => ({
      severity,
      items: [...(groups.get(severity) ?? [])].sort(
        (a, b) => b.confidence_score - a.confidence_score,
      ),
    }));
}

// "Accepted" still means an owner is meant to be actively working the linked risk, so a
// group only moves to "Historical" once EVERY linked risk has been rejected — i.e. nothing
// in it is pending or accepted. A group with any pending or accepted risk stays "Active",
// even if some of its other linked risks were rejected (a mixed outcome is surfaced on the
// card itself rather than hidden by filing the whole group as historical).
function splitGroupsByDecision(recommendations: GroupedMitigationRecommendation[]): {
  active: GroupedMitigationRecommendation[];
  historical: GroupedMitigationRecommendation[];
} {
  const active: GroupedMitigationRecommendation[] = [];
  const historical: GroupedMitigationRecommendation[] = [];
  for (const group of recommendations) {
    const allRejected = group.risks.every((risk) => risk.status === "rejected");
    (allRejected ? historical : active).push(group);
  }
  return { active, historical };
}

export function MitigationRecommendationsPanel({ projectId }: MitigationRecommendationsPanelProps) {
  const { data, isLoading, isError } = useProjectRecommendationsQuery(projectId);
  const acceptMutation = useAcceptRecommendationMutation(projectId);
  const rejectMutation = useRejectRecommendationMutation(projectId);
  const assignMutation = useAssignRecommendationOwnerMutation(projectId);

  const { active, historical } = useMemo(
    () => splitGroupsByDecision(data?.data ?? []),
    [data?.data],
  );
  const activeGrouped = useMemo(() => groupBySeverity(active), [active]);
  const historicalGrouped = useMemo(() => groupBySeverity(historical), [historical]);

  const assignableOwners = data?.assignable_owners ?? [];
  const hasAny = activeGrouped.length > 0 || historicalGrouped.length > 0;

  const renderGroups = (
    groups: Array<{ severity: RecommendationSeverity; items: GroupedMitigationRecommendation[] }>,
  ) => (
    <div className="space-y-4">
      {groups.map((group) => (
        <div key={group.severity}>
          <div className="mb-2 text-[11px] font-semibold uppercase tracking-wider text-muted-foreground">
            {SEVERITY_LABELS[group.severity]} severity
          </div>
          <div className="space-y-2">
            {group.items.map((recommendation) => (
              <RecommendationCard
                key={recommendation.title}
                recommendation={recommendation}
                assignableOwners={assignableOwners}
                onAccept={(id) => acceptMutation.mutate(id)}
                onReject={(id) => rejectMutation.mutate(id)}
                onAssignOwner={(id, ownerType, ownerId) =>
                  assignMutation.mutate({
                    recommendationId: id,
                    payload: {
                      owner_type: ownerType as "user" | "team" | null,
                      owner_id: ownerId,
                    },
                  })
                }
                isAccepting={(id) => acceptMutation.isPending && acceptMutation.variables === id}
                isRejecting={(id) => rejectMutation.isPending && rejectMutation.variables === id}
                isAssigning={(id) =>
                  assignMutation.isPending && assignMutation.variables?.recommendationId === id
                }
              />
            ))}
          </div>
        </div>
      ))}
    </div>
  );

  return (
    <Card>
      <SectionHeader title="Mitigation Recommendations" right={<EvidenceBadge />} />
      {isLoading ? (
        <div className="space-y-2">
          <div className="h-20 animate-pulse rounded-md bg-elevated" />
          <div className="h-20 animate-pulse rounded-md bg-elevated" />
        </div>
      ) : isError ? (
        <p className="text-sm text-[color:var(--danger)]">
          Unable to load mitigation recommendations.
        </p>
      ) : hasAny ? (
        <div className="space-y-6">
          <div>
            <div className="mb-3 text-xs font-semibold uppercase tracking-wider text-foreground">
              Active recommendations
            </div>
            <p className="mb-2 text-[11px] text-muted-foreground">
              Awaiting a decision, or accepted with an owner still expected to act.
            </p>
            {activeGrouped.length > 0 ? (
              renderGroups(activeGrouped)
            ) : (
              <p className="text-sm text-muted-foreground">No active recommendations.</p>
            )}
          </div>
          {historicalGrouped.length > 0 && (
            <div>
              <div className="mb-3 text-xs font-semibold uppercase tracking-wider text-muted-foreground">
                Historical decisions
              </div>
              <p className="mb-2 text-[11px] text-muted-foreground">
                Every linked risk was rejected — kept here for the record only.
              </p>
              {renderGroups(historicalGrouped)}
            </div>
          )}
        </div>
      ) : (
        <p className="text-sm text-muted-foreground">No mitigation recommendations available.</p>
      )}
    </Card>
  );
}
