import { useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { toast } from "sonner";
import { PageLoadingScreen } from "@/components/bsg/PageLoadingScreen";
import { KpiCard, SectionGroupHeading } from "@/components/bsg/widgets";
import { resolveRiskAlert, type ProjectRead } from "@/lib/api";
import { queryKeys } from "@/lib/queries/keys";
import { useQualityPageQuery } from "@/lib/queries/quality";
import { cn } from "@/lib/utils";
import { AskQualityAgentPanel } from "./AskQualityAgentPanel";
import { CalibrationBriefCard } from "./CalibrationBriefCard";
import { DriftAlertsCard } from "./DriftAlertsCard";
import { ErrorBreakdownChart } from "./ErrorBreakdownChart";
import { fmtIaa, fmtPct, kpiTone } from "./format";
import { NeedsAttentionBanner } from "./NeedsAttentionBanner";
import { QualityNarrativeCard } from "./QualityNarrativeCard";
import { QualityToolbar } from "./QualityToolbar";
import { QualityTrendChart } from "./QualityTrendChart";
import { ReviewerScorecardsCard } from "./ReviewerScorecardsCard";
import { SopAmbiguityCard } from "./SopAmbiguityCard";
import { TeamScorecardCard } from "./TeamScorecardCard";

type Props = {
  projects: ProjectRead[];
  activeProjectId: string | undefined;
  loadingProjects: boolean;
  onSelectProject: (projectId: string) => void;
};

export function QualityDashboard({
  projects,
  activeProjectId,
  loadingProjects,
  onSelectProject,
}: Props) {
  const queryClient = useQueryClient();
  const [resolvingId, setResolvingId] = useState<string | null>(null);

  const {
    data: qualityPage,
    isLoading,
    isFetching,
    isPlaceholderData,
    isError,
    error,
  } = useQualityPageQuery(activeProjectId);

  const dashboard = qualityPage?.dashboard;
  const calibrationBrief = qualityPage?.calibration_brief;
  const sopFlags = qualityPage?.sop_ambiguity_flags ?? [];
  const reviewerScorecards = qualityPage?.reviewer_scorecards ?? [];
  // `isPlaceholderData` (from `placeholderData: keepPreviousData` in
  // qualityPageQueryOptions) is true for the entire window where the page
  // is showing the PREVIOUS project's data standing in for the new one --
  // i.e. exactly a project switch in progress -- and only flips back to
  // false once the real data for the newly-selected project has arrived.
  // `isFetching` alone covers the other "updating" case this indicator
  // needs (a background revalidation of the SAME project's already-loaded
  // data, e.g. after resolving an alert below invalidates this query).
  const isUpdating = isPlaceholderData || (isFetching && Boolean(qualityPage));

  const handleResolveAlert = async (alertId: string) => {
    setResolvingId(alertId);
    try {
      await resolveRiskAlert(alertId, "Resolved from Quality dashboard");
      await queryClient.invalidateQueries({
        queryKey: queryKeys.qualityPage(activeProjectId ?? ""),
      });
      toast.success("Alert resolved.");
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Failed to resolve alert.");
    } finally {
      setResolvingId(null);
    }
  };

  const pageLoading = loadingProjects || (Boolean(activeProjectId) && isLoading);

  return (
    <div className="space-y-5">
      <QualityToolbar
        projects={projects}
        activeProjectId={activeProjectId}
        onSelectProject={onSelectProject}
        isUpdating={isUpdating}
        disabled={loadingProjects || projects.length === 0}
      />

      {pageLoading ? (
        <PageLoadingScreen />
      ) : isError ? (
        <p className="text-sm text-[color:var(--danger)]">
          {error instanceof Error ? error.message : "Failed to load quality data."}
        </p>
      ) : null}

      {dashboard && !pageLoading && (
        <div
          className={cn(
            "space-y-5 transition-opacity",
            isUpdating && "pointer-events-none opacity-60",
          )}
        >
          <NeedsAttentionBanner
            dashboard={dashboard}
            calibrationBrief={calibrationBrief}
            sopFlags={sopFlags}
          />

          <div className="grid grid-cols-2 gap-4 lg:grid-cols-4">
            <KpiCard
              label="Gold-Set Accuracy"
              value={fmtPct(dashboard.kpis.gold_set_accuracy_pct)}
              tone={kpiTone(dashboard.kpis.gold_set_accuracy_pct, "accuracy")}
            />
            <KpiCard
              label="IAA (Krippendorff α)"
              value={fmtIaa(dashboard.kpis.iaa_krippendorff_alpha)}
              tone={kpiTone(dashboard.kpis.iaa_krippendorff_alpha, "iaa")}
            />
            <KpiCard
              label="Rework Rate"
              value={fmtPct(dashboard.kpis.rework_rate_pct)}
              delta={
                dashboard.kpis.rework_rate_target_pct != null &&
                dashboard.kpis.rework_rate_pct != null
                  ? `target ≤${Number(dashboard.kpis.rework_rate_target_pct).toFixed(1)}%`
                  : undefined
              }
              tone={kpiTone(dashboard.kpis.rework_rate_pct, "rework")}
            />
            <KpiCard
              label="Active Drift Alerts"
              value={String(dashboard.kpis.active_drift_alerts)}
              tone={kpiTone(dashboard.kpis.active_drift_alerts, "alerts")}
            />
          </div>

          {dashboard.narrative && <QualityNarrativeCard narrative={dashboard.narrative} />}

          <div className="space-y-5">
            <SectionGroupHeading title="Needs Attention" />
            <DriftAlertsCard
              alerts={dashboard.drift_alerts}
              resolvingId={resolvingId}
              onResolve={(id) => void handleResolveAlert(id)}
            />
            {calibrationBrief && <CalibrationBriefCard brief={calibrationBrief} />}
            <SopAmbiguityCard flags={sopFlags} />
          </div>

          <div className="space-y-5">
            <SectionGroupHeading title="Trends & Analysis" />
            <div className="grid grid-cols-1 gap-5 lg:grid-cols-2">
              <QualityTrendChart trend={dashboard.trend} />
              <ErrorBreakdownChart breakdown={dashboard.error_breakdown} />
            </div>
          </div>

          <div className="space-y-5">
            <SectionGroupHeading title="Performance Scorecards" />
            <TeamScorecardCard dashboard={dashboard} />
            <ReviewerScorecardsCard scorecards={reviewerScorecards} />
          </div>

          <AskQualityAgentPanel projectId={activeProjectId} />
        </div>
      )}
    </div>
  );
}
