import { Card, SectionHeader } from "@/components/bsg/widgets";
import { ManageToggleButton } from "@/components/bsg/workforce/ManageToggleButton";
import { UtilizationBarChart } from "@/components/bsg/workforce/UtilizationBarChart";
import { UtilizationTrendChart } from "@/components/bsg/workforce/UtilizationTrendChart";
import { WorkforcePlaceholder } from "@/components/bsg/workforce/WorkforcePlaceholder";
import { UtilizationSnapshotsManager } from "@/components/bsg/WorkforceManagement";
import type { UtilizationTrendPoint } from "@/hooks/useWorkforceDashboardFilters";
import type { TeamUtilizationPoint } from "@/lib/queries/workforce";
import type { TeamRead } from "@/types/workforce";

export function WorkforceUtilizationSection({
  canReadInternalWorkforce,
  canManageWorkforce,
  resolvedProjectId,
  utilizationLoading,
  teamUtilization,
  filteredTeamUtilization,
  filteredUtilizationStats,
  filteredUtilizationYAxisMax,
  utilizationTrend,
  showUtilizationManager,
  onToggleUtilizationManager,
  teams,
  capacityThreshold,
}: {
  canReadInternalWorkforce: boolean;
  canManageWorkforce: boolean;
  resolvedProjectId: string | null;
  utilizationLoading: boolean;
  teamUtilization: TeamUtilizationPoint[];
  filteredTeamUtilization: TeamUtilizationPoint[];
  filteredUtilizationStats: {
    overloaded: number;
    underutilized: number;
    total: number;
    capacityThreshold: number;
    underutilizedThreshold: number;
  };
  filteredUtilizationYAxisMax: number;
  utilizationTrend: UtilizationTrendPoint[];
  showUtilizationManager: boolean;
  onToggleUtilizationManager: () => void;
  teams: TeamRead[];
  capacityThreshold: number;
}) {
  return (
    <Card>
      <SectionHeader
        title="Workforce Utilization"
        sub={`By team / ${capacityThreshold}% capacity threshold`}
        right={
          canReadInternalWorkforce && resolvedProjectId ? (
            <ManageToggleButton
              active={showUtilizationManager}
              onClick={onToggleUtilizationManager}
              label={canManageWorkforce ? "Manage" : "Details"}
            />
          ) : undefined
        }
      />
      {!canReadInternalWorkforce ? (
        <WorkforcePlaceholder
          title="Utilization data restricted"
          reason="Internal workforce utilization is not available to client users."
        />
      ) : utilizationLoading ? (
        <div className="h-60 animate-pulse rounded-md bg-elevated" />
      ) : teamUtilization.length === 0 ? (
        <WorkforcePlaceholder
          title="No utilization snapshots yet"
          reason="Add utilization snapshots for project teams to populate this chart."
        />
      ) : filteredTeamUtilization.length === 0 ? (
        <WorkforcePlaceholder
          title="No utilization data matches the current filters"
          reason="Change the site or domain filter to see utilization for more teams."
        />
      ) : (
        <>
          <UtilizationBarChart
            data={filteredTeamUtilization}
            yAxisMax={filteredUtilizationYAxisMax}
            capacityThreshold={capacityThreshold}
          />
          <div className="mt-3 flex flex-wrap gap-3 text-[11px] text-muted-foreground">
            {filteredUtilizationStats.overloaded > 0 && (
              <span className="text-[color:var(--warning)]">
                {filteredUtilizationStats.overloaded} team(s) at or above {capacityThreshold}%
              </span>
            )}
            {filteredUtilizationStats.underutilized > 0 && (
              <span>
                {filteredUtilizationStats.underutilized} team(s) below{" "}
                {filteredUtilizationStats.underutilizedThreshold}%
              </span>
            )}
          </div>
          <div className="mt-5 border-t border-border pt-4">
            <div className="mb-2">
              <div className="text-xs font-semibold">Utilization trend</div>
              <div className="text-[11px] text-muted-foreground">
                Average team utilization across snapshot dates
              </div>
            </div>
            {utilizationTrend.length < 2 ? (
              <WorkforcePlaceholder
                title="Not enough utilization history for a trend yet"
                reason="Add utilization snapshots across multiple dates to see a trend."
              />
            ) : (
              <UtilizationTrendChart
                data={utilizationTrend}
                yAxisMax={filteredUtilizationYAxisMax}
                capacityThreshold={capacityThreshold}
              />
            )}
          </div>
        </>
      )}
      {canReadInternalWorkforce && resolvedProjectId && showUtilizationManager ? (
        <UtilizationSnapshotsManager
          projectId={resolvedProjectId}
          teams={teams}
          canManage={canManageWorkforce}
        />
      ) : null}
    </Card>
  );
}
