import { createFileRoute, useNavigate } from "@tanstack/react-router";
import {
  BarChart,
  Bar,
  ResponsiveContainer,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ReferenceLine,
} from "recharts";
import { useEffect, useMemo, useRef, useState } from "react";
import { Card, SectionHeader, KpiCard, AiBadge, StatusPill } from "@/components/bsg/widgets";
import { useProjectsQuery } from "@/lib/queries/delivery";
import {
  UTILIZATION_CAPACITY_THRESHOLD,
  averageUtilizationBySite,
  buildLatestTeamUtilization,
  summarizeTeamUtilization,
  useProjectSkillMatrixQuery,
  useProjectTrainingGapsQuery,
  useProjectUtilizationQuery,
  useProjectWorkforceSummary,
} from "@/lib/queries/workforce";
import { useAuthStore } from "@/stores/useAuthStore";
import type { AppRole } from "@/types/auth";
import type {
  DeliverySite,
  SkillCoverageStatus,
  SkillMatrixRow,
  TeamRead,
  TrainingGapRow,
  TrainingGapSummaryRead,
  TrainingGapType,
} from "@/types/workforce";
import { cn } from "@/lib/utils";

export const Route = createFileRoute("/workforce")({
  validateSearch: (search: Record<string, unknown>) => ({
    projectId: typeof search.projectId === "string" ? search.projectId : undefined,
  }),
  component: WorkforcePage,
});

const axis = {
  tick: { fill: "#8b92a5", fontSize: 11 },
  axisLine: { stroke: "#2a2d3a" },
  tickLine: { stroke: "#2a2d3a" },
};
const tip = {
  backgroundColor: "#20242f",
  border: "1px solid #2a2d3a",
  borderRadius: 8,
  fontSize: 12,
  color: "#f0f2f7",
};

const coverageStatusClass = (status: SkillCoverageStatus) =>
  status === "high"
    ? "bg-[color:var(--success)]/20 text-[color:var(--success)]"
    : status === "medium"
      ? "bg-[color:var(--warning)]/20 text-[color:var(--warning)]"
      : "bg-[color:var(--danger)]/20 text-[color:var(--danger)]";

const coverageStatusLabel = (status: SkillCoverageStatus) =>
  status.charAt(0).toUpperCase() + status.slice(1);

const formatProficiency = (level: string) =>
  level.charAt(0).toUpperCase() + level.slice(1);

const siteSummaryFor = (row: SkillMatrixRow, site: DeliverySite) =>
  row.by_site.find((entry) => entry.site === site);

const skillMatrixConfidence = (rows: SkillMatrixRow[]) => {
  if (rows.length === 0) return 0;
  const highCount = rows.filter((row) => row.coverage_status === "high").length;
  return Math.round((highCount / rows.length) * 100);
};

const GAP_TYPE_LABELS: Record<TrainingGapType, string> = {
  mandatory_training_incomplete: "Mandatory incomplete",
  expired_or_failed_training: "Expired/failed training",
  expired_certification: "Expired certification",
  pending_certification_review: "Pending certification review",
};

const gapTypeLabel = (gapType: TrainingGapType) => GAP_TYPE_LABELS[gapType];

const gapRowSubject = (row: TrainingGapRow) =>
  row.training_program_name ?? row.certification_name ?? row.skill_name ?? EMPTY_VALUE;

const trainingGapRowKey = (row: TrainingGapRow, index: number) =>
  [
    row.gap_type,
    row.team_id ?? "none",
    row.training_program_id ?? "none",
    row.certification_id ?? "none",
    row.skill_id ?? "none",
    index,
  ].join(":");

function summarizeTrainingGapsDelta(summary: TrainingGapSummaryRead | undefined): string {
  if (!summary || summary.total_training_gaps === 0) return "No open gaps";
  if (summary.mandatory_training_incomplete > 0) {
    return `${summary.mandatory_training_incomplete} mandatory incomplete`;
  }
  if (summary.expired_or_failed_training > 0) {
    return `${summary.expired_or_failed_training} expired/failed training`;
  }
  if (summary.expired_certifications > 0) {
    return `${summary.expired_certifications} expired certifications`;
  }
  if (summary.pending_certification_reviews > 0) {
    return `${summary.pending_certification_reviews} pending reviews`;
  }
  return "Open gaps detected";
}

const SITE_LABELS: Record<DeliverySite, string> = {
  india: "India",
  kosovo: "Kosovo",
};

const ANNOTATOR_READ_ROLES: ReadonlySet<AppRole> = new Set([
  "delivery_manager",
  "bsg_leadership",
  "super_admin",
]);

function canUserReadAnnotators(role: AppRole | undefined): boolean {
  if (role === undefined) return false;
  return ANNOTATOR_READ_ROLES.has(role);
}

const EMPTY_VALUE = "-";

function PlaceholderPanel({ title, reason }: { title: string; reason: string }) {
  return (
    <div className="rounded-md border border-dashed border-border bg-elevated/50 px-4 py-8 text-center">
      <p className="text-sm font-medium text-muted-foreground">{title}</p>
      <p className="mt-1 text-xs text-muted-foreground">{reason}</p>
    </div>
  );
}

function WorkforcePage() {
  const navigate = useNavigate({ from: "/workforce" });
  const { projectId: urlProjectId } = Route.useSearch();
  const syncedProjectIdRef = useRef<string | null>(null);
  const [view, setView] = useState<"geo" | "matrix">("matrix");

  const user = useAuthStore((state) => state.user);
  const authLoading = useAuthStore((state) => state.isLoading);
  const canReadInternalWorkforce = !authLoading && canUserReadAnnotators(user?.role);

  const projectsQuery = useProjectsQuery();
  const projects = projectsQuery.data ?? [];

  const resolvedProjectId = useMemo(() => {
    if (projects.length === 0) return null;
    if (urlProjectId && projects.some((project) => project.id === urlProjectId)) {
      return urlProjectId;
    }
    return projects[0]?.id ?? null;
  }, [projects, urlProjectId]);

  useEffect(() => {
    if (!resolvedProjectId || resolvedProjectId === urlProjectId) return;
    if (syncedProjectIdRef.current === resolvedProjectId) return;
    syncedProjectIdRef.current = resolvedProjectId;
    navigate({ search: { projectId: resolvedProjectId }, replace: true });
  }, [resolvedProjectId, urlProjectId, navigate]);

  const workforceQuery = useProjectWorkforceSummary(resolvedProjectId, canReadInternalWorkforce);
  const { summary, isLoading: workforceLoading, error: workforceError } = workforceQuery;

  const utilizationQuery = useProjectUtilizationQuery(resolvedProjectId, canReadInternalWorkforce);
  const teamUtilization = useMemo(
    () => buildLatestTeamUtilization(utilizationQuery.data ?? [], summary.teams),
    [utilizationQuery.data, summary.teams],
  );
  const utilizationStats = useMemo(() => summarizeTeamUtilization(teamUtilization), [teamUtilization]);
  const utilizationYAxisMax = useMemo(() => {
    const peak = teamUtilization.reduce((max, point) => Math.max(max, point.value), 0);
    if (peak <= 100) return 100;
    return Math.ceil(peak / 10) * 10 + 10;
  }, [teamUtilization]);
  const siteUtilization = useMemo(() => averageUtilizationBySite(teamUtilization), [teamUtilization]);

  const skillMatrixQuery = useProjectSkillMatrixQuery(resolvedProjectId, canReadInternalWorkforce);
  const skillMatrixRows = skillMatrixQuery.data?.rows ?? [];
  const skillMatrixLoading = canReadInternalWorkforce && skillMatrixQuery.isLoading;
  const skillMatrixError =
    skillMatrixQuery.error instanceof Error ? skillMatrixQuery.error.message : null;
  const skillMatrixConfidencePct = useMemo(
    () => skillMatrixConfidence(skillMatrixRows),
    [skillMatrixRows],
  );

  const trainingGapsQuery = useProjectTrainingGapsQuery(resolvedProjectId, canReadInternalWorkforce);
  const trainingGaps = trainingGapsQuery.data;
  const trainingGapRows = trainingGaps?.rows ?? [];
  const trainingGapsLoading = canReadInternalWorkforce && trainingGapsQuery.isLoading;
  const trainingGapsError =
    trainingGapsQuery.error instanceof Error ? trainingGapsQuery.error.message : null;

  const selectedProject = projects.find((project) => project.id === resolvedProjectId);

  const projectsLoading = projectsQuery.isLoading;
  const utilizationLoading = canReadInternalWorkforce && utilizationQuery.isLoading;

  const errorMessage =
    (projectsQuery.error instanceof Error ? projectsQuery.error.message : null) ??
    workforceError ??
    (utilizationQuery.error instanceof Error ? utilizationQuery.error.message : null);

  const selectProject = (projectId: string) => {
    navigate({ search: { projectId } });
  };

  if (errorMessage) {
    return (
      <Card>
        <SectionHeader title="Workforce & Capability" sub="Unable to load workforce data" />
        <p className="text-sm text-[color:var(--danger)]">{errorMessage}</p>
      </Card>
    );
  }

  if (!projectsLoading && projects.length === 0) {
    return (
      <Card>
        <SectionHeader title="Workforce & Capability" sub="No projects available" />
        <p className="text-sm text-muted-foreground">
          No projects are available for the current user.
        </p>
      </Card>
    );
  }

  const hasTeams = summary.teams.length > 0;
  const smeCoverageValue =
    canReadInternalWorkforce && summary.smeCoveragePct !== null
      ? `${summary.smeCoveragePct}%`
      : EMPTY_VALUE;
  const smeCoverageDelta =
    canReadInternalWorkforce && summary.smeCount > 0
      ? `${summary.smeCount} certified`
      : canReadInternalWorkforce
        ? "No SMEs yet"
        : "Internal only";
  const teamsAtCapacityValue =
    !canReadInternalWorkforce
      ? EMPTY_VALUE
      : utilizationLoading
        ? EMPTY_VALUE
        : utilizationStats.total > 0
          ? `${utilizationStats.overloaded} / ${utilizationStats.total}`
          : EMPTY_VALUE;
  const teamsAtCapacityDelta =
    !canReadInternalWorkforce
      ? "Internal only"
      : utilizationLoading
        ? undefined
        : utilizationStats.total > 0
          ? `${utilizationStats.underutilized} under ${utilizationStats.underutilizedThreshold}%`
          : "No utilization snapshots yet";

  const trainingGapsValue =
    !canReadInternalWorkforce
      ? EMPTY_VALUE
      : trainingGapsLoading
        ? EMPTY_VALUE
        : trainingGaps !== undefined
          ? trainingGaps.total_training_gaps
          : EMPTY_VALUE;
  const trainingGapsDelta =
    !canReadInternalWorkforce
      ? "Internal only"
      : trainingGapsLoading
        ? undefined
        : summarizeTrainingGapsDelta(trainingGaps);
  const trainingGapsTone =
    !canReadInternalWorkforce || trainingGapsLoading
      ? "default"
      : (trainingGaps?.total_training_gaps ?? 0) > 0
        ? "danger"
        : "success";

  return (
    <div className="space-y-5">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="text-xs text-muted-foreground">
          {selectedProject ? (
            <>
              Project focus / <span className="font-medium text-foreground">{selectedProject.name}</span>
            </>
          ) : (
            "Project focus"
          )}
        </div>
        <select
          value={resolvedProjectId ?? ""}
          onChange={(event) => selectProject(event.target.value)}
          disabled={projectsLoading || projects.length === 0}
          className="rounded border border-border bg-card px-2.5 py-1.5 text-xs outline-none"
        >
          {projects.map((project) => (
            <option key={project.id} value={project.id}>
              {project.name}
            </option>
          ))}
        </select>
      </div>

      <div className="grid grid-cols-1 gap-5 lg:grid-cols-5">
        <div className="space-y-5 lg:col-span-3">
          {/* --- Live KPIs (teams + annotators API) --- */}
          <div className="grid grid-cols-2 gap-4 lg:grid-cols-4">
            <KpiCard
              label="Active Annotators"
              value={
                workforceLoading
                  ? EMPTY_VALUE
                  : canReadInternalWorkforce
                    ? summary.activeAnnotatorCount
                    : EMPTY_VALUE
              }
              delta={canReadInternalWorkforce ? undefined : "Internal only"}
              tone={summary.activeAnnotatorCount > 0 ? "success" : "default"}
            />
            <KpiCard
              label="SME Coverage"
              value={workforceLoading ? EMPTY_VALUE : smeCoverageValue}
              delta={workforceLoading ? undefined : smeCoverageDelta}
              tone={
                summary.smeCoveragePct !== null && summary.smeCoveragePct < 50
                  ? "warning"
                  : "default"
              }
            />
            <KpiCard
              label="Teams At Capacity"
              value={teamsAtCapacityValue}
              delta={teamsAtCapacityDelta}
              tone={
                utilizationStats.overloaded > 0
                  ? "warning"
                  : utilizationStats.total > 0
                    ? "success"
                    : "default"
              }
            />
            <KpiCard
              label="Training Gaps"
              value={trainingGapsValue}
              delta={trainingGapsDelta}
              tone={trainingGapsTone}
            />
          </div>

          {/* --- Live: skill coverage matrix (Phase 3) --- */}
          <Card>
            <SectionHeader
              title="Skill Coverage Matrix"
              sub="Required skills vs available project coverage"
              right={
                canReadInternalWorkforce && skillMatrixRows.length > 0 ? (
                  <AiBadge confidence={skillMatrixConfidencePct} />
                ) : undefined
              }
            />
            {!canReadInternalWorkforce ? (
              <PlaceholderPanel
                title="Skill coverage restricted"
                reason="Internal workforce skill coverage is not available to client users."
              />
            ) : skillMatrixLoading ? (
              <div className="space-y-2">
                <div className="h-10 animate-pulse rounded-md bg-elevated" />
                <div className="h-10 animate-pulse rounded-md bg-elevated" />
                <div className="h-10 animate-pulse rounded-md bg-elevated" />
              </div>
            ) : skillMatrixError ? (
              <p className="text-sm text-[color:var(--danger)]">{skillMatrixError}</p>
            ) : skillMatrixRows.length === 0 ? (
              <PlaceholderPanel
                title="No skill requirements yet"
                reason="Add project skill requirements to populate this matrix."
              />
            ) : (
              <div className="overflow-x-auto">
                <table className="w-full text-xs">
                  <thead className="text-left text-muted-foreground">
                    <tr className="border-b border-border">
                      <th className="py-2 pr-3 font-medium">Skill</th>
                      <th className="py-2 pr-3 font-medium">Proficiency</th>
                      <th className="py-2 pr-3 font-medium">Headcount</th>
                      <th className="py-2 pr-3 font-medium">SMEs</th>
                      <th className="py-2 pr-3 font-medium">Status</th>
                      <th className="py-2 pr-3 text-center font-medium">India</th>
                      <th className="py-2 pr-3 text-center font-medium">Kosovo</th>
                    </tr>
                  </thead>
                  <tbody>
                    {skillMatrixRows.map((row) => (
                      <SkillMatrixRowView key={row.skill_id} row={row} />
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </Card>

          {/* --- Live: utilization snapshots (Phase 2) --- */}
          <Card>
            <SectionHeader
              title="Workforce Utilization"
              sub={`By team / ${UTILIZATION_CAPACITY_THRESHOLD}% capacity threshold`}
            />
            {!canReadInternalWorkforce ? (
              <PlaceholderPanel
                title="Utilization data restricted"
                reason="Internal workforce utilization is not available to client users."
              />
            ) : utilizationLoading ? (
              <div className="h-60 animate-pulse rounded-md bg-elevated" />
            ) : teamUtilization.length === 0 ? (
              <PlaceholderPanel
                title="No utilization snapshots yet"
                reason="Add utilization snapshots for project teams to populate this chart."
              />
            ) : (
              <>
                <ResponsiveContainer width="100%" height={240}>
                  <BarChart data={teamUtilization}>
                    <CartesianGrid stroke="#2a2d3a" strokeDasharray="3 3" />
                    <XAxis dataKey="team" {...axis} />
                    <YAxis {...axis} domain={[0, utilizationYAxisMax]} />
                    <Tooltip contentStyle={tip} />
                    <ReferenceLine
                      y={UTILIZATION_CAPACITY_THRESHOLD}
                      stroke="#ef4444"
                      strokeDasharray="4 4"
                    />
                    <Bar dataKey="value" fill="#0D1240" radius={[4, 4, 0, 0]} />
                  </BarChart>
                </ResponsiveContainer>
                <div className="mt-3 flex flex-wrap gap-3 text-[11px] text-muted-foreground">
                  {utilizationStats.overloaded > 0 && (
                    <span className="text-[color:var(--warning)]">
                      {utilizationStats.overloaded} team(s) at or above{" "}
                      {UTILIZATION_CAPACITY_THRESHOLD}%
                    </span>
                  )}
                  {utilizationStats.underutilized > 0 && (
                    <span>
                      {utilizationStats.underutilized} team(s) below{" "}
                      {utilizationStats.underutilizedThreshold}%
                    </span>
                  )}
                </div>
              </>
            )}
          </Card>

          {/* --- Live: team / annotator summary --- */}
          <Card>
            <SectionHeader
              title="Team Summary"
              sub={
                canReadInternalWorkforce
                  ? "Teams with headcount and SME coverage"
                  : "Team structure (annotator details restricted)"
              }
            />
            {workforceLoading ? (
              <div className="space-y-2">
                <div className="h-10 animate-pulse rounded-md bg-elevated" />
                <div className="h-10 animate-pulse rounded-md bg-elevated" />
              </div>
            ) : !hasTeams ? (
              <p className="text-sm text-muted-foreground">
                No teams are configured for this project yet.
              </p>
            ) : (
              <div className="overflow-x-auto">
                <table className="w-full text-xs">
                  <thead className="text-left text-muted-foreground">
                    <tr className="border-b border-border">
                      <th className="py-2 pr-3 font-medium">Team</th>
                      <th className="py-2 pr-3 font-medium">Site</th>
                      <th className="py-2 pr-3 font-medium">Domain</th>
                      <th className="py-2 pr-3 font-medium">Annotators</th>
                      <th className="py-2 pr-3 font-medium">SMEs</th>
                      <th className="py-2 pr-3 font-medium">Status</th>
                    </tr>
                  </thead>
                  <tbody>
                    {summary.teams.map((team) => (
                      <TeamSummaryRow
                        key={team.id}
                        team={team}
                        annotatorCount={
                          canReadInternalWorkforce
                            ? (summary.annotatorsByTeam.get(team.id) ?? []).filter(
                                (annotator) => annotator.is_active,
                              ).length
                            : null
                        }
                        smeCount={
                          canReadInternalWorkforce
                            ? (summary.annotatorsByTeam.get(team.id) ?? []).filter(
                                (annotator) => annotator.is_active && annotator.is_sme_certified,
                              ).length
                            : null
                        }
                      />
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </Card>
        </div>

        <div className="space-y-4 lg:col-span-2">
          {/* --- Live: teams grouped by site --- */}
          <Card>
            <SectionHeader
              title="By Region"
              sub="India / Kosovo"
              right={
                <div className="flex items-center gap-1 rounded-md border border-border bg-elevated p-0.5 text-[11px]">
                  <button
                    onClick={() => setView("geo")}
                    className={cn("rounded px-2 py-0.5", view === "geo" && "bg-card")}
                  >
                    Geographical
                  </button>
                  <button
                    onClick={() => setView("matrix")}
                    className={cn("rounded px-2 py-0.5", view === "matrix" && "bg-card")}
                  >
                    Matrix
                  </button>
                </div>
              }
            />
            {workforceLoading ? (
              <div className="grid grid-cols-2 gap-3">
                <div className="h-28 animate-pulse rounded-md bg-elevated" />
                <div className="h-28 animate-pulse rounded-md bg-elevated" />
              </div>
            ) : !hasTeams ? (
              <p className="text-sm text-muted-foreground">No teams to group by site yet.</p>
            ) : (
              <div className="grid grid-cols-2 gap-3">
                {(["india", "kosovo"] as const).map((site) => {
                  const stats = summary.teamsBySite[site];
                  return (
                    <div key={site} className="rounded-md border border-border bg-elevated p-3">
                      <div className="flex items-center justify-between">
                        <div className="text-sm font-semibold">{SITE_LABELS[site]}</div>
                        <StatusPill status={stats.activeTeams > 0 ? "On Track" : "Warning"} />
                      </div>
                      <dl className="mt-2 space-y-1 text-[11px]">
                        <div className="flex justify-between">
                          <dt className="text-muted-foreground">Teams</dt>
                          <dd className="font-medium">{stats.teams}</dd>
                        </div>
                        <div className="flex justify-between">
                          <dt className="text-muted-foreground">Active teams</dt>
                          <dd className="font-medium">{stats.activeTeams}</dd>
                        </div>
                        <div className="flex justify-between">
                          <dt className="text-muted-foreground">Annotators</dt>
                          <dd className="font-medium">
                            {canReadInternalWorkforce ? stats.annotators : EMPTY_VALUE}
                          </dd>
                        </div>
                        <div className="flex justify-between">
                          <dt className="text-muted-foreground">SMEs</dt>
                          <dd className="font-medium">
                            {canReadInternalWorkforce ? stats.smes : EMPTY_VALUE}
                          </dd>
                        </div>
                        <div className="flex justify-between">
                          <dt className="text-muted-foreground">Utilization</dt>
                          <dd className="font-medium">
                            {!canReadInternalWorkforce
                              ? EMPTY_VALUE
                              : siteUtilization[site] !== null
                                ? `${siteUtilization[site]}%`
                                : "No data"}
                          </dd>
                        </div>
                      </dl>
                    </div>
                  );
                })}
              </div>
            )}
            {view === "matrix" && (
              <div className="mt-4">
                {!canReadInternalWorkforce ? (
                  <PlaceholderPanel
                    title="Regional skill matrix restricted"
                    reason="Internal workforce skill coverage is not available to client users."
                  />
                ) : skillMatrixLoading ? (
                  <div className="h-24 animate-pulse rounded-md bg-elevated" />
                ) : skillMatrixError ? (
                  <p className="text-sm text-[color:var(--danger)]">{skillMatrixError}</p>
                ) : skillMatrixRows.length === 0 ? (
                  <PlaceholderPanel
                    title="No regional skill matrix data"
                    reason="Add project skill requirements to compare India and Kosovo coverage."
                  />
                ) : (
                  <div className="overflow-x-auto">
                    <table className="w-full text-xs">
                      <thead className="text-left text-muted-foreground">
                        <tr className="border-b border-border">
                          <th className="py-2 pr-3 font-medium">Skill</th>
                          <th className="py-2 pr-3 text-center font-medium">India</th>
                          <th className="py-2 pr-3 text-center font-medium">Kosovo</th>
                        </tr>
                      </thead>
                      <tbody>
                        {skillMatrixRows.map((row) => {
                          const india = siteSummaryFor(row, "india");
                          const kosovo = siteSummaryFor(row, "kosovo");
                          return (
                            <tr key={row.skill_id} className="border-b border-border/50">
                              <td className="py-2.5 pr-3 font-medium">{row.skill_name}</td>
                              <td className="py-2.5 pr-3 text-center">
                                {india ? (
                                  <RegionalSiteBadge summary={india} required={row.required_headcount} />
                                ) : (
                                  EMPTY_VALUE
                                )}
                              </td>
                              <td className="py-2.5 pr-3 text-center">
                                {kosovo ? (
                                  <RegionalSiteBadge summary={kosovo} required={row.required_headcount} />
                                ) : (
                                  EMPTY_VALUE
                                )}
                              </td>
                            </tr>
                          );
                        })}
                      </tbody>
                    </table>
                  </div>
                )}
              </div>
            )}
          </Card>

          {/* --- Live: training gaps (Phase 4) --- */}
          <Card>
            <SectionHeader title="Training Gaps" sub="Certification and training coverage gaps" />
            {!canReadInternalWorkforce ? (
              <PlaceholderPanel
                title="Training gaps restricted"
                reason="Internal workforce training and certification gaps are not available to client users."
              />
            ) : trainingGapsLoading ? (
              <div className="space-y-2">
                <div className="h-8 animate-pulse rounded-md bg-elevated" />
                <div className="h-10 animate-pulse rounded-md bg-elevated" />
                <div className="h-10 animate-pulse rounded-md bg-elevated" />
              </div>
            ) : trainingGapsError ? (
              <p className="text-sm text-[color:var(--danger)]">{trainingGapsError}</p>
            ) : (trainingGaps?.total_training_gaps ?? 0) === 0 ? (
              <PlaceholderPanel
                title="No open training gaps"
                reason="Mandatory training, certifications, and training records are current for project teams."
              />
            ) : (
              <>
                <div className="mb-4 flex flex-wrap gap-2">
                  {trainingGaps!.mandatory_training_incomplete > 0 && (
                    <span className="rounded border border-border bg-elevated px-2 py-1 text-[11px] text-muted-foreground">
                      {trainingGaps!.mandatory_training_incomplete} mandatory incomplete
                    </span>
                  )}
                  {trainingGaps!.expired_or_failed_training > 0 && (
                    <span className="rounded border border-border bg-elevated px-2 py-1 text-[11px] text-muted-foreground">
                      {trainingGaps!.expired_or_failed_training} expired/failed training
                    </span>
                  )}
                  {trainingGaps!.expired_certifications > 0 && (
                    <span className="rounded border border-border bg-elevated px-2 py-1 text-[11px] text-muted-foreground">
                      {trainingGaps!.expired_certifications} expired certifications
                    </span>
                  )}
                  {trainingGaps!.pending_certification_reviews > 0 && (
                    <span className="rounded border border-border bg-elevated px-2 py-1 text-[11px] text-muted-foreground">
                      {trainingGaps!.pending_certification_reviews} pending reviews
                    </span>
                  )}
                </div>
                <div className="overflow-x-auto">
                  <table className="w-full text-xs">
                    <thead className="text-left text-muted-foreground">
                      <tr className="border-b border-border">
                        <th className="py-2 pr-3 font-medium">Team</th>
                        <th className="py-2 pr-3 font-medium">Gap</th>
                        <th className="py-2 pr-3 font-medium">Subject</th>
                        <th className="py-2 pr-3 font-medium">Affected</th>
                      </tr>
                    </thead>
                    <tbody>
                      {trainingGapRows.map((row, index) => (
                        <tr key={trainingGapRowKey(row, index)} className="border-b border-border/50">
                          <td className="py-2.5 pr-3 font-medium">
                            {row.team_name ?? EMPTY_VALUE}
                          </td>
                          <td className="py-2.5 pr-3">
                            <span className="inline-block rounded bg-[color:var(--danger)]/10 px-2 py-1 text-[11px] font-medium text-[color:var(--danger)]">
                              {gapTypeLabel(row.gap_type)}
                            </span>
                          </td>
                          <td className="py-2.5 pr-3 text-muted-foreground">{gapRowSubject(row)}</td>
                          <td className="py-2.5 pr-3">{row.affected_count}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </>
            )}
          </Card>
        </div>
      </div>
    </div>
  );
}

function SkillMatrixRowView({ row }: { row: SkillMatrixRow }) {
  const india = siteSummaryFor(row, "india");
  const kosovo = siteSummaryFor(row, "kosovo");
  const domainLabel = row.domain ?? row.category;

  return (
    <tr className="border-b border-border/50">
      <td className="py-2.5 pr-3">
        <div className="font-medium">{row.skill_name}</div>
        {domainLabel ? (
          <div className="text-[11px] text-muted-foreground">{domainLabel}</div>
        ) : null}
      </td>
      <td className="py-2.5 pr-3 text-muted-foreground">
        {formatProficiency(row.required_proficiency_level)}
      </td>
      <td className="py-2.5 pr-3">
        {row.available_headcount} / {row.required_headcount}
      </td>
      <td className="py-2.5 pr-3">
        {row.available_sme_count} / {row.required_sme_count}
      </td>
      <td className="py-2.5 pr-3">
        <span
          className={cn(
            "inline-block rounded px-2.5 py-1 text-[11px] font-medium",
            coverageStatusClass(row.coverage_status),
          )}
        >
          {coverageStatusLabel(row.coverage_status)}
        </span>
      </td>
      <td className="py-2.5 pr-3 text-center">
        {india ? (
          <RegionalSiteBadge summary={india} required={row.required_headcount} />
        ) : (
          EMPTY_VALUE
        )}
      </td>
      <td className="py-2.5 pr-3 text-center">
        {kosovo ? (
          <RegionalSiteBadge summary={kosovo} required={row.required_headcount} />
        ) : (
          EMPTY_VALUE
        )}
      </td>
    </tr>
  );
}

function RegionalSiteBadge({
  summary,
  required,
}: {
  summary: { available_headcount: number; coverage_status: SkillCoverageStatus };
  required: number;
}) {
  return (
    <span
      className={cn(
        "inline-block rounded px-2.5 py-1 text-[11px] font-medium",
        coverageStatusClass(summary.coverage_status),
      )}
      title={`${summary.available_headcount} available / ${required} required`}
    >
      {summary.available_headcount}/{required}
    </span>
  );
}

function TeamSummaryRow({
  team,
  annotatorCount,
  smeCount,
}: {
  team: TeamRead;
  annotatorCount: number | null;
  smeCount: number | null;
}) {
  return (
    <tr className="border-b border-border/50">
      <td className="py-2.5 pr-3 font-medium">{team.name}</td>
      <td className="py-2.5 pr-3 text-muted-foreground">{SITE_LABELS[team.site]}</td>
      <td className="py-2.5 pr-3 text-muted-foreground">{team.domain}</td>
      <td className="py-2.5 pr-3">{annotatorCount ?? EMPTY_VALUE}</td>
      <td className="py-2.5 pr-3">{smeCount ?? EMPTY_VALUE}</td>
      <td className="py-2.5 pr-3">
        <StatusPill status={team.is_active ? "On Track" : "Warning"} />
      </td>
    </tr>
  );
}
