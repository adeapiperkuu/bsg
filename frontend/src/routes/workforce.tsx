import { createFileRoute, useNavigate } from "@tanstack/react-router";
import { useMutation } from "@tanstack/react-query";
import { useEffect, useMemo, useRef, useState } from "react";
import { Card, SectionHeader } from "@/components/bsg/widgets";
import { EmployeeProfileDrawer } from "@/components/bsg/EmployeeProfileDrawer";
import { CapabilityGapsSection } from "@/components/bsg/workforce/CapabilityGapsSection";
import { RegionalOverviewSection } from "@/components/bsg/workforce/RegionalOverviewSection";
import { SkillCoverageMatrixSection } from "@/components/bsg/workforce/SkillCoverageMatrixSection";
import { TeamSummarySection } from "@/components/bsg/workforce/TeamSummarySection";
import { TrainingGapsSection } from "@/components/bsg/workforce/TrainingGapsSection";
import { WorkforceUtilizationSection } from "@/components/bsg/workforce/WorkforceUtilizationSection";
import { WorkforceAgentSection } from "@/components/bsg/workforce/WorkforceAgentSection";
import { WorkforceKpiStrip } from "@/components/bsg/workforce/WorkforceKpiStrip";
import { WorkforceRecommendationsPanel } from "@/components/bsg/WorkforceRecommendationsPanel";
import {
  createAgentQuery,
} from "@/lib/api";
import { useProjectsQuery } from "@/lib/queries/delivery";
import {
  UTILIZATION_CAPACITY_THRESHOLD,
  buildLatestTeamUtilization,
  useProjectCapabilityGapsQuery,
  useProjectSkillMatrixQuery,
  useProjectTrainingGapsQuery,
  useProjectUtilizationQuery,
  useProjectWorkforceSummary,
} from "@/lib/queries/workforce";
import {
  useWorkforceDashboardFilters,
  WORKFORCE_ALL_SITES,
  type WorkforceSiteFilter,
} from "@/hooks/useWorkforceDashboardFilters";
import { useWorkforceCapabilityGapActions } from "@/hooks/useWorkforceCapabilityGapActions";
import {
  SITE_LABELS,
  WORKFORCE_EMPTY_VALUE,
} from "@/lib/workforceLabels";
import {
  canManageWorkforce as canManageWorkforceRole,
  canReadInternalWorkforce as canReadInternalWorkforceRole,
} from "@/lib/workforcePermissions";
import { useAuthStore } from "@/stores/useAuthStore";
import type {
  AgentQueryRead,
  AnnotatorRead,
  SkillMatrixRow,
  TrainingGapRow,
  TrainingGapSummaryRead,
} from "@/types/workforce";

export const Route = createFileRoute("/workforce")({
  validateSearch: (search: Record<string, unknown>) => ({
    projectId: typeof search.projectId === "string" ? search.projectId : undefined,
  }),
  component: WorkforcePage,
});

const skillMatrixConfidence = (rows: SkillMatrixRow[]) => {
  if (rows.length === 0) return 0;
  const highCount = rows.filter((row) => row.coverage_status === "high").length;
  return Math.round((highCount / rows.length) * 100);
};

const gapRowSubject = (row: TrainingGapRow) =>
  row.training_program_name ?? row.certification_name ?? row.skill_name ?? WORKFORCE_EMPTY_VALUE;

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

const EMPTY_LIST: never[] = [];

const WORKFORCE_AGENT_NAME = "workforce_capability_agent";

const WORKFORCE_STARTER_QUESTIONS = [
  "Which teams are overloaded?",
  "Do we have enough SME coverage?",
  "What are the biggest capability gaps?",
  "Which skills are missing for this project?",
  "Are training gaps creating risk?",
];

function WorkforcePage() {
  const navigate = useNavigate({ from: "/workforce" });
  const { projectId: urlProjectId } = Route.useSearch();
  const syncedProjectIdRef = useRef<string | null>(null);
  const [view, setView] = useState<"geo" | "matrix">("matrix");
  const [showSkillRequirementsManager, setShowSkillRequirementsManager] = useState(false);
  const [showUtilizationManager, setShowUtilizationManager] = useState(false);

  const user = useAuthStore((state) => state.user);
  const authLoading = useAuthStore((state) => state.isLoading);
  const canReadInternalWorkforce = !authLoading && canReadInternalWorkforceRole(user?.role);

  const projectsQuery = useProjectsQuery();
  const projects = projectsQuery.data ?? EMPTY_LIST;

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

  useEffect(() => {
    setShowSkillRequirementsManager(false);
    setShowUtilizationManager(false);
  }, [resolvedProjectId]);

  const workforceQuery = useProjectWorkforceSummary(resolvedProjectId, canReadInternalWorkforce);
  const { summary, isLoading: workforceLoading, error: workforceError } = workforceQuery;

  const utilizationQuery = useProjectUtilizationQuery(resolvedProjectId, canReadInternalWorkforce);
  const teamUtilization = useMemo(
    () => buildLatestTeamUtilization(utilizationQuery.data ?? [], summary.teams),
    [utilizationQuery.data, summary.teams],
  );
  const skillMatrixQuery = useProjectSkillMatrixQuery(resolvedProjectId, canReadInternalWorkforce);
  const skillMatrixRows = skillMatrixQuery.data?.rows ?? EMPTY_LIST;
  const skillMatrixLoading = canReadInternalWorkforce && skillMatrixQuery.isLoading;
  const skillMatrixError =
    skillMatrixQuery.error instanceof Error ? skillMatrixQuery.error.message : null;
  const skillMatrixConfidencePct = useMemo(
    () => skillMatrixConfidence(skillMatrixRows),
    [skillMatrixRows],
  );

  const trainingGapsQuery = useProjectTrainingGapsQuery(resolvedProjectId, canReadInternalWorkforce);
  const trainingGaps = trainingGapsQuery.data;
  const trainingGapRows = trainingGaps?.rows ?? EMPTY_LIST;
  const trainingGapsLoading = canReadInternalWorkforce && trainingGapsQuery.isLoading;
  const trainingGapsError =
    trainingGapsQuery.error instanceof Error ? trainingGapsQuery.error.message : null;

  const canManageWorkforce = canManageWorkforceRole(user?.role);

  const capabilityGapsQuery = useProjectCapabilityGapsQuery(
    resolvedProjectId,
    canReadInternalWorkforce,
  );
  const capabilityGaps = capabilityGapsQuery.data ?? EMPTY_LIST;
  const capabilityGapsLoading = canReadInternalWorkforce && capabilityGapsQuery.isLoading;
  const capabilityGapsError =
    capabilityGapsQuery.error instanceof Error ? capabilityGapsQuery.error.message : null;

  const {
    siteFilter,
    setSiteFilter,
    domainFilter,
    setDomainFilter,
    categoryFilter,
    setCategoryFilter,
    domainOptions,
    categoryOptions,
    filteredTeams,
    filteredTeamUtilization,
    filteredUtilizationStats,
    filteredUtilizationYAxisMax,
    filteredSiteUtilization,
    visibleSites,
    utilizationTrend,
    filteredSkillMatrixRows,
    filteredTrainingGapRows,
    filteredCapabilityGaps,
    filteredCapabilityGapsSummary,
  } = useWorkforceDashboardFilters({
    projectId: resolvedProjectId,
    teams: summary.teams,
    skillMatrixRows,
    teamUtilization,
    utilizationSnapshots: utilizationQuery.data ?? [],
    trainingGapRows,
    capabilityGaps,
  });

  const {
    detectMessage,
    recommendMessage,
    actionError,
    updatingGapId,
    detectGapsMutation,
    generateRecommendationsMutation,
    triggerDetectGaps,
    triggerGenerateRecommendations,
    handleGapStatusUpdate,
  } = useWorkforceCapabilityGapActions(resolvedProjectId);

  const [expandedTeams, setExpandedTeams] = useState<Set<string>>(() => new Set());
  const [selectedAnnotator, setSelectedAnnotator] = useState<AnnotatorRead | null>(null);
  const [drawerOpen, setDrawerOpen] = useState(false);

  const toggleTeamExpanded = (teamId: string) => {
    setExpandedTeams((prev) => {
      const next = new Set(prev);
      if (next.has(teamId)) {
        next.delete(teamId);
      } else {
        next.add(teamId);
      }
      return next;
    });
  };

  const openAnnotatorProfile = (annotator: AnnotatorRead) => {
    setSelectedAnnotator(annotator);
    setDrawerOpen(true);
  };

  const selectedAnnotatorTeam = selectedAnnotator
    ? summary.teams.find((team) => team.id === selectedAnnotator.team_id)
    : undefined;

  const [agentQuestion, setAgentQuestion] = useState("");
  const [agentAnswer, setAgentAnswer] = useState<AgentQueryRead | null>(null);
  const agentQueryMutation = useMutation({
    mutationFn: (question: string) =>
      createAgentQuery({
        agent_name: WORKFORCE_AGENT_NAME,
        project_id: resolvedProjectId,
        query_text: question,
      }),
    onSuccess: (result) => {
      setAgentAnswer(result);
    },
  });

  const submitAgentQuestion = (question: string) => {
    const trimmed = question.trim();
    if (!trimmed || !resolvedProjectId) return;
    setAgentAnswer(null);
    agentQueryMutation.mutate(trimmed);
  };

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
      : WORKFORCE_EMPTY_VALUE;
  const smeCoverageDelta =
    canReadInternalWorkforce && summary.smeCount > 0
      ? `${summary.smeCount} certified`
      : canReadInternalWorkforce
        ? "No SMEs yet"
        : "Internal only";
  const teamsAtCapacityValue =
    !canReadInternalWorkforce
      ? WORKFORCE_EMPTY_VALUE
      : utilizationLoading
        ? WORKFORCE_EMPTY_VALUE
        : filteredUtilizationStats.total > 0
          ? `${filteredUtilizationStats.overloaded} / ${filteredUtilizationStats.total}`
          : WORKFORCE_EMPTY_VALUE;
  const teamsAtCapacityDelta =
    !canReadInternalWorkforce
      ? "Internal only"
      : utilizationLoading
        ? undefined
        : filteredUtilizationStats.total > 0
          ? `${filteredUtilizationStats.underutilized} under ${filteredUtilizationStats.underutilizedThreshold}%`
          : "No utilization snapshots yet";

  const trainingGapsValue =
    !canReadInternalWorkforce
      ? WORKFORCE_EMPTY_VALUE
      : trainingGapsLoading
        ? WORKFORCE_EMPTY_VALUE
        : trainingGaps !== undefined
          ? trainingGaps.total_training_gaps
          : WORKFORCE_EMPTY_VALUE;
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
        <div className="flex flex-wrap items-center gap-2">
          {canReadInternalWorkforce && (
            <>
              <select
                value={siteFilter}
                onChange={(event) => setSiteFilter(event.target.value as WorkforceSiteFilter)}
                className="rounded border border-border bg-card px-2.5 py-1.5 text-xs outline-none"
              >
                <option value="all">All sites</option>
                {WORKFORCE_ALL_SITES.map((site) => (
                  <option key={site} value={site}>{SITE_LABELS[site]}</option>
                ))}
              </select>
              <select
                value={domainFilter}
                onChange={(event) => setDomainFilter(event.target.value)}
                className="rounded border border-border bg-card px-2.5 py-1.5 text-xs outline-none"
              >
                <option value="all">All domains</option>
                {domainOptions.map((domain) => (
                  <option key={domain} value={domain}>{domain}</option>
                ))}
              </select>
              <select
                value={categoryFilter}
                onChange={(event) => setCategoryFilter(event.target.value)}
                className="rounded border border-border bg-card px-2.5 py-1.5 text-xs outline-none"
              >
                <option value="all">All skills</option>
                {categoryOptions.map((category) => (
                  <option key={category} value={category}>{category}</option>
                ))}
              </select>
            </>
          )}
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
      </div>

      <div className="grid grid-cols-1 gap-5 lg:grid-cols-5">
        <div className="space-y-5 lg:col-span-3">
          {/* --- Live KPIs (teams + annotators API) --- */}
          <WorkforceKpiStrip
            workforceLoading={workforceLoading}
            canReadInternalWorkforce={canReadInternalWorkforce}
            activeAnnotatorCount={summary.activeAnnotatorCount}
            smeCoverageValue={smeCoverageValue}
            smeCoverageDelta={smeCoverageDelta}
            smeCoveragePct={summary.smeCoveragePct}
            teamsAtCapacityValue={teamsAtCapacityValue}
            teamsAtCapacityDelta={teamsAtCapacityDelta}
            teamsAtCapacityOverloaded={filteredUtilizationStats.overloaded}
            teamsAtCapacityTotal={filteredUtilizationStats.total}
            trainingGapsValue={trainingGapsValue}
            trainingGapsDelta={trainingGapsDelta}
            trainingGapsTone={trainingGapsTone}
          />

          <SkillCoverageMatrixSection
            canReadInternalWorkforce={canReadInternalWorkforce}
            canManageWorkforce={canManageWorkforce}
            resolvedProjectId={resolvedProjectId}
            skillMatrixRows={skillMatrixRows}
            filteredSkillMatrixRows={filteredSkillMatrixRows}
            skillMatrixLoading={skillMatrixLoading}
            skillMatrixError={skillMatrixError}
            skillMatrixConfidencePct={skillMatrixConfidencePct}
            visibleSites={visibleSites}
            showSkillRequirementsManager={showSkillRequirementsManager}
            onToggleSkillRequirementsManager={() =>
              setShowSkillRequirementsManager((value) => !value)
            }
          />

          <WorkforceUtilizationSection
            canReadInternalWorkforce={canReadInternalWorkforce}
            canManageWorkforce={canManageWorkforce}
            resolvedProjectId={resolvedProjectId}
            utilizationLoading={utilizationLoading}
            teamUtilization={teamUtilization}
            filteredTeamUtilization={filteredTeamUtilization}
            filteredUtilizationStats={filteredUtilizationStats}
            filteredUtilizationYAxisMax={filteredUtilizationYAxisMax}
            utilizationTrend={utilizationTrend}
            showUtilizationManager={showUtilizationManager}
            onToggleUtilizationManager={() => setShowUtilizationManager((value) => !value)}
            teams={summary.teams}
            capacityThreshold={UTILIZATION_CAPACITY_THRESHOLD}
          />

          <CapabilityGapsSection
            canReadInternalWorkforce={canReadInternalWorkforce}
            canManageWorkforce={canManageWorkforce}
            resolvedProjectId={resolvedProjectId}
            capabilityGapsLoading={capabilityGapsLoading}
            capabilityGapsError={capabilityGapsError}
            capabilityGaps={capabilityGaps}
            filteredCapabilityGaps={filteredCapabilityGaps}
            filteredCapabilityGapsSummary={filteredCapabilityGapsSummary}
            detectMessage={detectMessage}
            recommendMessage={recommendMessage}
            actionError={actionError}
            updatingGapId={updatingGapId}
            detectGapsMutation={detectGapsMutation}
            generateRecommendationsMutation={generateRecommendationsMutation}
            triggerDetectGaps={triggerDetectGaps}
            triggerGenerateRecommendations={triggerGenerateRecommendations}
            handleGapStatusUpdate={handleGapStatusUpdate}
          />

          {canReadInternalWorkforce ? (
            <WorkforceRecommendationsPanel
              projectId={resolvedProjectId}
              canManage={canManageWorkforce}
            />
          ) : null}

          <TeamSummarySection
            workforceLoading={workforceLoading}
            hasTeams={hasTeams}
            canReadInternalWorkforce={canReadInternalWorkforce}
            annotatorsByTeam={summary.annotatorsByTeam}
            filteredTeams={filteredTeams}
            expandedTeams={expandedTeams}
            onToggleTeam={toggleTeamExpanded}
            onSelectAnnotator={openAnnotatorProfile}
          />
        </div>

        <div className="space-y-5 lg:col-span-2">
          <RegionalOverviewSection
            view={view}
            onViewChange={setView}
            workforceLoading={workforceLoading}
            hasTeams={hasTeams}
            filteredTeams={filteredTeams}
            summary={summary}
            canReadInternalWorkforce={canReadInternalWorkforce}
            filteredSiteUtilization={filteredSiteUtilization}
            visibleSites={visibleSites}
            skillMatrixLoading={skillMatrixLoading}
            skillMatrixError={skillMatrixError}
            skillMatrixRows={skillMatrixRows}
            filteredSkillMatrixRows={filteredSkillMatrixRows}
          />

          <TrainingGapsSection
            canReadInternalWorkforce={canReadInternalWorkforce}
            trainingGapsLoading={trainingGapsLoading}
            trainingGapsError={trainingGapsError}
            trainingGaps={trainingGaps}
            filteredTrainingGapRows={filteredTrainingGapRows}
            trainingGapRowKey={trainingGapRowKey}
            gapRowSubject={gapRowSubject}
          />

          <WorkforceAgentSection
            canReadInternalWorkforce={canReadInternalWorkforce}
            resolvedProjectId={resolvedProjectId}
            starterQuestions={WORKFORCE_STARTER_QUESTIONS}
            agentQuestion={agentQuestion}
            onAgentQuestionChange={setAgentQuestion}
            submitAgentQuestion={submitAgentQuestion}
            agentQueryMutation={agentQueryMutation}
            agentAnswer={agentAnswer}
          />
        </div>
      </div>

      {canReadInternalWorkforce ? (
        <EmployeeProfileDrawer
          open={drawerOpen}
          onOpenChange={setDrawerOpen}
          annotator={selectedAnnotator}
          team={selectedAnnotatorTeam}
          projectId={resolvedProjectId}
          canManage={canManageWorkforce}
          canRead={canReadInternalWorkforce}
        />
      ) : null}
    </div>
  );
}
