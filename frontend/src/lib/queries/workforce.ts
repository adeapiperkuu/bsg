import { queryOptions, useQueries, useQuery } from "@tanstack/react-query";
import { useMemo } from "react";

import { listProjectTeams, listProjectUtilization, listTeamAnnotators } from "@/lib/api";
import { queryKeys, STALE_TIME_MS } from "@/lib/queries/keys";
import type {
  AnnotatorRead,
  DeliverySite,
  ProjectUtilizationFilters,
  TeamRead,
  UtilizationSnapshotRead,
} from "@/types/workforce";

export function projectTeamsQueryOptions(projectId: string | null) {
  return queryOptions({
    queryKey: queryKeys.projectTeams(projectId ?? ""),
    queryFn: () => listProjectTeams(projectId!),
    enabled: Boolean(projectId),
    staleTime: STALE_TIME_MS,
  });
}

export function teamAnnotatorsQueryOptions(teamId: string, enabled = true) {
  return queryOptions({
    queryKey: queryKeys.teamAnnotators(teamId),
    queryFn: () => listTeamAnnotators(teamId),
    enabled: Boolean(teamId) && enabled,
    staleTime: STALE_TIME_MS,
  });
}

export function useProjectTeamsQuery(projectId: string | null) {
  return useQuery(projectTeamsQueryOptions(projectId));
}

export type SiteWorkforceStats = {
  teams: number;
  activeTeams: number;
  annotators: number;
  smes: number;
};

export type ProjectWorkforceSummary = {
  teams: TeamRead[];
  annotatorsByTeam: Map<string, AnnotatorRead[]>;
  activeTeams: TeamRead[];
  activeAnnotators: AnnotatorRead[];
  activeAnnotatorCount: number;
  smeCount: number;
  smeCoveragePct: number | null;
  teamsBySite: Record<DeliverySite, SiteWorkforceStats>;
};

function emptySiteStats(): Record<DeliverySite, SiteWorkforceStats> {
  return {
    india: { teams: 0, activeTeams: 0, annotators: 0, smes: 0 },
    kosovo: { teams: 0, activeTeams: 0, annotators: 0, smes: 0 },
  };
}

export function buildProjectWorkforceSummary(
  teams: TeamRead[],
  annotatorsByTeam: Map<string, AnnotatorRead[]>,
): ProjectWorkforceSummary {
  const activeTeams = teams.filter((team) => team.is_active);
  const allAnnotators = [...annotatorsByTeam.values()].flat();
  const activeAnnotators = allAnnotators.filter((annotator) => annotator.is_active);
  const smeCount = activeAnnotators.filter((annotator) => annotator.is_sme_certified).length;
  const smeCoveragePct =
    activeAnnotators.length > 0
      ? Math.round((smeCount / activeAnnotators.length) * 100)
      : null;

  const teamsBySite = emptySiteStats();
  for (const team of teams) {
    const bucket = teamsBySite[team.site];
    bucket.teams += 1;
    if (team.is_active) bucket.activeTeams += 1;
    const teamAnnotators = annotatorsByTeam.get(team.id) ?? [];
    const activeTeamAnnotators = teamAnnotators.filter((annotator) => annotator.is_active);
    bucket.annotators += activeTeamAnnotators.length;
    bucket.smes += activeTeamAnnotators.filter((annotator) => annotator.is_sme_certified).length;
  }

  return {
    teams,
    annotatorsByTeam,
    activeTeams,
    activeAnnotators,
    activeAnnotatorCount: activeAnnotators.length,
    smeCount,
    smeCoveragePct,
    teamsBySite,
  };
}

export function useProjectWorkforceSummary(projectId: string | null, canReadAnnotators: boolean) {
  const teamsQuery = useProjectTeamsQuery(projectId);
  const teams = teamsQuery.data ?? [];

  const annotatorQueries = useQueries({
    queries: teams.map((team) => ({
      ...teamAnnotatorsQueryOptions(team.id, canReadAnnotators),
    })),
  });

  const annotatorsByTeam = useMemo(() => {
    const map = new Map<string, AnnotatorRead[]>();
    teams.forEach((team, index) => {
      map.set(team.id, annotatorQueries[index]?.data ?? []);
    });
    return map;
  }, [teams, annotatorQueries]);

  const summary = useMemo(
    () => buildProjectWorkforceSummary(teams, annotatorsByTeam),
    [teams, annotatorsByTeam],
  );

  const annotatorsLoading =
    canReadAnnotators && teams.length > 0 && annotatorQueries.some((query) => query.isLoading);
  const annotatorsError = canReadAnnotators
    ? annotatorQueries.find((query) => query.isError)?.error
    : null;

  return {
    teamsQuery,
    annotatorQueries,
    summary,
    isLoading: teamsQuery.isLoading || annotatorsLoading,
    isError: teamsQuery.isError || Boolean(annotatorsError),
    error:
      (teamsQuery.error instanceof Error ? teamsQuery.error.message : null) ??
      (annotatorsError instanceof Error ? annotatorsError.message : null),
  };
}

export function useTeamAnnotatorsQuery(teamId: string | null, enabled = true) {
  return useQuery({
    ...teamAnnotatorsQueryOptions(teamId ?? "", Boolean(teamId) && enabled),
  });
}

const UTILIZATION_CAPACITY_THRESHOLD = 85;
const UTILIZATION_UNDERUTILIZED_THRESHOLD = 60;

export function normalizeUtilizationPct(value: string | number): number {
  const parsed = typeof value === "number" ? value : Number.parseFloat(value);
  return Number.isFinite(parsed) ? parsed : 0;
}

export type TeamUtilizationPoint = {
  teamId: string;
  team: string;
  site: DeliverySite | null;
  value: number;
  snapshotDate: string;
};

export function buildLatestTeamUtilization(
  snapshots: UtilizationSnapshotRead[],
  teams: TeamRead[],
): TeamUtilizationPoint[] {
  const teamById = new Map(teams.map((team) => [team.id, team]));
  const latestByTeam = new Map<string, UtilizationSnapshotRead>();

  for (const snapshot of snapshots) {
    if (!snapshot.team_id) continue;
    const existing = latestByTeam.get(snapshot.team_id);
    if (!existing || snapshot.snapshot_date > existing.snapshot_date) {
      latestByTeam.set(snapshot.team_id, snapshot);
    }
  }

  return [...latestByTeam.entries()]
    .map(([teamId, snapshot]) => {
      const team = teamById.get(teamId);
      return {
        teamId,
        team: team?.name ?? `Team ${teamId.slice(0, 8)}`,
        site: team?.site ?? null,
        value: Math.round(normalizeUtilizationPct(snapshot.utilization_pct)),
        snapshotDate: snapshot.snapshot_date,
      };
    })
    .sort((left, right) => right.value - left.value);
}

export function summarizeTeamUtilization(points: TeamUtilizationPoint[]) {
  const overloaded = points.filter((point) => point.value >= UTILIZATION_CAPACITY_THRESHOLD).length;
  const underutilized = points.filter(
    (point) => point.value < UTILIZATION_UNDERUTILIZED_THRESHOLD,
  ).length;
  return {
    overloaded,
    underutilized,
    total: points.length,
    capacityThreshold: UTILIZATION_CAPACITY_THRESHOLD,
    underutilizedThreshold: UTILIZATION_UNDERUTILIZED_THRESHOLD,
  };
}

export function averageUtilizationBySite(
  points: TeamUtilizationPoint[],
): Record<DeliverySite, number | null> {
  const totals: Record<DeliverySite, { sum: number; count: number }> = {
    india: { sum: 0, count: 0 },
    kosovo: { sum: 0, count: 0 },
  };

  for (const point of points) {
    if (!point.site) continue;
    totals[point.site].sum += point.value;
    totals[point.site].count += 1;
  }

  return {
    india: totals.india.count > 0 ? Math.round(totals.india.sum / totals.india.count) : null,
    kosovo: totals.kosovo.count > 0 ? Math.round(totals.kosovo.sum / totals.kosovo.count) : null,
  };
}

export function projectUtilizationQueryOptions(
  projectId: string | null,
  enabled: boolean,
  filters: ProjectUtilizationFilters = {},
) {
  const filterKey = {
    team_id: filters.team_id,
    annotator_id: filters.annotator_id,
    from_date: filters.from_date,
    to_date: filters.to_date,
    limit: filters.limit,
  };

  return queryOptions({
    queryKey: queryKeys.projectUtilization(projectId ?? "", filterKey),
    queryFn: () => listProjectUtilization(projectId!, filters),
    enabled: Boolean(projectId) && enabled,
    staleTime: STALE_TIME_MS,
  });
}

export function useProjectUtilizationQuery(
  projectId: string | null,
  canReadUtilization: boolean,
  filters: ProjectUtilizationFilters = {},
) {
  return useQuery(projectUtilizationQueryOptions(projectId, canReadUtilization, filters));
}

export { UTILIZATION_CAPACITY_THRESHOLD, UTILIZATION_UNDERUTILIZED_THRESHOLD };
