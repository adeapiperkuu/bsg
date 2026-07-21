import { AiBadge, Card, SectionHeader } from "@/components/bsg/widgets";
import type { ProjectRootCausesResponse, RootCauseTrendsResponse } from "@/lib/api";
import { ImpactDistributionChart } from "./ImpactDistributionChart";
import { RootCauseBreakdownCard } from "./RootCauseBreakdownCard";
import { RootCauseTimeline } from "./RootCauseTimeline";
import { RootCauseTrendChart } from "./RootCauseTrendChart";
import { contributorsWithOther } from "./format";

type Props = {
  projectName?: string;
  rootCauses?: ProjectRootCausesResponse;
  trends?: RootCauseTrendsResponse;
  loading?: boolean;
  trendsLoading?: boolean;
  fallbackConfidence?: number | null;
};

export function DeliveryRootCauseSection({
  projectName,
  rootCauses,
  trends,
  loading = false,
  trendsLoading = false,
  fallbackConfidence = null,
}: Props) {
  const latest = rootCauses?.latest ?? null;
  const contributors = contributorsWithOther(latest?.main_contributors ?? []);
  const confidence = latest?.overall_confidence ?? fallbackConfidence;

  return (
    <Card>
      <SectionHeader
        title="Root Cause Analysis"
        sub={
          projectName
            ? `Why delivery confidence changed for ${projectName}`
            : "Deterministic confidence-loss breakdown"
        }
        right={
          <AiBadge
            label="Root cause"
            source="formula"
            confidence={confidence == null ? undefined : Math.round(confidence)}
          />
        }
      />
      <RootCauseBreakdownCard
        confidence={confidence}
        confidenceLoss={latest?.confidence_loss ?? null}
        contributors={contributors}
        factors={latest?.factors}
        loading={loading}
      />
      <div className="mt-4 space-y-4 border-t border-border pt-4">
        <div>
          <p className="mb-2 text-xs uppercase tracking-wide text-muted-foreground">
            Impact distribution
          </p>
          <ImpactDistributionChart contributors={contributors} loading={loading} />
        </div>
        <div>
          <p className="mb-2 text-xs uppercase tracking-wide text-muted-foreground">Trends</p>
          <RootCauseTrendChart factors={trends?.factors ?? []} loading={trendsLoading} />
        </div>
        <div>
          <p className="mb-2 text-xs uppercase tracking-wide text-muted-foreground">Timeline</p>
          <RootCauseTimeline history={rootCauses?.history ?? []} loading={loading} />
        </div>
      </div>
    </Card>
  );
}
