import { ChevronDown } from "lucide-react";
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
import { cn } from "@/lib/utils";
import { useMemo, useState } from "react";

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
  const [selectedTitle, setSelectedTitle] = useState<string | null>(null);
  const acceptMutation = useAcceptRecommendationMutation(projectId);
  const rejectMutation = useRejectRecommendationMutation(projectId);
  const assignMutation = useAssignRecommendationOwnerMutation(projectId);

  const { active, historical } = useMemo(
    () => splitGroupsByDecision(data?.data ?? []),
    [data?.data],
  );
  // Active recommendations first (ordered by severity, then confidence), historical after.
  const tabs = useMemo(() => {
    const flatten = (
      groups: Array<{ severity: RecommendationSeverity; items: GroupedMitigationRecommendation[] }>,
    ) => groups.flatMap((group) => group.items);
    return [
      ...flatten(groupBySeverity(active)).map((recommendation) => ({
        recommendation,
        historical: false,
      })),
      ...flatten(groupBySeverity(historical)).map((recommendation) => ({
        recommendation,
        historical: true,
      })),
    ];
  }, [active, historical]);

  const assignableOwners = data?.assignable_owners ?? [];
  const selected = tabs.find((tab) => tab.recommendation.title === selectedTitle) ?? null;

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
      ) : tabs.length === 0 ? (
        <p className="text-sm text-muted-foreground">No mitigation recommendations available.</p>
      ) : (
        <>
          <div className="mb-3 flex flex-wrap border-b border-border">
            {tabs.map(({ recommendation, historical: isHistorical }) => {
              const isSelected = selectedTitle === recommendation.title;
              return (
                <button
                  key={recommendation.title}
                  type="button"
                  aria-expanded={isSelected}
                  onClick={() => setSelectedTitle(isSelected ? null : recommendation.title)}
                  className={cn(
                    "flex items-center gap-1.5 border-b-2 px-3 py-1.5 text-xs font-medium transition-colors",
                    isSelected
                      ? "border-[color:var(--brand)] text-foreground"
                      : "border-transparent text-muted-foreground hover:text-foreground",
                    isHistorical && !isSelected && "opacity-60",
                  )}
                >
                  <span className="rounded-full border border-border bg-secondary px-1.5 py-px text-[9px] font-semibold uppercase tracking-wide">
                    {SEVERITY_LABELS[recommendation.severity]}
                  </span>
                  {recommendation.title}
                  <ChevronDown
                    className={cn(
                      "h-3.5 w-3.5 transition-transform",
                      isSelected ? "" : "-rotate-90",
                    )}
                  />
                </button>
              );
            })}
          </div>

          {selected ? (
            <div className="space-y-2">
              {selected.historical ? (
                <p className="text-[11px] text-muted-foreground">
                  Historical decision — every linked risk was rejected, kept for the record only.
                </p>
              ) : null}
              <RecommendationCard
                recommendation={selected.recommendation}
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
            </div>
          ) : null}
        </>
      )}
    </Card>
  );
}
