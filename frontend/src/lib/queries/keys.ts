export const queryKeys = {
  projects: ["projects"] as const,
  organisations: ["organisations"] as const,
  deliveryPortfolio: ["delivery", "portfolio"] as const,
  deliveryDashboard: (projectId: string) => ["delivery", "dashboard", projectId] as const,
  projectDeliveryConfidence: (projectId: string) =>
    ["projects", projectId, "delivery-confidence"] as const,
  projectThroughput: (projectId: string) => ["projects", projectId, "throughput"] as const,
  projectRecommendations: (projectId: string) =>
    ["projects", projectId, "recommendations"] as const,
  projectTeams: (projectId: string) => ["projects", projectId, "teams"] as const,
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
  governanceAnalytics: (days: number) => ["governance", "analytics", days] as const,
};

export const STALE_TIME_MS = 5 * 60 * 1000;
