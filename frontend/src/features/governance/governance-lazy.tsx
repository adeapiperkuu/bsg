import { lazy } from "react";

import { Skeleton } from "@/components/ui/skeleton";

export const LazyExecutiveGovernanceDashboard = lazy(() =>
  import("@/features/governance/ExecutiveGovernanceDashboard").then((module) => ({
    default: module.ExecutiveGovernanceDashboard,
  })),
);

export const LazyAskGovernanceAgentPanel = lazy(() =>
  import("@/features/governance/AskGovernanceAgentPanel").then((module) => ({
    default: module.AskGovernanceAgentPanel,
  })),
);

export const LazyProjectChartersPanel = lazy(() =>
  import("@/features/governance/ProjectChartersPanel").then((module) => ({
    default: module.ProjectChartersPanel,
  })),
);

export const LazyGovernanceWorkflowDialogs = lazy(() =>
  import("@/features/governance/GovernanceWorkflowDialogs").then((module) => ({
    default: module.GovernanceWorkflowDialogs,
  })),
);

export function ExecutiveDashboardFallback() {
  return (
    <div className="space-y-3 rounded-md border border-border bg-card p-4" aria-hidden>
      <Skeleton className="h-4 w-56" />
      <div className="grid gap-4 xl:grid-cols-[1fr_1fr]">
        <Skeleton className="h-48 w-full" />
        <Skeleton className="h-48 w-full" />
      </div>
    </div>
  );
}

export function GovernanceToolsPanelFallback() {
  return (
    <div className="rounded-md border border-border bg-card p-4" aria-hidden>
      <Skeleton className="h-4 w-40" />
      <Skeleton className="mt-3 h-24 w-full" />
    </div>
  );
}
