export const queryKeys = {
  projects: ["projects"] as const,
  organisations: ["organisations"] as const,
  deliveryPortfolio: ["delivery", "portfolio"] as const,
  deliveryDashboard: (projectId: string) => ["delivery", "dashboard", projectId] as const,
  deliveryConversations: (projectId: string | null) =>
    ["delivery", "conversations", projectId ?? "__portfolio__"] as const,
  projectDeliveryConfidence: (projectId: string) =>
    ["projects", projectId, "delivery-confidence"] as const,
  projectThroughput: (projectId: string) => ["projects", projectId, "throughput"] as const,
  projectRecommendations: (projectId: string) =>
    ["projects", projectId, "recommendations"] as const,
  projectTeams: (projectId: string) => ["projects", projectId, "teams"] as const,
  projectWorkforceSummary: (projectId: string) =>
    ["projects", projectId, "workforce-summary"] as const,
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
};

export const STALE_TIME_MS = 5 * 60 * 1000;
export const KNOWLEDGE_BOOTSTRAP_STALE_TIME_MS = 10 * 60 * 1000;
