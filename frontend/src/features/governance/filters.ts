import type {
  GovernanceAction,
  GovernanceEscalation,
  GovernanceScopeStatus,
  ProjectDependency,
} from "@/types/governance";

export type GovernanceFilters = {
  search: string;
  projectId: string;
  status: string;
  severity: string;
  dependencyType: string;
  ownerId: string;
  assigneeId: string;
  scopeStatus: string;
  dueBefore: string;
};

export const emptyGovernanceFilters = (): GovernanceFilters => ({
  search: "",
  projectId: "all",
  status: "all",
  severity: "all",
  dependencyType: "all",
  ownerId: "all",
  assigneeId: "all",
  scopeStatus: "all",
  dueBefore: "",
});

function matchesSearch(text: string, query: string): boolean {
  if (!query) return true;
  return text.toLowerCase().includes(query.toLowerCase());
}

export function filterDependencies(
  items: ProjectDependency[],
  filters: GovernanceFilters,
): ProjectDependency[] {
  return items.filter((item) => {
    if (filters.projectId !== "all" && item.project_id !== filters.projectId) return false;
    if (filters.status !== "all" && item.status !== filters.status) return false;
    if (filters.dependencyType !== "all" && item.dependency_type !== filters.dependencyType) {
      return false;
    }
    if (filters.ownerId !== "all" && item.owner_id !== filters.ownerId) return false;
    if (filters.dueBefore && item.due_date && item.due_date > filters.dueBefore) return false;
    const haystack = [item.title, item.project_name ?? "", item.owner_name ?? ""].join(" ");
    return matchesSearch(haystack, filters.search);
  });
}

export function filterActions(items: GovernanceAction[], filters: GovernanceFilters): GovernanceAction[] {
  return items.filter((item) => {
    if (filters.projectId !== "all" && item.project_id !== filters.projectId) return false;
    if (filters.status !== "all" && item.status !== filters.status) return false;
    if (filters.ownerId !== "all" && item.owner_id !== filters.ownerId) return false;
    if (filters.dueBefore && item.due_date && item.due_date > filters.dueBefore) return false;
    const haystack = [item.title, item.project_name ?? "", item.owner_name ?? ""].join(" ");
    return matchesSearch(haystack, filters.search);
  });
}

export function filterEscalations(
  items: GovernanceEscalation[],
  filters: GovernanceFilters,
): GovernanceEscalation[] {
  return items.filter((item) => {
    if (filters.projectId !== "all" && item.project_id !== filters.projectId) return false;
    if (filters.status !== "all" && item.status !== filters.status) return false;
    if (filters.severity !== "all" && item.severity !== filters.severity) return false;
    if (filters.assigneeId !== "all" && item.assigned_to !== filters.assigneeId) return false;
    const haystack = [
      item.title,
      item.project_name ?? "",
      item.raised_by_name ?? "",
      item.assigned_to_name ?? "",
    ].join(" ");
    return matchesSearch(haystack, filters.search);
  });
}

export function filterRegisterByScope<
  T extends {
    projectId: string;
    projectName?: string;
    scopeStatus: GovernanceScopeStatus | null;
  },
>(rows: T[], filters: GovernanceFilters): T[] {
  return rows.filter((row) => {
    if (filters.scopeStatus !== "all" && row.scopeStatus !== filters.scopeStatus) return false;
    if (filters.projectId !== "all" && row.projectId !== filters.projectId) return false;
    if (!filters.search) return true;
    const haystack = [row.projectName ?? "", row.projectId].join(" ");
    return matchesSearch(haystack, filters.search);
  });
}
