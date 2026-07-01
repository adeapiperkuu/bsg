import type { UseMutationResult } from "@tanstack/react-query";

import { Card, SectionHeader } from "@/components/bsg/widgets";
import { CapabilityGapRowView } from "@/components/bsg/workforce/CapabilityGapRowView";
import { WorkforcePlaceholder } from "@/components/bsg/workforce/WorkforcePlaceholder";
import type { WorkforceCapabilityGapsSummary } from "@/hooks/useWorkforceDashboardFilters";
import { formatDetectedAt } from "@/lib/workforceLabels";
import type { CapabilityGapRead, CapabilityGapStatus } from "@/types/workforce";

export function CapabilityGapsSection({
  canReadInternalWorkforce,
  canManageWorkforce,
  resolvedProjectId,
  capabilityGapsLoading,
  capabilityGapsError,
  capabilityGaps,
  filteredCapabilityGaps,
  filteredCapabilityGapsSummary,
  detectMessage,
  recommendMessage,
  actionError,
  updatingGapId,
  detectGapsMutation,
  generateRecommendationsMutation,
  triggerDetectGaps,
  triggerGenerateRecommendations,
  handleGapStatusUpdate,
}: {
  canReadInternalWorkforce: boolean;
  canManageWorkforce: boolean;
  resolvedProjectId: string | null;
  capabilityGapsLoading: boolean;
  capabilityGapsError: string | null;
  capabilityGaps: CapabilityGapRead[];
  filteredCapabilityGaps: CapabilityGapRead[];
  filteredCapabilityGapsSummary: WorkforceCapabilityGapsSummary;
  detectMessage: string | null;
  recommendMessage: string | null;
  actionError: string | null;
  updatingGapId: string | null;
  detectGapsMutation: UseMutationResult<unknown, Error, void>;
  generateRecommendationsMutation: UseMutationResult<unknown, Error, void>;
  triggerDetectGaps: () => void;
  triggerGenerateRecommendations: () => void;
  handleGapStatusUpdate: (gapId: string, status: CapabilityGapStatus) => Promise<void>;
}) {
  return (
    <Card>
      <SectionHeader
        title="Capability Gaps"
        sub="Detected workforce skill, training, and utilization gaps"
        right={
          canManageWorkforce && resolvedProjectId ? (
            <div className="flex flex-wrap items-center gap-2">
              <button
                type="button"
                onClick={triggerDetectGaps}
                disabled={detectGapsMutation.isPending || generateRecommendationsMutation.isPending}
                className="rounded border border-border bg-elevated px-2.5 py-1 text-[11px] font-medium text-foreground hover:bg-card disabled:opacity-50"
              >
                {detectGapsMutation.isPending ? "Detecting..." : "Detect gaps"}
              </button>
              <button
                type="button"
                onClick={triggerGenerateRecommendations}
                disabled={detectGapsMutation.isPending || generateRecommendationsMutation.isPending}
                className="rounded border border-[color:var(--brand)]/30 bg-[color:var(--brand)]/10 px-2.5 py-1 text-[11px] font-medium text-[color:var(--brand)] hover:bg-[color:var(--brand)]/20 disabled:opacity-50"
              >
                {generateRecommendationsMutation.isPending
                  ? "Generating..."
                  : "Generate recommendations"}
              </button>
            </div>
          ) : undefined
        }
      />
      {!canReadInternalWorkforce ? (
        <WorkforcePlaceholder
          title="Capability gaps restricted"
          reason="Internal workforce capability gaps are not available to client users."
        />
      ) : capabilityGapsLoading ? (
        <div className="space-y-2">
          <div className="h-8 animate-pulse rounded-md bg-elevated" />
          <div className="h-10 animate-pulse rounded-md bg-elevated" />
          <div className="h-10 animate-pulse rounded-md bg-elevated" />
        </div>
      ) : capabilityGapsError ? (
        <p className="text-sm text-[color:var(--danger)]">{capabilityGapsError}</p>
      ) : (
        <>
          {canReadInternalWorkforce && (
            <div className="mb-4 flex flex-wrap gap-2">
              <span className="rounded border border-border bg-elevated px-2 py-1 text-[11px] text-muted-foreground">
                {filteredCapabilityGapsSummary.openCount} open gap
                {filteredCapabilityGapsSummary.openCount === 1 ? "" : "s"}
              </span>
              {filteredCapabilityGapsSummary.highCriticalCount > 0 && (
                <span className="rounded border border-[color:var(--danger)]/30 bg-[color:var(--danger)]/10 px-2 py-1 text-[11px] font-medium text-[color:var(--danger)]">
                  {filteredCapabilityGapsSummary.highCriticalCount} high/critical
                </span>
              )}
              {filteredCapabilityGapsSummary.latestDetected && (
                <span className="rounded border border-border bg-elevated px-2 py-1 text-[11px] text-muted-foreground">
                  Latest: {formatDetectedAt(filteredCapabilityGapsSummary.latestDetected)}
                </span>
              )}
            </div>
          )}
          {detectMessage && (
            <p className="mb-3 text-xs text-[color:var(--success)]">{detectMessage}</p>
          )}
          {recommendMessage && (
            <p className="mb-3 text-xs text-[color:var(--success)]">{recommendMessage}</p>
          )}
          {actionError && <p className="mb-3 text-xs text-[color:var(--danger)]">{actionError}</p>}
          {capabilityGaps.length === 0 ? (
            <WorkforcePlaceholder
              title="No capability gaps recorded"
              reason={
                canManageWorkforce
                  ? "Run gap detection to scan skill coverage, training, certifications, and utilization."
                  : "No open capability gaps have been recorded for this project."
              }
            />
          ) : filteredCapabilityGaps.length === 0 ? (
            <WorkforcePlaceholder
              title="No capability gaps match the current filters"
              reason="Change the site, domain, or skill category filter to review more gaps."
            />
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full text-xs">
                <thead className="text-left text-muted-foreground">
                  <tr className="border-b border-border">
                    <th className="py-2 pr-3 font-medium">Title</th>
                    <th className="py-2 pr-3 font-medium">Type</th>
                    <th className="py-2 pr-3 font-medium">Severity</th>
                    <th className="py-2 pr-3 font-medium">Status</th>
                    <th className="py-2 pr-3 font-medium">Detected</th>
                    {canManageWorkforce && <th className="py-2 pr-3 font-medium">Actions</th>}
                  </tr>
                </thead>
                <tbody>
                  {filteredCapabilityGaps.map((gap) => (
                    <CapabilityGapRowView
                      key={gap.id}
                      gap={gap}
                      canManage={canManageWorkforce}
                      isUpdating={updatingGapId === gap.id}
                      onStatusUpdate={handleGapStatusUpdate}
                    />
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
