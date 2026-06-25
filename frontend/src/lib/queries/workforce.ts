import { queryOptions, useQueries, useQuery } from "@tanstack/react-query";
import { useMemo } from "react";

import { listProjectTeams, listTeamAnnotators } from "@/lib/api";
import { queryKeys, STALE_TIME_MS } from "@/lib/queries/keys";
import type { AnnotatorRead, DeliverySite, TeamRead } from "@/types/workforce";

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
