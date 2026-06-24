import { Card, EvidenceBadge, SectionHeader } from "@/components/bsg/widgets";
import { RecommendationCard } from "@/features/mitigation-recommendations/components/RecommendationCard";
import {
  useAcceptRecommendationMutation,
  useAssignRecommendationOwnerMutation,
  useProjectRecommendationsQuery,
  useRejectRecommendationMutation,
} from "@/features/mitigation-recommendations/hooks/useProjectRecommendations";
import type {
  MitigationRecommendation,
  RecommendationSeverity,
} from "@/features/mitigation-recommendations/types";
import { SEVERITY_LABELS } from "@/features/mitigation-recommendations/types";
import { useMemo } from "react";

type MitigationRecommendationsPanelProps = {
  projectId: string | null;
};

function groupBySeverity(
  recommendations: MitigationRecommendation[],
): Array<{ severity: RecommendationSeverity; items: MitigationRecommendation[] }> {
  const groups = new Map<RecommendationSeverity, MitigationRecommendation[]>();
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

export function MitigationRecommendationsPanel({ projectId }: MitigationRecommendationsPanelProps) {
  const { data, isLoading, isError } = useProjectRecommendationsQuery(projectId);
  const acceptMutation = useAcceptRecommendationMutation(projectId);
  const rejectMutation = useRejectRecommendationMutation(projectId);
  const assignMutation = useAssignRecommendationOwnerMutation(projectId);

  const grouped = useMemo(
    () => groupBySeverity(data?.data ?? []),
    [data?.data],
  );

  const assignableOwners = data?.assignable_owners ?? [];

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
      ) : grouped.length > 0 ? (
        <div className="space-y-4">
          {grouped.map((group) => (
            <div key={group.severity}>
              <div className="mb-2 text-[11px] font-semibold uppercase tracking-wider text-muted-foreground">
                {SEVERITY_LABELS[group.severity]} severity
              </div>
              <div className="space-y-2">
                {group.items.map((recommendation) => (
                  <RecommendationCard
                    key={recommendation.id}
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
                    isAccepting={
                      acceptMutation.isPending &&
                      acceptMutation.variables === recommendation.id
                    }
                    isRejecting={
                      rejectMutation.isPending &&
                      rejectMutation.variables === recommendation.id
                    }
                    isAssigning={
                      assignMutation.isPending &&
                      assignMutation.variables?.recommendationId === recommendation.id
                    }
                  />
                ))}
              </div>
            </div>
          ))}
        </div>
      ) : (
        <p className="text-sm text-muted-foreground">No mitigation recommendations available.</p>
      )}
    </Card>
  );
}
