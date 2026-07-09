import { useEffect, useMemo, useState } from "react";

import {
  averageUtilizationBySite,
  normalizeUtilizationPct,
  summarizeTeamUtilization,
  type TeamUtilizationPoint,
} from "@/lib/queries/workforce";
import type {
  CapabilityGapRead,
  DeliverySite,
  SkillMatrixRow,
  TeamRead,
  TrainingGapRow,
  UtilizationSnapshotRead,
} from "@/types/workforce";

export const WORKFORCE_ALL_SITES: DeliverySite[] = ["india", "kosovo"];

export type WorkforceSiteFilter = DeliverySite | "all";

export type UtilizationTrendPoint = {
  date: string;
  value: number;
};

export type WorkforceCapabilityGapsSummary = {
  openCount: number;
  highCriticalCount: number;
  latestDetected: string | null;
};

export type UseWorkforceDashboardFiltersParams = {
  projectId: string | null;
  teams: TeamRead[];
  skillMatrixRows: SkillMatrixRow[];
  teamUtilization: TeamUtilizationPoint[];
  utilizationSnapshots: UtilizationSnapshotRead[];
  trainingGapRows: TrainingGapRow[];
  capabilityGaps: CapabilityGapRead[];
};

function summarizeCapabilityGaps(gaps: CapabilityGapRead[]): WorkforceCapabilityGapsSummary {
  const openGaps = gaps.filter((gap) => gap.status === "open" || gap.status === "acknowledged");
  const highCritical = openGaps.filter(
    (gap) => gap.severity === "high" || gap.severity === "critical",
  );
  const latestDetected =
    gaps.length > 0
      ? gaps.reduce(
          (latest, gap) => (gap.detected_at > latest ? gap.detected_at : latest),
          gaps[0]!.detected_at,
        )
      : null;
  return { openCount: openGaps.length, highCriticalCount: highCritical.length, latestDetected };
}

function matchesSkillMatrixFilters(
  skillRow: SkillMatrixRow | undefined,
  domainFilter: string,
  categoryFilter: string,
): boolean {
  if (!skillRow) return true;
  if (domainFilter !== "all" && skillRow.domain !== domainFilter) return false;
  if (categoryFilter !== "all" && skillRow.category !== categoryFilter) return false;
  return true;
}

export function useWorkforceDashboardFilters({
  projectId,
  teams,
  skillMatrixRows,
  teamUtilization,
  utilizationSnapshots,
  trainingGapRows,
  capabilityGaps,
}: UseWorkforceDashboardFiltersParams) {
  const [siteFilter, setSiteFilter] = useState<WorkforceSiteFilter>("all");
  const [domainFilter, setDomainFilter] = useState("all");
  const [categoryFilter, setCategoryFilter] = useState("all");

  useEffect(() => {
    setSiteFilter("all");
    setDomainFilter("all");
    setCategoryFilter("all");
  }, [projectId]);

  const domainOptions = useMemo(() => {
    const values = new Set<string>();
    for (const team of teams) values.add(team.domain);
    for (const row of skillMatrixRows) {
      if (row.domain) values.add(row.domain);
    }
    return [...values].sort((left, right) => left.localeCompare(right));
  }, [teams, skillMatrixRows]);

  const categoryOptions = useMemo(() => {
    const values = new Set<string>();
    for (const row of skillMatrixRows) {
      if (row.category) values.add(row.category);
    }
    return [...values].sort((left, right) => left.localeCompare(right));
  }, [skillMatrixRows]);

  const filteredTeams = useMemo(
    () =>
      teams.filter(
        (team) =>
          (siteFilter === "all" || team.site === siteFilter) &&
          (domainFilter === "all" || team.domain === domainFilter),
      ),
    [teams, siteFilter, domainFilter],
  );

  const filteredTeamIds = useMemo(
    () => new Set(filteredTeams.map((team) => team.id)),
    [filteredTeams],
  );

  const teamById = useMemo(() => new Map(teams.map((team) => [team.id, team])), [teams]);

  const skillMatrixBySkillId = useMemo(() => {
    const map = new Map<string, SkillMatrixRow>();
    for (const row of skillMatrixRows) {
      map.set(row.skill_id, row);
    }
    return map;
  }, [skillMatrixRows]);

  const filteredSkillMatrixRows = useMemo(
    () =>
      skillMatrixRows.filter(
        (row) =>
          (domainFilter === "all" || row.domain === domainFilter) &&
          (categoryFilter === "all" || row.category === categoryFilter),
      ),
    [skillMatrixRows, domainFilter, categoryFilter],
  );

  const filteredTeamUtilization = useMemo(
    () => teamUtilization.filter((point) => filteredTeamIds.has(point.teamId)),
    [teamUtilization, filteredTeamIds],
  );

  const filteredUtilizationStats = useMemo(
    () => summarizeTeamUtilization(filteredTeamUtilization),
    [filteredTeamUtilization],
  );

  const filteredUtilizationYAxisMax = useMemo(() => {
    const peak = filteredTeamUtilization.reduce((max, point) => Math.max(max, point.value), 0);
    if (peak <= 100) return 100;
    return Math.ceil(peak / 10) * 10 + 10;
  }, [filteredTeamUtilization]);

  const filteredSiteUtilization = useMemo(
    () => averageUtilizationBySite(filteredTeamUtilization),
    [filteredTeamUtilization],
  );

  const visibleSites = useMemo<DeliverySite[]>(
    () => (siteFilter === "all" ? WORKFORCE_ALL_SITES : [siteFilter]),
    [siteFilter],
  );

  const utilizationTrend = useMemo<UtilizationTrendPoint[]>(() => {
    const snapshotsByDate = new Map<string, number[]>();
    for (const snapshot of utilizationSnapshots) {
      if (!snapshot.team_id || snapshot.annotator_id) continue;
      if (!filteredTeamIds.has(snapshot.team_id)) continue;
      const team = teamById.get(snapshot.team_id);
      if (domainFilter !== "all" && team?.domain !== domainFilter) continue;
      const values = snapshotsByDate.get(snapshot.snapshot_date) ?? [];
      values.push(normalizeUtilizationPct(snapshot.utilization_pct));
      snapshotsByDate.set(snapshot.snapshot_date, values);
    }
    return [...snapshotsByDate.entries()]
      .map(([date, values]) => ({
        date,
        value: Math.round(values.reduce((sum, value) => sum + value, 0) / values.length),
      }))
      .sort((left, right) => left.date.localeCompare(right.date));
  }, [utilizationSnapshots, filteredTeamIds, teamById, domainFilter]);

  const filteredTrainingGapRows = useMemo(
    () =>
      trainingGapRows.filter((row) => {
        if (row.team_id && !filteredTeamIds.has(row.team_id)) return false;
        const skillRow = row.skill_id ? skillMatrixBySkillId.get(row.skill_id) : undefined;
        return matchesSkillMatrixFilters(skillRow, domainFilter, categoryFilter);
      }),
    [trainingGapRows, filteredTeamIds, skillMatrixBySkillId, domainFilter, categoryFilter],
  );

  const filteredCapabilityGaps = useMemo(
    () =>
      capabilityGaps.filter((gap) => {
        if (gap.team_id && !filteredTeamIds.has(gap.team_id)) return false;
        const skillRow = gap.skill_id ? skillMatrixBySkillId.get(gap.skill_id) : undefined;
        return matchesSkillMatrixFilters(skillRow, domainFilter, categoryFilter);
      }),
    [capabilityGaps, filteredTeamIds, skillMatrixBySkillId, domainFilter, categoryFilter],
  );

  const filteredCapabilityGapsSummary = useMemo(
    () => summarizeCapabilityGaps(filteredCapabilityGaps),
    [filteredCapabilityGaps],
  );

  return {
    siteFilter,
    setSiteFilter,
    domainFilter,
    setDomainFilter,
    categoryFilter,
    setCategoryFilter,
    domainOptions,
    categoryOptions,
    filteredTeams,
    filteredTeamIds,
    teamById,
    filteredSkillMatrixRows,
    filteredTeamUtilization,
    filteredUtilizationStats,
    filteredUtilizationYAxisMax,
    filteredSiteUtilization,
    visibleSites,
    utilizationTrend,
    filteredTrainingGapRows,
    filteredCapabilityGaps,
    filteredCapabilityGapsSummary,
  };
}
