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
import { skillMatrix } from "@/lib/bsg/data";
import { useProjectsQuery } from "@/lib/queries/delivery";
import {
  UTILIZATION_CAPACITY_THRESHOLD,
  averageUtilizationBySite,
  buildLatestTeamUtilization,
  summarizeTeamUtilization,
  useProjectUtilizationQuery,
  useProjectWorkforceSummary,
} from "@/lib/queries/workforce";
import { useAuthStore } from "@/stores/useAuthStore";
import type { AppRole } from "@/types/auth";
import type { DeliverySite, TeamRead } from "@/types/workforce";
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

const coverageColor = (v: string) =>
  v === "High"
    ? "bg-[color:var(--success)]/20 text-[color:var(--success)]"
    : v === "Medium"
      ? "bg-[color:var(--warning)]/20 text-[color:var(--warning)]"
      : "bg-[color:var(--danger)]/20 text-[color:var(--danger)]";

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
              value={EMPTY_VALUE}
              delta="Pending backend"
              tone="default"
            />
          </div>

          {/* --- Placeholder: skill matrix (Phase 3) --- */}
          <Card>
            <SectionHeader
              title="Skill Coverage Matrix"
              sub="Domains x regions"
              right={<AiBadge confidence={85} />}
            />
            <PlaceholderPanel
              title="Skill coverage not connected yet"
              reason="Skills taxonomy and matrix APIs are planned for Phase 3."
            />
            <div className="mt-4 overflow-x-auto opacity-40">
              <table className="w-full text-xs">
                <thead>
                  <tr className="text-muted-foreground">
                    <th className="py-2 pr-3 text-left font-medium">Domain</th>
                    <th className="py-2 pr-3 text-center font-medium">India</th>
                    <th className="py-2 pr-3 text-center font-medium">Kosovo</th>
                  </tr>
                </thead>
                <tbody>
                  {skillMatrix.map((s) => (
                    <tr key={s.domain} className="border-t border-border/50">
                      <td className="py-2.5 pr-3 font-medium">{s.domain}</td>
                      <td className="py-2.5 pr-3 text-center">
                        <span
                          className={cn(
                            "inline-block rounded px-2.5 py-1 text-[11px] font-medium",
                            coverageColor(s.India),
                          )}
                        >
                          {s.India}
                        </span>
                      </td>
                      <td className="py-2.5 pr-3 text-center">
                        <span
                          className={cn(
                            "inline-block rounded px-2.5 py-1 text-[11px] font-medium",
                            coverageColor(s.Kosovo),
                          )}
                        >
                          {s.Kosovo}
                        </span>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
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
                <PlaceholderPanel
                  title="Regional skill matrix preview"
                  reason="Skill coverage by site requires Phase 3 skills data."
                />
              </div>
            )}
          </Card>

          {/* --- Placeholder: training gaps (Phase 4) --- */}
          <Card>
            <SectionHeader title="Training Gaps" />
            <PlaceholderPanel
              title="Training tracking not connected yet"
              reason="Training programs and records are planned for Phase 4."
            />
          </Card>
        </div>
      </div>
    </div>
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
