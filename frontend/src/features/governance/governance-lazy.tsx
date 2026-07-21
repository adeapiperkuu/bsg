import { lazy } from "react";

import { Skeleton } from "@/components/ui/skeleton";

export const LazyExecutiveGovernanceDashboard = lazy(() =>
  import("@/features/governance/ExecutiveGovernanceDashboard").then((module) => ({
    default: module.ExecutiveGovernanceDashboard,
  })),
);

const loadAskGovernanceAgentPanel = () =>
  import("@/features/governance/AskGovernanceAgentPanel").then((module) => ({
    default: module.AskGovernanceAgentPanel,
  }));

const loadProjectChartersPanel = () =>
  import("@/features/governance/ProjectChartersPanel").then((module) => ({
    default: module.ProjectChartersPanel,
  }));

export const LazyAskGovernanceAgentPanel = lazy(loadAskGovernanceAgentPanel);

export const LazyProjectChartersPanel = lazy(loadProjectChartersPanel);

export function preloadProjectChartersPanel() {
  void loadProjectChartersPanel();
}

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

export function ProjectChartersPanelFallback() {
  return (
    <div className="flex h-[640px] flex-col overflow-hidden rounded-lg border border-border bg-card p-5" aria-hidden>
      <div className="mb-4 flex items-start justify-between gap-3">
        <div className="min-w-0 space-y-2">
          <Skeleton className="h-4 w-32" />
          <Skeleton className="h-3 w-80 max-w-full" />
        </div>
        <div className="flex gap-2">
          <Skeleton className="h-8 w-56" />
          <Skeleton className="h-8 w-40" />
        </div>
      </div>
      <div className="flex min-h-0 flex-1 flex-col rounded-md border border-border bg-elevated p-3">
        <div className="mb-3 flex gap-2">
          <Skeleton className="h-5 w-20 rounded-full" />
          <Skeleton className="h-5 w-24 rounded-full" />
          <Skeleton className="h-4 w-36" />
        </div>
        <Skeleton className="mb-2 h-24 w-full" />
        <Skeleton className="min-h-0 flex-1 w-full" />
        <div className="mt-3 flex gap-2">
          <Skeleton className="h-7 w-24" />
          <Skeleton className="h-7 w-14" />
          <Skeleton className="h-7 w-16" />
        </div>
      </div>
    </div>
  );
}
