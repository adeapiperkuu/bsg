import type { DeliveryPortfolioResponse } from "@/lib/api";
import type { DeliveryTrafficLight } from "@/lib/delivery-traffic-light";

export type ClientProjectSummary = {
  id: string;
  name: string;
  confidence: number | null;
  trafficLight: DeliveryTrafficLight;
};

export type ClientPortfolioSummary = {
  confidence: number | null;
  projects: ClientProjectSummary[];
  totalProjects: number;
  onTrackProjects: number;
  atRiskProjects: number;
  waitingForDataProjects: number;
  hasMoreProjects: boolean;
};

function projectName(overview: Record<string, unknown>): string {
  const project = overview.project;
  if (!project || typeof project !== "object") return "Untitled project";
  const name = (project as Record<string, unknown>).name;
  return typeof name === "string" && name.trim() ? name : "Untitled project";
}

export function summarizeClientPortfolio(
  portfolio: DeliveryPortfolioResponse | undefined,
): ClientPortfolioSummary {
  const projects = (portfolio?.projects ?? []).map(({ project_id, dashboard }) => {
    const hasSufficientData = dashboard.overview.has_sufficient_data !== false;
    const confidence =
      hasSufficientData && Number.isFinite(dashboard.confidence)
        ? Math.round(dashboard.confidence)
        : null;

    return {
      id: project_id,
      name: projectName(dashboard.overview),
      confidence,
      trafficLight: dashboard.traffic_light,
    };
  });

  const confidenceValues = projects.flatMap((project) =>
    project.confidence === null ? [] : [project.confidence],
  );
  const confidence = confidenceValues.length
    ? Math.round(
        confidenceValues.reduce((total, value) => total + value, 0) / confidenceValues.length,
      )
    : null;
  const totalProjects = portfolio?.total_count ?? projects.length;

  return {
    confidence,
    projects,
    totalProjects,
    onTrackProjects: projects.filter(
      (project) => project.confidence !== null && project.trafficLight === "green",
    ).length,
    atRiskProjects: projects.filter(
      (project) => project.confidence !== null && project.trafficLight !== "green",
    ).length,
    waitingForDataProjects: projects.filter((project) => project.confidence === null).length,
    hasMoreProjects: totalProjects > projects.length,
  };
}
