import { keepPreviousData, useQuery, useQueryClient } from "@tanstack/react-query";
import { useMemo, useState } from "react";
import { AlertCircle, FileText, Plus, RefreshCw } from "lucide-react";
import { toast } from "sonner";

import { Card, KpiCard, SectionHeader, StatusPill } from "@/components/bsg/widgets";
import { PageLoadingScreen } from "@/components/bsg/PageLoadingScreen";
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from "@/components/ui/alert-dialog";
import { Button } from "@/components/ui/button";
import { GovernanceFiltersBar } from "@/features/governance/GovernanceFiltersBar";
import { ProjectChartersPanel } from "@/features/governance/ProjectChartersPanel";
import { ProjectGovernanceSheet } from "@/features/governance/ProjectGovernanceSheet";
import {
  GovernanceWorkflowDialogs,
  type WorkflowDialogState,
} from "@/features/governance/GovernanceWorkflowDialogs";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import {
  emptyGovernanceFilters,
  filterActions,
  filterDependencies,
  filterEscalations,
  filterRegisterByScope,
} from "@/features/governance/filters";
import { listUsers } from "@/lib/api";
import {
  actionsDueThisWeek,
  buildGovernanceRegister,
  dependencyRowClass,
  escalationRowClass,
  formatActionStatus,
  formatDate,
  formatDependencyStatus,
  formatDependencyType,
  formatEscalationSeverity,
  formatEscalationStatus,
  isOverdueAction,
  type GovernanceRegisterRow,
} from "@/lib/governance-utils";
import { deliveryPortfolioQueryOptions, projectsQueryOptions } from "@/lib/queries/delivery";
import {
  createGovernanceAction,
  createGovernanceEscalation,
  createProjectDependency,
  deleteDependency,
  deleteGovernanceAction,
  deleteGovernanceEscalation,
  governanceBootstrapQueryOptions,
  promoteRiskAlertToEscalation,
  resolveDependency,
  updateDependency,
  updateGovernanceAction,
  updateGovernanceEscalation,
  updateProjectScope,
} from "@/lib/queries/governance";
import { cn } from "@/lib/utils";
import { useAuthStore } from "@/stores/useAuthStore";
import type { AppRole } from "@/types/auth";
import type {
  GovernanceAction,
  GovernanceBootstrap,
  GovernanceDependencyType,
  GovernanceEscalation,
  GovernanceEscalationSeverity,
  GovernanceEscalationSourceType,
  GovernanceScopeStatus,
  ProjectDependency,
} from "@/types/governance";

const OPEN_ACTION_STATUSES = new Set(["open", "in_progress", "overdue"]);
const OPEN_ESCALATION_STATUSES = new Set(["open", "in_progress"]);
const TABLE_PAGE_SIZE = 6;
const GOVERNANCE_TABLE_VIEWPORT_CLASS = "governance-table-shell h-[258px]";

type GovernanceTableTab = "dependencies" | "actions" | "register" | "escalations";

function getPageCount(totalRows: number): number {
  return Math.max(1, Math.ceil(totalRows / TABLE_PAGE_SIZE));
}

function getSafePage(page: number, totalRows: number): number {
  return Math.min(Math.max(page, 1), getPageCount(totalRows));
}

function paginateRows<T>(rows: T[], page: number): T[] {
  const safePage = getSafePage(page, rows.length);
  const start = (safePage - 1) * TABLE_PAGE_SIZE;
  return rows.slice(start, start + TABLE_PAGE_SIZE);
}

function calculateSlaAdherence(actions: GovernanceAction[]): number {
  const windowStart = new Date();
  windowStart.setDate(windowStart.getDate() - 90);
  const recentCompleted = actions.filter((action) => {
    if (action.status !== "completed" || !action.completed_at) return false;
    return new Date(action.completed_at) >= windowStart;
  });
  if (recentCompleted.length === 0) return 100;
  const onTime = recentCompleted.filter((action) => {
    if (!action.due_date || !action.completed_at) return true;
    return (
      new Date(action.completed_at).getTime() <= new Date(`${action.due_date}T23:59:59`).getTime()
    );
  }).length;
  return Math.round((onTime / recentCompleted.length) * 1000) / 10;
}

function recalculateBootstrapKpis(data: GovernanceBootstrap): GovernanceBootstrap {
  const openActions = data.actions.filter((action) => OPEN_ACTION_STATUSES.has(action.status));
  const openEscalations = data.escalations.filter((esc) =>
    OPEN_ESCALATION_STATUSES.has(esc.status),
  );
  const blockingDependencies = data.dependencies.filter((dep) => dep.status === "blocking");
  const pendingScopes = data.scope_states.filter(
    (scope) => scope.scope_status === "pending_revision",
  );
  const highOpenEscalations = data.escalations.filter(
    (esc) => esc.status !== "resolved" && (esc.severity === "high" || esc.severity === "critical"),
  );

  return {
    ...data,
    kpis: {
      open_actions: openActions.length,
      overdue_actions: data.actions.filter((action) => isOverdueAction(action)).length,
      open_escalations: openEscalations.length,
      blocking_dependencies: blockingDependencies.length,
      at_risk_items:
        blockingDependencies.length + pendingScopes.length + highOpenEscalations.length,
      sla_adherence_pct: calculateSlaAdherence(data.actions),
    },
  };
}

function replaceOrAddById<T extends { id: string }>(rows: T[], next: T): T[] {
  return rows.some((row) => row.id === next.id)
    ? rows.map((row) => (row.id === next.id ? next : row))
    : [next, ...rows];
}

function canWriteGovernance(role: AppRole | undefined): boolean {
  return role === "delivery_manager" || role === "super_admin";
}

function canSeeDeliveryContext(role: AppRole | undefined): boolean {
  return role !== "client";
}

function deliveryTrafficLabel(value: "green" | "yellow" | "red" | null): string {
  if (value === "green") return "On Track";
  if (value === "yellow") return "At Risk";
  if (value === "red") return "Critical";
  return "—";
}

type ConfirmState = {
  kind:
    | "resolve-dependency"
    | "resolve-escalation"
    | "complete-action"
    | "delete-dependency"
    | "delete-escalation"
    | "delete-action";
  id: string;
  label: string;
} | null;

function EmptyRow({ colSpan, message }: { colSpan: number; message: string }) {
  return (
    <tr>
      <td colSpan={colSpan} className="py-8 text-center text-sm text-muted-foreground">
        {message}
      </td>
    </tr>
  );
}

function SectionError({ message, onRetry }: { message: string; onRetry: () => void }) {
  return (
    <div className="flex flex-col items-center justify-center gap-3 py-10 text-center">
      <AlertCircle className="h-8 w-8 text-[color:var(--danger)]" />
      <p className="max-w-md text-sm text-muted-foreground">{message}</p>
      <Button type="button" variant="outline" size="sm" className="shadow-none" onClick={onRetry}>
        <RefreshCw className="h-4 w-4" />
        Retry
      </Button>
    </div>
  );
}

function RowActions({
  canWrite,
  onEdit,
  onResolve,
  onDelete,
  showResolve,
  resolveLabel = "Resolve",
}: {
  canWrite: boolean;
  onEdit: () => void;
  onResolve?: () => void;
  onDelete?: () => void;
  showResolve?: boolean;
  resolveLabel?: string;
}) {
  if (!canWrite) return null;
  return (
    <div className="flex gap-1">
      <button
        type="button"
        className="rounded border border-border px-2 py-0.5 text-[10px]"
        onClick={onEdit}
      >
        Edit
      </button>
      {showResolve && onResolve && (
        <button
          type="button"
          className="rounded border border-border px-2 py-0.5 text-[10px]"
          onClick={onResolve}
        >
          {resolveLabel}
        </button>
      )}
      {onDelete && (
        <button
          type="button"
          className="rounded border border-destructive/40 px-2 py-0.5 text-[10px] text-destructive"
          onClick={onDelete}
        >
          Archive
        </button>
      )}
    </div>
  );
}

function TablePagination({
  page,
  totalRows,
  onPageChange,
}: {
  page: number;
  totalRows: number;
  onPageChange: (page: number) => void;
}) {
  if (totalRows <= TABLE_PAGE_SIZE) return null;

  const safePage = getSafePage(page, totalRows);
  const totalPages = getPageCount(totalRows);
  const startRow = (safePage - 1) * TABLE_PAGE_SIZE + 1;
  const endRow = Math.min(safePage * TABLE_PAGE_SIZE, totalRows);

  return (
    <div className="mt-3 flex flex-wrap items-center justify-between gap-2 border-t border-border pt-3 text-[11px] text-muted-foreground">
      <span>
        Showing {startRow}-{endRow} of {totalRows}
      </span>
      <div className="flex items-center gap-2">
        <Button
          type="button"
          size="sm"
          variant="outline"
          className="h-7 px-2 text-[11px] shadow-none"
          disabled={safePage <= 1}
          onClick={() => onPageChange(safePage - 1)}
        >
          Previous
        </Button>
        <span>
          Page {safePage} of {totalPages}
        </span>
        <Button
          type="button"
          size="sm"
          variant="outline"
          className="h-7 px-2 text-[11px] shadow-none"
          disabled={safePage >= totalPages}
          onClick={() => onPageChange(safePage + 1)}
        >
          Next
        </Button>
      </div>
    </div>
  );
}

export function GovernanceDashboard() {
  const queryClient = useQueryClient();
  const user = useAuthStore((state) => state.user);
  const role = user?.role;
  const canWrite = canWriteGovernance(role);
  const showDelivery = canSeeDeliveryContext(role);
  const isClient = role === "client";
  const isReadOnly = role === "bsg_leadership";

  const bootstrapQuery = useQuery({
    ...governanceBootstrapQueryOptions,
    placeholderData: keepPreviousData,
  });
  const portfolioQuery = useQuery({
    ...deliveryPortfolioQueryOptions,
    enabled: showDelivery,
  });
  const projectsQuery = useQuery(projectsQueryOptions);
  const usersQuery = useQuery({
    queryKey: ["users"],
    queryFn: listUsers,
    enabled: canWrite,
  });

  const [filters, setFilters] = useState(emptyGovernanceFilters);
  const [dialog, setDialog] = useState<WorkflowDialogState>(null);
  const [confirm, setConfirm] = useState<ConfirmState>(null);
  const [selectedRow, setSelectedRow] = useState<GovernanceRegisterRow | null>(null);
  const [sheetOpen, setSheetOpen] = useState(false);
  const [promotingRiskId, setPromotingRiskId] = useState<string | null>(null);
  const [busyId, setBusyId] = useState<string | null>(null);
  const [activeTable, setActiveTable] = useState<GovernanceTableTab>("dependencies");
  const [dependencyPage, setDependencyPage] = useState(1);
  const [actionPage, setActionPage] = useState(1);
  const [registerPage, setRegisterPage] = useState(1);
  const [escalationPage, setEscalationPage] = useState(1);

  const cachedBootstrap = queryClient.getQueryData<GovernanceBootstrap>(
    governanceBootstrapQueryOptions.queryKey,
  );
  const data = bootstrapQuery.data ?? cachedBootstrap;

  const projectOptions = useMemo(
    () =>
      (projectsQuery.data ?? []).map((p) => ({
        value: p.id,
        label: p.name,
      })),
    [projectsQuery.data],
  );

  const userOptions = useMemo(
    () =>
      (usersQuery.data ?? []).map((u) => ({
        value: u.id,
        label: u.full_name || u.email,
      })),
    [usersQuery.data],
  );

  const projectNameById = useMemo(
    () => new Map(projectOptions.map((project) => [project.value, project.label])),
    [projectOptions],
  );

  const userNameById = useMemo(
    () => new Map(userOptions.map((userOption) => [userOption.value, userOption.label])),
    [userOptions],
  );

  const updateBootstrapCache = (updater: (current: GovernanceBootstrap) => GovernanceBootstrap) => {
    queryClient.setQueryData<GovernanceBootstrap>(
      governanceBootstrapQueryOptions.queryKey,
      (current) => (current ? recalculateBootstrapKpis(updater(current)) : current),
    );
  };

  const hydrateDependency = (
    next: ProjectDependency,
    current?: ProjectDependency,
  ): ProjectDependency => ({
    ...next,
    project_name:
      next.project_name ?? current?.project_name ?? projectNameById.get(next.project_id) ?? null,
    owner_name:
      next.owner_name ??
      (next.owner_id ? userNameById.get(next.owner_id) : null) ??
      current?.owner_name ??
      null,
  });

  const hydrateAction = (next: GovernanceAction, current?: GovernanceAction): GovernanceAction => ({
    ...next,
    project_name:
      next.project_name ?? current?.project_name ?? projectNameById.get(next.project_id) ?? null,
    owner_name:
      next.owner_name ??
      (next.owner_id ? userNameById.get(next.owner_id) : null) ??
      current?.owner_name ??
      null,
  });

  const hydrateEscalation = (
    next: GovernanceEscalation,
    current?: GovernanceEscalation,
  ): GovernanceEscalation => ({
    ...next,
    project_name:
      next.project_name ?? current?.project_name ?? projectNameById.get(next.project_id) ?? null,
    raised_by_name: next.raised_by_name ?? current?.raised_by_name ?? null,
    assigned_to_name:
      next.assigned_to_name ??
      (next.assigned_to ? userNameById.get(next.assigned_to) : null) ??
      current?.assigned_to_name ??
      null,
  });

  const registerRows = useMemo(() => {
    if (!data) return [];
    const rows = buildGovernanceRegister(data, portfolioQuery.data);
    return filterRegisterByScope(rows, filters);
  }, [data, portfolioQuery.data, filters]);

  const filteredDependencies = useMemo(
    () => (data ? filterDependencies(data.dependencies, filters) : []),
    [data, filters],
  );
  const filteredActions = useMemo(
    () => (data ? filterActions(data.actions, filters) : []),
    [data, filters],
  );
  const filteredEscalations = useMemo(
    () => (data ? filterEscalations(data.escalations, filters) : []),
    [data, filters],
  );

  const visibleTableTabs = useMemo(
    () =>
      (
        [
          !isClient && {
            value: "dependencies" as const,
            label: "Dependency Tracker",
            count: filteredDependencies.length,
          },
          !isClient && {
            value: "actions" as const,
            label: "Governance Actions",
            count: filteredActions.length,
          },
          {
            value: "register" as const,
            label: "Governance Register",
            count: registerRows.length,
          },
          {
            value: "escalations" as const,
            label: "Escalation Register",
            count: filteredEscalations.length,
          },
        ] satisfies Array<false | { value: GovernanceTableTab; label: string; count: number }>
      ).filter(Boolean) as Array<{ value: GovernanceTableTab; label: string; count: number }>,
    [
      filteredActions.length,
      filteredDependencies.length,
      filteredEscalations.length,
      isClient,
      registerRows.length,
    ],
  );
  const selectedTable = visibleTableTabs.some((tab) => tab.value === activeTable)
    ? activeTable
    : (visibleTableTabs[0]?.value ?? "register");
  const pagedDependencies = useMemo(
    () => paginateRows(filteredDependencies, dependencyPage),
    [dependencyPage, filteredDependencies],
  );
  const pagedActions = useMemo(
    () => paginateRows(filteredActions, actionPage),
    [actionPage, filteredActions],
  );
  const pagedRegisterRows = useMemo(
    () => paginateRows(registerRows, registerPage),
    [registerPage, registerRows],
  );
  const pagedEscalations = useMemo(
    () => paginateRows(filteredEscalations, escalationPage),
    [escalationPage, filteredEscalations],
  );

  const dueThisWeek = useMemo(() => (data ? actionsDueThisWeek(data.actions) : []), [data]);

  const escalatedRiskIds = useMemo(() => {
    if (!data) return new Set<string>();
    return new Set(
      data.escalations
        .filter((e) => e.source_type === "delivery_risk" && e.source_id)
        .map((e) => e.source_id as string),
    );
  }, [data]);

  const refetchDashboardData = async () => {
    await bootstrapQuery.refetch();
    if (showDelivery) await portfolioQuery.refetch();
  };

  const runConfirm = async () => {
    if (!confirm) return;
    setBusyId(confirm.id);
    try {
      if (confirm.kind === "resolve-dependency") {
        const dependency = await resolveDependency(confirm.id);
        updateBootstrapCache((current) => {
          const existing = current.dependencies.find((row) => row.id === dependency.id);
          return {
            ...current,
            dependencies: replaceOrAddById(
              current.dependencies,
              hydrateDependency(dependency, existing),
            ),
          };
        });
        toast.success("Dependency resolved.");
      } else if (confirm.kind === "resolve-escalation") {
        const escalation = await updateGovernanceEscalation(confirm.id, { status: "resolved" });
        updateBootstrapCache((current) => {
          const existing = current.escalations.find((row) => row.id === escalation.id);
          return {
            ...current,
            escalations: replaceOrAddById(
              current.escalations,
              hydrateEscalation(escalation, existing),
            ),
          };
        });
        toast.success("Escalation resolved.");
      } else if (confirm.kind === "complete-action") {
        const action = await updateGovernanceAction(confirm.id, { status: "completed" });
        updateBootstrapCache((current) => {
          const existing = current.actions.find((row) => row.id === action.id);
          return {
            ...current,
            actions: replaceOrAddById(current.actions, hydrateAction(action, existing)),
          };
        });
        toast.success("Action completed.");
      } else if (confirm.kind === "delete-dependency") {
        await deleteDependency(confirm.id);
        updateBootstrapCache((current) => ({
          ...current,
          dependencies: current.dependencies.filter((row) => row.id !== confirm.id),
        }));
        toast.success("Dependency archived.");
      } else if (confirm.kind === "delete-escalation") {
        await deleteGovernanceEscalation(confirm.id);
        updateBootstrapCache((current) => ({
          ...current,
          escalations: current.escalations.filter((row) => row.id !== confirm.id),
        }));
        toast.success("Escalation archived.");
      } else if (confirm.kind === "delete-action") {
        await deleteGovernanceAction(confirm.id);
        updateBootstrapCache((current) => ({
          ...current,
          actions: current.actions.filter((row) => row.id !== confirm.id),
        }));
        toast.success("Action archived.");
      }
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Action failed.");
    } finally {
      setBusyId(null);
      setConfirm(null);
    }
  };

  const handlePromoteRisk = async (riskAlertId: string) => {
    setPromotingRiskId(riskAlertId);
    try {
      const escalation = await promoteRiskAlertToEscalation(riskAlertId);
      updateBootstrapCache((current) => ({
        ...current,
        escalations: replaceOrAddById(current.escalations, hydrateEscalation(escalation)),
      }));
      toast.success("Delivery risk promoted to escalation.");
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Promotion failed.");
    } finally {
      setPromotingRiskId(null);
    }
  };

  const openProjectSheet = (row: GovernanceRegisterRow) => {
    setSelectedRow(row);
    setSheetOpen(true);
  };

  if (!data && bootstrapQuery.isLoading) {
    return <PageLoadingScreen label="Loading governance…" />;
  }

  if (bootstrapQuery.isError || !data) {
    return (
      <Card>
        <SectionError
          message={
            bootstrapQuery.error instanceof Error
              ? bootstrapQuery.error.message
              : "Unable to load governance data."
          }
          onRetry={() => void refetchDashboardData()}
        />
      </Card>
    );
  }

  const { kpis, charter_references } = data;
  const openActionsDelta =
    dueThisWeek.length > 0 ? `${dueThisWeek.length} due this week` : undefined;

  return (
    <div className="governance-no-shadow space-y-5">
      {isReadOnly && (
        <div className="rounded-md border border-border bg-elevated px-3 py-2 text-xs text-muted-foreground">
          Read-only portfolio governance view.
        </div>
      )}
      {isClient && (
        <div className="rounded-md border border-border bg-elevated px-3 py-2 text-xs text-muted-foreground">
          Client-safe escalation visibility only. Internal dependencies, actions, and draft
          summaries are hidden.
        </div>
      )}
      {bootstrapQuery.isFetching && (
        <div className="flex items-center gap-2 text-[10px] text-muted-foreground">
          <RefreshCw className="h-3 w-3 animate-spin" />
          Refreshing governance data...
        </div>
      )}

      <GovernanceFiltersBar
        filters={filters}
        onChange={setFilters}
        projects={projectOptions}
        users={userOptions}
        showInternalFilters={!isClient}
      />

      {canWrite && (
        <div className="flex flex-wrap gap-2">
          <Button
            type="button"
            size="sm"
            variant="outline"
            className="shadow-none"
            onClick={() => setDialog({ kind: "dependency", mode: "create" })}
          >
            <Plus className="mr-1 h-3.5 w-3.5" />
            Dependency
          </Button>
          <Button
            type="button"
            size="sm"
            variant="outline"
            className="shadow-none"
            onClick={() => setDialog({ kind: "action", mode: "create" })}
          >
            <Plus className="mr-1 h-3.5 w-3.5" />
            Action
          </Button>
          <Button
            type="button"
            size="sm"
            variant="outline"
            className="shadow-none"
            onClick={() => setDialog({ kind: "escalation", mode: "create" })}
          >
            <Plus className="mr-1 h-3.5 w-3.5" />
            Escalation
          </Button>
        </div>
      )}

      <div className="space-y-5">
        <div className="grid grid-cols-2 gap-4 lg:grid-cols-3">
          <KpiCard
            label="Open Actions"
            value={kpis.open_actions}
            delta={openActionsDelta}
            tone={kpis.open_actions > 0 ? "warning" : "default"}
          />
          <KpiCard
            label="Overdue Actions"
            value={kpis.overdue_actions}
            tone={kpis.overdue_actions > 0 ? "danger" : "default"}
          />
          <KpiCard
            label="At-Risk Items"
            value={kpis.at_risk_items}
            tone={kpis.at_risk_items > 0 ? "danger" : "success"}
          />
          <KpiCard
            label="Open Escalations"
            value={kpis.open_escalations}
            tone={kpis.open_escalations > 0 ? "danger" : "default"}
          />
          <KpiCard
            label="Blocking Dependencies"
            value={kpis.blocking_dependencies}
            tone={kpis.blocking_dependencies > 0 ? "danger" : "default"}
          />
          <KpiCard
            label="SLA Adherence"
            value={`${kpis.sla_adherence_pct}%`}
            tone={kpis.sla_adherence_pct >= 90 ? "success" : "warning"}
          />
        </div>

        <Tabs
          value={selectedTable}
          onValueChange={(value) => setActiveTable(value as GovernanceTableTab)}
          className="space-y-3"
        >
          <TabsList className="h-auto flex-wrap justify-start gap-1 bg-elevated">
            {visibleTableTabs.map((tab) => (
              <TabsTrigger key={tab.value} value={tab.value} className="gap-2 text-xs">
                {tab.label}
                <span className="rounded bg-background px-1.5 py-0.5 text-[10px] text-muted-foreground">
                  {tab.count}
                </span>
              </TabsTrigger>
            ))}
          </TabsList>

          <TabsContent value="dependencies" className="mt-0">
            {!isClient && selectedTable === "dependencies" && (
              <Card>
                <SectionHeader title="Dependency Tracker" sub="Cross-project dependencies" />
                <div className={GOVERNANCE_TABLE_VIEWPORT_CLASS}>
                  <table className="w-full text-xs">
                    <thead className="text-left text-muted-foreground">
                      <tr className="border-b border-border">
                        <th className="py-2 pr-3 font-medium">Dependency</th>
                        <th className="py-2 pr-3 font-medium">Project</th>
                        <th className="py-2 pr-3 font-medium">Type</th>
                        <th className="py-2 pr-3 font-medium">Owner</th>
                        <th className="py-2 pr-3 font-medium">Due</th>
                        <th className="py-2 pr-3 font-medium">Overdue</th>
                        <th className="py-2 pr-3 font-medium">Status</th>
                        {canWrite && <th className="py-2 pr-3 font-medium">Actions</th>}
                      </tr>
                    </thead>
                    <tbody>
                      {filteredDependencies.length === 0 ? (
                        <EmptyRow
                          colSpan={canWrite ? 8 : 7}
                          message="No dependencies match filters."
                        />
                      ) : (
                        pagedDependencies.map((dep) => (
                          <tr
                            key={dep.id}
                            className={cn("border-b border-border/50", dependencyRowClass(dep))}
                          >
                            <td className="py-2.5 pr-3 font-medium">{dep.title}</td>
                            <td className="py-2.5 pr-3">{dep.project_name ?? "—"}</td>
                            <td className="py-2.5 pr-3 text-muted-foreground">
                              {formatDependencyType(dep.dependency_type)}
                            </td>
                            <td className="py-2.5 pr-3 text-muted-foreground">
                              {dep.owner_name ?? "—"}
                            </td>
                            <td className="py-2.5 pr-3 text-muted-foreground">
                              {formatDate(dep.due_date)}
                            </td>
                            <td className="py-2.5 pr-3">
                              {dep.overdue_days > 0 ? (
                                <span className="text-[color:var(--danger)]">
                                  {dep.overdue_days}d
                                </span>
                              ) : (
                                "—"
                              )}
                            </td>
                            <td className="py-2.5 pr-3">
                              <StatusPill status={formatDependencyStatus(dep.status)} />
                            </td>
                            {canWrite && (
                              <td className="py-2.5 pr-3">
                                <RowActions
                                  canWrite={canWrite}
                                  onEdit={() =>
                                    setDialog({
                                      kind: "dependency",
                                      mode: "edit",
                                      id: dep.id,
                                      projectId: dep.project_id,
                                    })
                                  }
                                  showResolve={dep.status !== "resolved"}
                                  onResolve={() =>
                                    setConfirm({
                                      kind: "resolve-dependency",
                                      id: dep.id,
                                      label: dep.title,
                                    })
                                  }
                                  onDelete={() =>
                                    setConfirm({
                                      kind: "delete-dependency",
                                      id: dep.id,
                                      label: dep.title,
                                    })
                                  }
                                />
                              </td>
                            )}
                          </tr>
                        ))
                      )}
                    </tbody>
                  </table>
                </div>
                <TablePagination
                  page={dependencyPage}
                  totalRows={filteredDependencies.length}
                  onPageChange={setDependencyPage}
                />
              </Card>
            )}
          </TabsContent>

          <TabsContent value="actions" className="mt-0">
            {!isClient && selectedTable === "actions" && (
              <Card>
                <SectionHeader
                  title="Governance Actions"
                  sub="Tracked follow-ups and commitments"
                />
                <div className={GOVERNANCE_TABLE_VIEWPORT_CLASS}>
                  <table className="w-full text-xs">
                    <thead className="text-left text-muted-foreground">
                      <tr className="border-b border-border">
                        <th className="py-2 pr-3 font-medium">Action</th>
                        <th className="py-2 pr-3 font-medium">Project</th>
                        <th className="py-2 pr-3 font-medium">Owner</th>
                        <th className="py-2 pr-3 font-medium">Due</th>
                        <th className="py-2 pr-3 font-medium">Status</th>
                        {canWrite && <th className="py-2 pr-3 font-medium">Actions</th>}
                      </tr>
                    </thead>
                    <tbody>
                      {filteredActions.length === 0 ? (
                        <EmptyRow colSpan={canWrite ? 6 : 5} message="No actions match filters." />
                      ) : (
                        pagedActions.map((action) => (
                          <tr key={action.id} className="border-b border-border/50">
                            <td className="py-2.5 pr-3 font-medium">{action.title}</td>
                            <td className="py-2.5 pr-3">{action.project_name ?? "—"}</td>
                            <td className="py-2.5 pr-3 text-muted-foreground">
                              {action.owner_name ?? "—"}
                            </td>
                            <td className="py-2.5 pr-3 text-muted-foreground">
                              {formatDate(action.due_date)}
                            </td>
                            <td className="py-2.5 pr-3">
                              <StatusPill status={formatActionStatus(action.status)} />
                            </td>
                            {canWrite && (
                              <td className="py-2.5 pr-3">
                                <RowActions
                                  canWrite={canWrite}
                                  onEdit={() =>
                                    setDialog({
                                      kind: "action",
                                      mode: "edit",
                                      id: action.id,
                                      projectId: action.project_id,
                                    })
                                  }
                                  showResolve={action.status !== "completed"}
                                  resolveLabel="Complete"
                                  onResolve={() =>
                                    setConfirm({
                                      kind: "complete-action",
                                      id: action.id,
                                      label: action.title,
                                    })
                                  }
                                  onDelete={() =>
                                    setConfirm({
                                      kind: "delete-action",
                                      id: action.id,
                                      label: action.title,
                                    })
                                  }
                                />
                              </td>
                            )}
                          </tr>
                        ))
                      )}
                    </tbody>
                  </table>
                </div>
                <TablePagination
                  page={actionPage}
                  totalRows={filteredActions.length}
                  onPageChange={setActionPage}
                />
              </Card>
            )}
          </TabsContent>

          <TabsContent value="register" className="mt-0">
            {selectedTable === "register" && (
              <Card>
                <SectionHeader title="Governance Register" sub="Click a project for details" />
                <div className={GOVERNANCE_TABLE_VIEWPORT_CLASS}>
                  <table className="w-full text-xs">
                    <thead className="text-left text-muted-foreground">
                      <tr className="border-b border-border">
                        <th className="py-2 pr-3 font-medium">Project</th>
                        <th className="py-2 pr-3 font-medium">Scope</th>
                        <th className="py-2 pr-3 font-medium">Version</th>
                        {!isClient && <th className="py-2 pr-3 font-medium">Dependencies</th>}
                        {!isClient && <th className="py-2 pr-3 font-medium">Actions</th>}
                        <th className="py-2 pr-3 font-medium">Escalations</th>
                        <th className="py-2 pr-3 font-medium">Governance</th>
                        {showDelivery && <th className="py-2 pr-3 font-medium">Delivery</th>}
                      </tr>
                    </thead>
                    <tbody>
                      {registerRows.length === 0 ? (
                        <EmptyRow
                          colSpan={isClient ? (showDelivery ? 5 : 4) : showDelivery ? 8 : 7}
                          message="No governance register entries match filters."
                        />
                      ) : (
                        pagedRegisterRows.map((row) => (
                          <tr
                            key={row.projectId}
                            className="cursor-pointer border-b border-border/50 hover:bg-elevated/80"
                            onClick={() => openProjectSheet(row)}
                          >
                            <td className="py-2.5 pr-3 font-medium">{row.projectName}</td>
                            <td className="py-2.5 pr-3">
                              <StatusPill
                                status={
                                  row.scopeStatus === "approved"
                                    ? "Approved"
                                    : row.scopeStatus === "pending_revision"
                                      ? "Pending"
                                      : row.scopeStatus === "locked"
                                        ? "In Progress"
                                        : "—"
                                }
                              />
                            </td>
                            <td className="py-2.5 pr-3 text-muted-foreground">
                              {row.scopeVersion ?? "—"}
                            </td>
                            {!isClient && (
                              <td className="py-2.5 pr-3 text-muted-foreground">
                                {row.blockingDependencies > 0
                                  ? `${row.blockingDependencies} blocking`
                                  : `${row.openDependencies} open`}
                              </td>
                            )}
                            {!isClient && <td className="py-2.5 pr-3">{row.openActions}</td>}
                            <td className="py-2.5 pr-3">
                              {row.openEscalations > 0 ? (
                                <span className="text-[color:var(--danger)]">
                                  {row.openEscalations}
                                </span>
                              ) : (
                                "0"
                              )}
                            </td>
                            <td className="py-2.5 pr-3">
                              <StatusPill status={row.health} />
                            </td>
                            {showDelivery && (
                              <td className="py-2.5 pr-3">
                                <div className="flex flex-col gap-0.5">
                                  <StatusPill
                                    status={deliveryTrafficLabel(row.deliveryTrafficLight)}
                                  />
                                  {row.deliveryConfidence !== null && (
                                    <span className="text-[10px] text-muted-foreground">
                                      {row.deliveryConfidence}% confidence
                                    </span>
                                  )}
                                </div>
                              </td>
                            )}
                          </tr>
                        ))
                      )}
                    </tbody>
                  </table>
                </div>
                <TablePagination
                  page={registerPage}
                  totalRows={registerRows.length}
                  onPageChange={setRegisterPage}
                />
              </Card>
            )}
          </TabsContent>

          <TabsContent value="escalations" className="mt-0">
            {selectedTable === "escalations" && (
              <Card>
                <SectionHeader title="Escalation Register" />
                <div className={GOVERNANCE_TABLE_VIEWPORT_CLASS}>
                  <table className="w-full text-xs">
                    <thead className="text-left text-muted-foreground">
                      <tr className="border-b border-border">
                        <th className="py-2 pr-3 font-medium">Title</th>
                        <th className="py-2 pr-3 font-medium">Project</th>
                        <th className="py-2 pr-3 font-medium">Severity</th>
                        <th className="py-2 pr-3 font-medium">Status</th>
                        <th className="py-2 pr-3 font-medium">Raised By</th>
                        <th className="py-2 pr-3 font-medium">Assigned</th>
                        <th className="py-2 pr-3 font-medium">Raised</th>
                        {!isClient && <th className="py-2 pr-3 font-medium">Source</th>}
                        {canWrite && <th className="py-2 pr-3 font-medium">Actions</th>}
                      </tr>
                    </thead>
                    <tbody>
                      {filteredEscalations.length === 0 ? (
                        <EmptyRow
                          colSpan={isClient ? 7 : canWrite ? 9 : 8}
                          message="No escalations match filters."
                        />
                      ) : (
                        pagedEscalations.map((esc) => (
                          <tr
                            key={esc.id}
                            className={cn("border-b border-border/50", escalationRowClass(esc))}
                          >
                            <td className="py-2.5 pr-3 font-medium">{esc.title}</td>
                            <td className="py-2.5 pr-3">{esc.project_name ?? "—"}</td>
                            <td className="py-2.5 pr-3">
                              <StatusPill status={formatEscalationSeverity(esc.severity)} />
                            </td>
                            <td className="py-2.5 pr-3">
                              <StatusPill status={formatEscalationStatus(esc.status)} />
                            </td>
                            <td className="py-2.5 pr-3 text-muted-foreground">
                              {esc.raised_by_name ?? "—"}
                            </td>
                            <td className="py-2.5 pr-3">{esc.assigned_to_name ?? "—"}</td>
                            <td className="py-2.5 pr-3 text-muted-foreground">
                              {formatDate(esc.raised_at)}
                            </td>
                            {!isClient && (
                              <td className="py-2.5 pr-3 text-muted-foreground">
                                {esc.source_type === "delivery_risk"
                                  ? "Delivery risk"
                                  : esc.source_type === "knowledge_document"
                                    ? "Knowledge doc"
                                    : "—"}
                              </td>
                            )}
                            {canWrite && (
                              <td className="py-2.5 pr-3">
                                <RowActions
                                  canWrite={canWrite}
                                  onEdit={() =>
                                    setDialog({
                                      kind: "escalation",
                                      mode: "edit",
                                      id: esc.id,
                                      projectId: esc.project_id,
                                    })
                                  }
                                  showResolve={esc.status !== "resolved"}
                                  onResolve={() =>
                                    setConfirm({
                                      kind: "resolve-escalation",
                                      id: esc.id,
                                      label: esc.title,
                                    })
                                  }
                                  onDelete={() =>
                                    setConfirm({
                                      kind: "delete-escalation",
                                      id: esc.id,
                                      label: esc.title,
                                    })
                                  }
                                />
                              </td>
                            )}
                          </tr>
                        ))
                      )}
                    </tbody>
                  </table>
                </div>
                <TablePagination
                  page={escalationPage}
                  totalRows={filteredEscalations.length}
                  onPageChange={setEscalationPage}
                />
              </Card>
            )}
          </TabsContent>
        </Tabs>
      </div>

      <ProjectChartersPanel
        projects={projectOptions}
        canWrite={canWrite}
        isClient={isClient}
        isReadOnly={isReadOnly}
      />

      {!isClient && charter_references.length > 0 && (
        <Card>
          <SectionHeader
            title="Linked Knowledge Documents"
            sub="Approved charters and governance references from Operational Knowledge"
          />
          <ul className="space-y-2 text-xs">
            {charter_references.map((doc) => (
              <li
                key={doc.document_id}
                className="flex items-start gap-2 rounded border border-border bg-elevated px-3 py-2"
              >
                <FileText className="mt-0.5 h-4 w-4 shrink-0 text-[color:var(--brand)]" />
                <div className="min-w-0">
                  <div className="font-medium">{doc.title}</div>
                  <div className="mt-0.5 text-[10px] text-muted-foreground">
                    {doc.project ? `${doc.project} · ` : ""}
                    {doc.version} · {doc.visibility}
                  </div>
                </div>
                <StatusPill status="Approved" />
              </li>
            ))}
          </ul>
        </Card>
      )}

      <GovernanceWorkflowDialogs
        dialog={dialog}
        onClose={() => setDialog(null)}
        data={data}
        projects={projectOptions}
        users={userOptions}
        canWrite={canWrite}
        onSaveDependency={async ({ projectId, id, values }) => {
          let dependency: ProjectDependency;
          if (id) {
            dependency = await updateDependency(id, {
              title: values.title ?? undefined,
              description: values.description,
              dependency_type: values.dependency_type as GovernanceDependencyType,
              owner_id: values.owner_id,
              due_date: values.due_date,
              status: values.status as "open" | "blocking" | "resolved",
            });
            toast.success("Dependency updated.");
          } else {
            dependency = await createProjectDependency(projectId, {
              title: values.title!,
              description: values.description,
              dependency_type: values.dependency_type as GovernanceDependencyType,
              owner_id: values.owner_id,
              due_date: values.due_date,
              status: values.status as "open" | "blocking" | "resolved",
            });
            toast.success("Dependency created.");
          }
          updateBootstrapCache((current) => {
            const existing = current.dependencies.find((row) => row.id === dependency.id);
            return {
              ...current,
              dependencies: replaceOrAddById(
                current.dependencies,
                hydrateDependency(dependency, existing),
              ),
            };
          });
        }}
        onSaveAction={async ({ projectId, id, values }) => {
          let action: GovernanceAction;
          if (id) {
            action = await updateGovernanceAction(id, {
              title: values.title ?? undefined,
              description: values.description,
              owner_id: values.owner_id,
              due_date: values.due_date,
              status: values.status as "open" | "in_progress" | "completed" | "overdue",
              linked_knowledge_document_id: values.linked_knowledge_document_id,
            });
            toast.success("Action updated.");
          } else {
            action = await createGovernanceAction({
              project_id: projectId,
              title: values.title!,
              description: values.description,
              owner_id: values.owner_id,
              due_date: values.due_date,
              status: values.status as "open" | "in_progress" | "completed" | "overdue",
              linked_knowledge_document_id: values.linked_knowledge_document_id,
            });
            toast.success("Action created.");
          }
          updateBootstrapCache((current) => {
            const existing = current.actions.find((row) => row.id === action.id);
            return {
              ...current,
              actions: replaceOrAddById(current.actions, hydrateAction(action, existing)),
            };
          });
        }}
        onSaveEscalation={async ({ projectId, id, values }) => {
          let escalation: GovernanceEscalation;
          if (id) {
            escalation = await updateGovernanceEscalation(id, {
              title: values.title ?? undefined,
              description: values.description,
              severity: values.severity as GovernanceEscalationSeverity,
              status: values.status as "open" | "in_progress" | "resolved",
              assigned_to: values.assigned_to,
              source_type: values.source_type as GovernanceEscalationSourceType | null,
              source_id: values.source_id,
            });
            toast.success("Escalation updated.");
          } else {
            escalation = await createGovernanceEscalation({
              project_id: projectId,
              title: values.title!,
              description: values.description,
              severity: values.severity as GovernanceEscalationSeverity,
              status: values.status as "open" | "in_progress" | "resolved",
              assigned_to: values.assigned_to,
              source_type: values.source_type as GovernanceEscalationSourceType | null,
              source_id: values.source_id,
            });
            toast.success("Escalation created.");
          }
          updateBootstrapCache((current) => {
            const existing = current.escalations.find((row) => row.id === escalation.id);
            return {
              ...current,
              escalations: replaceOrAddById(
                current.escalations,
                hydrateEscalation(escalation, existing),
              ),
            };
          });
        }}
        onSaveScope={async ({ projectId, values }) => {
          const scope = await updateProjectScope(projectId, {
            scope_status: values.scope_status as GovernanceScopeStatus,
            version_label: values.version_label ?? undefined,
            notes: values.notes,
            linked_charter_document_id: values.linked_charter_document_id,
          });
          toast.success("Scope updated.");
          updateBootstrapCache((current) => ({
            ...current,
            scope_states: current.scope_states.some((row) => row.id === scope.id)
              ? current.scope_states.map((row) => (row.id === scope.id ? scope : row))
              : replaceOrAddById(current.scope_states, scope),
          }));
        }}
      />

      <ProjectGovernanceSheet
        open={sheetOpen}
        onClose={() => setSheetOpen(false)}
        row={selectedRow}
        data={data}
        portfolio={portfolioQuery.data}
        canWrite={canWrite}
        showDelivery={showDelivery}
        onEditScope={(projectId) => setDialog({ kind: "scope", mode: "edit", projectId })}
        onEditDependency={(id) => setDialog({ kind: "dependency", mode: "edit", id })}
        onEditAction={(id) => setDialog({ kind: "action", mode: "edit", id })}
        onEditEscalation={(id) => setDialog({ kind: "escalation", mode: "edit", id })}
        onCreateDependency={(projectId) =>
          setDialog({ kind: "dependency", mode: "create", projectId })
        }
        onCreateAction={(projectId) => setDialog({ kind: "action", mode: "create", projectId })}
        onCreateEscalation={(projectId) =>
          setDialog({ kind: "escalation", mode: "create", projectId })
        }
        onPromoteRisk={(riskAlertId) => void handlePromoteRisk(riskAlertId)}
        promotingRiskId={promotingRiskId}
        escalatedRiskIds={escalatedRiskIds}
      />

      <AlertDialog open={Boolean(confirm)} onOpenChange={(open) => !open && setConfirm(null)}>
        <AlertDialogContent className="governance-no-shadow">
          <AlertDialogHeader>
            <AlertDialogTitle>
              {confirm?.kind.startsWith("delete") ? "Archive item?" : "Confirm action"}
            </AlertDialogTitle>
            <AlertDialogDescription>
              {confirm?.kind === "resolve-dependency" && `Mark "${confirm.label}" as resolved?`}
              {confirm?.kind === "resolve-escalation" && `Mark "${confirm.label}" as resolved?`}
              {confirm?.kind === "complete-action" && `Mark "${confirm.label}" as completed?`}
              {confirm?.kind === "delete-dependency" && `Archive dependency "${confirm.label}"?`}
              {confirm?.kind === "delete-escalation" && `Archive escalation "${confirm.label}"?`}
              {confirm?.kind === "delete-action" && `Archive action "${confirm.label}"?`}
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel disabled={Boolean(busyId)}>Cancel</AlertDialogCancel>
            <AlertDialogAction disabled={Boolean(busyId)} onClick={() => void runConfirm()}>
              {busyId ? "Working…" : "Confirm"}
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </div>
  );
}
