export const queryKeys = {
  projects: ["projects"] as const,
  programs: ["programs"] as const,
  adminProjects: ["admin", "projects"] as const,
  organisations: ["organisations"] as const,
  users: ["users"] as const,
  deliveryPortfolio: ["delivery", "portfolio"] as const,
  towerPulse: ["dashboard", "operational-tower", "pulse"] as const,
  towerEscalations: ["dashboard", "operational-tower", "escalations"] as const,
  towerHealth: ["dashboard", "operational-tower", "health"] as const,
  towerWork: ["dashboard", "operational-tower", "work"] as const,
  towerActivity: ["dashboard", "operational-tower", "activity"] as const,
  executiveSummary: ["dashboard", "executive-summary"] as const,
  deliveryDashboard: (projectId: string) => ["delivery", "dashboard", projectId] as const,
  deliveryConversations: (projectId: string | null) =>
    ["delivery", "conversations", projectId ?? "__portfolio__"] as const,
  projectDeliveryConfidence: (projectId: string) =>
    ["projects", projectId, "delivery-confidence"] as const,
  projectRootCauses: (projectId: string) =>
    ["delivery", "root-causes", "project", projectId] as const,
  rootCauseTrends: (projectId: string | null) =>
    ["delivery", "root-causes", "trends", projectId ?? "__org__"] as const,
  projectDailyActions: (projectId: string) =>
    ["delivery", "daily-actions", projectId] as const,
  projectOperationalBriefing: (projectId: string) =>
    ["delivery", "operational-briefing", projectId] as const,
  clientIntelligenceOverview: (projectId: string, asOf?: string) =>
    ["projects", projectId, "client-intelligence", "overview", asOf ?? "__current__"] as const,
  clientIntelligenceDeliveryConfidenceHistory: (projectId: string) =>
    ["projects", projectId, "client-intelligence", "delivery-confidence-history"] as const,
  clientIntelligenceSummary: ["client-intelligence", "summary"] as const,
  clientIntelligenceMaster: ["client-intelligence", "master"] as const,
  clientIntelligenceCommunications: (projectId: string) =>
    ["client-intelligence", "communications", projectId] as const,
  clientIntelligenceReportHistory: (
    projectId: string,
    status: "all" | "approved" | "sent" = "all",
  ) => ["client-intelligence", "reports", projectId, status] as const,
  clientIntelligenceProjectSummary: (projectId: string) =>
    ["client-intelligence", "summary", "project", projectId] as const,
  clientIntelligenceQueryHistory: (projectId: string) =>
    ["client-intelligence", "queries", projectId] as const,
  clientIntelligenceDashboard: (projectId: string) =>
    ["client-intelligence", "dashboard", projectId] as const,
  clientIntelligenceReportSchedules: (projectId: string) =>
    ["client-intelligence", "report-schedules", projectId] as const,
  clientIntelligenceReportPackages: (projectId: string) =>
    ["client-intelligence", "report-packages", projectId] as const,
  clientIntelligenceReportApprovals: (packageId: string) =>
    ["client-intelligence", "report-approvals", packageId] as const,
  clientIntelligenceReportDeliveries: (packageId: string) =>
    ["client-intelligence", "report-deliveries", packageId] as const,
  projectThroughput: (projectId: string) => ["projects", projectId, "throughput"] as const,
  projectRecommendations: (projectId: string) =>
    ["projects", projectId, "recommendations"] as const,
  projectTeams: (projectId: string) => ["projects", projectId, "teams"] as const,
  projectWorkforceSummary: (projectId: string) =>
    ["projects", projectId, "workforce-summary"] as const,
  projectWorkforceDashboard: (projectId: string) =>
    ["projects", projectId, "workforce-dashboard"] as const,
  projectWorkforceOptimization: (projectId: string) =>
    ["projects", projectId, "workforce-optimization"] as const,
  teamAnnotators: (teamId: string) => ["teams", teamId, "annotators"] as const,
  projectUtilization: (
    projectId: string,
    filters: Record<string, string | number | undefined> = {},
  ) => ["projects", projectId, "utilization", filters] as const,
  workforceSkills: ["workforce", "skills"] as const,
  workforceCertifications: ["workforce", "certifications"] as const,
  workforceTrainingPrograms: ["workforce", "training-programs"] as const,
  annotatorSkills: (annotatorId: string) => ["annotators", annotatorId, "skills"] as const,
  annotatorCertifications: (annotatorId: string) =>
    ["annotators", annotatorId, "certifications"] as const,
  annotatorTrainingRecords: (annotatorId: string) =>
    ["annotators", annotatorId, "training-records"] as const,
  projectSkillRequirements: (projectId: string) =>
    ["projects", projectId, "skill-requirements"] as const,
  projectSkillMatrix: (projectId: string) => ["projects", projectId, "skill-matrix"] as const,
  projectTrainingGaps: (projectId: string) => ["projects", projectId, "training-gaps"] as const,
  projectCapabilityGaps: (projectId: string) => ["projects", projectId, "capability-gaps"] as const,
  governanceBootstrap: ["governance", "bootstrap"] as const,
  governanceWeeklySummary: ["governance", "weekly-summary", "latest"] as const,
  governanceWeeklySummaries: ["governance", "weekly-summary", "history"] as const,
  governanceWeeklySummaryDetail: (summaryId: string | null | undefined) =>
    ["governance", "weekly-summary", "detail", summaryId ?? "__none__"] as const,
  governanceAnalyticsSummary: (
    days: number,
    filters: { projectId?: string | null; vertical?: string | null } = {},
  ) =>
    [
      "governance",
      "analytics",
      "summary",
      days,
      filters.projectId ?? null,
      filters.vertical ?? null,
    ] as const,
  governanceAnalyticsDetail: (
    days: number,
    filters: { projectId?: string | null; vertical?: string | null } = {},
  ) =>
    [
      "governance",
      "analytics",
      "detail",
      days,
      filters.projectId ?? null,
      filters.vertical ?? null,
    ] as const,
  governanceRecommendationEffectivenessSummary: (
    filters: Record<string, string | number | boolean | null | undefined>,
  ) => ["governance", "effectiveness", "summary", filters] as const,
  governanceRecommendationEffectivenessFunnel: (
    filters: Record<string, string | number | boolean | null | undefined>,
  ) => ["governance", "effectiveness", "funnel", filters] as const,
  governanceRecommendationEffectivenessTrends: (
    filters: Record<string, string | number | boolean | null | undefined>,
  ) => ["governance", "effectiveness", "trends", filters] as const,
  governanceRecommendationEffectivenessCategories: (
    kind: "dismissed" | "accepted",
    filters: Record<string, string | number | boolean | null | undefined>,
  ) => ["governance", "effectiveness", kind, filters] as const,
  governanceRecommendationOptimizationSummary: (
    filters: Record<string, string | number | boolean | null | undefined>,
  ) => ["governance", "optimization", "summary", filters] as const,
  governanceRecommendationOptimizationCompare: (
    strategyA: string,
    strategyB: string,
    days: number,
  ) => ["governance", "optimization", "compare", strategyA, strategyB, days] as const,
  governanceDependencies: (params: Record<string, unknown> = {}) =>
    ["governance", "dependencies", params] as const,
  governanceActions: (params: Record<string, unknown> = {}) =>
    ["governance", "actions", params] as const,
  governanceEscalations: (params: Record<string, unknown> = {}) =>
    ["governance", "escalations", params] as const,
  governanceScopeStates: (params: Record<string, unknown> = {}) =>
    ["governance", "scope-states", params] as const,
  governanceRegister: (params: Record<string, unknown> = {}) =>
    ["governance", "register", params] as const,
  governanceProjectSheet: (projectId: string) =>
    ["governance", "project-sheet", projectId] as const,
  governanceProjectCharters: (params: Record<string, unknown> = {}) =>
    ["governance", "project-charters", params] as const,
  governanceProjectChartersPanel: (params: Record<string, unknown> = {}) =>
    ["governance", "project-charters-panel", params] as const,
  governanceProjectCharter: (charterId: string | null | undefined) =>
    ["governance", "project-charter", charterId ?? "__none__"] as const,
  governanceProjectCharterVersions: (charterId: string | null | undefined) =>
    ["governance", "project-charter-versions", charterId ?? "__none__"] as const,
  governanceJobs: (params: Record<string, unknown> = {}) => ["governance", "jobs", params] as const,
  governanceJob: (jobId: string) => ["governance", "jobs", jobId] as const,
  governanceAIRecommendations: (params: Record<string, unknown> = {}) =>
    ["governance", "ai-recommendations", params] as const,
  qualityPage: (projectId: string) => ["quality", "page", projectId] as const,
  knowledgeBootstrap: ["knowledge", "bootstrap"] as const,
  knowledgeDocuments: ["knowledge", "documents"] as const,
  knowledgeConversations: ["knowledge", "conversations"] as const,
  knowledgeDocumentApprovalHistory: (documentId: string) =>
    ["knowledge", "documents", documentId, "approval-history"] as const,
  knowledgeLibraryHealth: ["knowledge", "library-health"] as const,
  knowledgeRelatedDocuments: (documentId: string) =>
    ["knowledge", "documents", documentId, "related"] as const,
  knowledgeRetrievalSettings: ["knowledge", "retrieval-settings"] as const,
  knowledgeDocument: (documentId: string) => ["knowledge", "document", documentId] as const,
  knowledgeDocumentVersions: (documentId: string) =>
    ["knowledge", "document", documentId, "versions"] as const,
  knowledgeAgentQueries: ["knowledge", "agent-queries"] as const,
  communicationsList: (filters: {
    status?: string | null;
    projectId?: string | null;
    limit?: number;
    offset?: number;
  }) =>
    [
      "communications",
      "list",
      filters.status ?? null,
      filters.projectId ?? null,
      filters.limit ?? 30,
      filters.offset ?? 0,
    ] as const,
  communicationDetail: (communicationId: string) =>
    ["communications", "detail", communicationId] as const,
  clientCommunicationsList: (filters: { limit?: number; offset?: number }) =>
    [
      "client-communications",
      "list",
      filters.limit ?? 30,
      filters.offset ?? 0,
    ] as const,
};

export const STALE_TIME_MS = 5 * 60 * 1000;
export const TOWER_STALE_TIME_MS = 60 * 1000;
export const COMMUNICATIONS_LIST_STALE_TIME_MS = 30 * 1000;
export const COMMUNICATIONS_DETAIL_STALE_TIME_MS = 60 * 1000;

export const TOWER_RISK_POLL_MS = 60 * 1000;
export const ADMIN_LIST_GC_TIME_MS = 30 * 60 * 1000;
export const KNOWLEDGE_BOOTSTRAP_STALE_TIME_MS = 10 * 60 * 1000;
export const WORKFORCE_CATALOG_STALE_TIME_MS = 15 * 60 * 1000;
export const WORKFORCE_PROJECT_STALE_TIME_MS = 10 * 60 * 1000;
