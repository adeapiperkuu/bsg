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
};

export const STALE_TIME_MS = 5 * 60 * 1000;
