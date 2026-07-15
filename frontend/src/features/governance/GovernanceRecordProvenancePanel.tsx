import { useQuery } from "@tanstack/react-query";

import { SectionHeader, StatusPill } from "@/components/bsg/widgets";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import {
  getActionEvidence,
  getActionSourceRecommendation,
  getEscalationEvidence,
  getEscalationSourceRecommendation,
} from "@/lib/queries/governance";
import type { GovernanceAction, GovernanceEscalation } from "@/types/governance";

type ProvenanceTarget =
  | { kind: "action"; record: GovernanceAction }
  | { kind: "escalation"; record: GovernanceEscalation };

export function GovernanceRecordProvenancePanel({
  target,
  enabled,
}: {
  target: ProvenanceTarget;
  enabled: boolean;
}) {
  const hasAiSource = Boolean(target.record.has_ai_source);
  const evidenceCount = target.record.evidence_link_count ?? 0;
  const sourceQuery = useQuery({
    queryKey: ["governance", target.kind, target.record.id, "source-recommendation"],
    queryFn: () =>
      target.kind === "action"
        ? getActionSourceRecommendation(target.record.id)
        : getEscalationSourceRecommendation(target.record.id),
    enabled: enabled && hasAiSource,
  });
  const evidenceQuery = useQuery({
    queryKey: ["governance", target.kind, target.record.id, "evidence"],
    queryFn: () =>
      target.kind === "action"
        ? getActionEvidence(target.record.id)
        : getEscalationEvidence(target.record.id),
    enabled: enabled && hasAiSource && evidenceCount > 0,
  });

  if (!enabled || !hasAiSource) {
    return null;
  }

  return (
    <div className="mt-4 space-y-3 rounded-md border border-border bg-elevated p-3">
      <SectionHeader title="Source" sub="AI Governance Recommendation provenance" />
      {sourceQuery.isLoading ? (
        <Skeleton className="h-12 w-full" />
      ) : sourceQuery.isError ? (
        <p className="text-xs text-destructive">Unable to load source recommendation.</p>
      ) : sourceQuery.data ? (
        <div className="space-y-1 text-xs">
          <p className="font-medium">{sourceQuery.data.title}</p>
          <div className="flex flex-wrap gap-2 text-muted-foreground">
            {sourceQuery.data.priority ? (
              <StatusPill status={sourceQuery.data.priority} />
            ) : null}
            {sourceQuery.data.confidence != null ? (
              <span>Confidence {Math.round(sourceQuery.data.confidence * 100)}%</span>
            ) : null}
            {sourceQuery.data.generated_at ? (
              <span>Generated {new Date(sourceQuery.data.generated_at).toLocaleString()}</span>
            ) : null}
            {!sourceQuery.data.source_available ? <span>Source unavailable</span> : null}
          </div>
          {sourceQuery.data.can_view ? (
            <Button type="button" size="sm" variant="outline" className="mt-2 shadow-none" disabled>
              Open recommendation
            </Button>
          ) : null}
        </div>
      ) : (
        <p className="text-xs text-muted-foreground">No source recommendation linked.</p>
      )}

      <SectionHeader title="Supporting evidence" sub={`${evidenceCount} linked item(s)`} />
      {evidenceQuery.isLoading ? (
        <Skeleton className="h-16 w-full" />
      ) : evidenceQuery.isError ? (
        <p className="text-xs text-destructive">Unable to load evidence links.</p>
      ) : (evidenceQuery.data ?? []).length === 0 ? (
        <p className="text-xs text-muted-foreground">No supporting evidence links.</p>
      ) : (
        <ul className="space-y-2 text-xs">
          {(evidenceQuery.data ?? [])
            .filter((item) => item.link_type !== "ai_recommendation_source")
            .map((item) => (
              <li key={item.id} className="rounded border border-border px-2 py-1.5">
                <div className="flex items-start justify-between gap-2">
                  <div>
                    <p className="font-medium">{item.title ?? item.source_type}</p>
                    <p className="text-muted-foreground">
                      {item.source_type}
                      {item.status ? ` · ${item.status}` : ""}
                      {item.project_name ? ` · ${item.project_name}` : ""}
                    </p>
                    {!item.source_available ? (
                      <p className="text-[10px] text-muted-foreground">Source unavailable</p>
                    ) : null}
                  </div>
                  {item.severity ? <StatusPill status={item.severity} /> : null}
                </div>
              </li>
            ))}
        </ul>
      )}
    </div>
  );
}
