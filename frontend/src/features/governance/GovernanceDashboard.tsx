import { keepPreviousData, useQuery, useQueryClient } from "@tanstack/react-query";
import { useNavigate } from "@tanstack/react-router";
import { Suspense, useEffect, useMemo, useRef, useState } from "react";
import { AlertCircle, Plus, RefreshCw } from "lucide-react";
import { toast } from "sonner";

import { Card, SectionHeader, StatusPill } from "@/components/bsg/widgets";
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
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Textarea } from "@/components/ui/textarea";
import { GovernanceFiltersBar } from "@/features/governance/GovernanceFiltersBar";
import {
  collectProjectNamesFromGovernanceRows,
  GOVERNANCE_ANALYTICS_DEFER_MS,
  GOVERNANCE_ANALYTICS_DETAIL_IDLE_MS,
  resolveGovernanceTabTotals,
  shouldEnableGovernanceAnalyticsDetail,
  shouldEnableGovernanceAnalyticsSummary,
  shouldEnableGovernanceProjects,
} from "@/features/governance/governance-load-strategy";
import {
  GOVERNANCE_DEFAULT_ANALYTICS_DAYS,
  GOVERNANCE_DEFAULT_TABLE_PARAMS,
} from "@/features/governance/governance-prefetch";
import {
  ExecutiveDashboardFallback,
  GovernanceToolsPanelFallback,
  LazyAskGovernanceAgentPanel,
  LazyExecutiveGovernanceDashboard,
  LazyGovernanceWorkflowDialogs,
  LazyProjectChartersPanel,
  ProjectChartersPanelFallback,
  preloadProjectChartersPanel,
} from "@/features/governance/governance-lazy";
import { Route as GovernanceRoute } from "@/routes/governance";
import type { WorkflowDialogState } from "@/features/governance/governance-workflow-types";
import { ProjectGovernanceSheet } from "@/features/governance/ProjectGovernanceSheet";
import { GovernanceWeeklySummaryPanel } from "@/features/governance/GovernanceWeeklySummaryPanel";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { emptyGovernanceFilters } from "@/features/governance/filters";
import { listUsers } from "@/lib/api";
import {
  mapRegisterApiRow,
  dependencyRowClass,
  escalationRowClass,
  formatActionStatus,
  formatDate,
  formatDependencyStatus,
  formatDependencyType,
  formatEscalationSeverity,
  formatEscalationStatus,
  isCriticalPathDependency,
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
  governanceActionsQueryOptions,
  governanceAnalyticsDetailQueryOptions,
  governanceAnalyticsSummaryQueryOptions,
  governanceBootstrapQueryOptions,
  mergeGovernanceAnalytics,
  governanceDependenciesQueryOptions,
  governanceEscalationsQueryOptions,
  governanceProjectChartersPanelQueryOptions,
  governanceProjectSheetQueryOptions,
  governanceRegisterQueryOptions,
  governanceWeeklySummaryQueryOptions,
  invalidateGovernanceProjectSheet,
  promoteRiskAlertToEscalation,
  publishClientEscalationSummary,
  resolveDependency,
  updateDependency,
  updateGovernanceAction,
  updateGovernanceEscalation,
  updateProjectScope,
} from "@/lib/queries/governance";
import { queryKeys } from "@/lib/queries/keys";
import { cn } from "@/lib/utils";
import { useAuthStore } from "@/stores/useAuthStore";
import type { AppRole } from "@/types/auth";
import type {
  GovernanceAction,
  GovernanceActionListItem,
  GovernanceBootstrap,
  GovernanceDependencyType,
  GovernanceEscalation,
  GovernanceEscalationListItem,
  GovernanceEscalationSeverity,
  GovernanceEscalationSourceType,
  GovernanceListParams,
  GovernanceScopeStatus,
  PaginatedGovernanceList,
  ProjectDependency,
  ProjectDependencyListItem,
} from "@/types/governance";

const TABLE_PAGE_SIZE = GOVERNANCE_DEFAULT_TABLE_PARAMS.limit;
const GOVERNANCE_TABLE_VIEWPORT_CLASS =
  "governance-table-shell min-h-[180px] max-h-[360px] overflow-x-auto overflow-y-auto";

type GovernanceTableTab = "dependencies" | "actions" | "register" | "escalations";

function getPageCount(totalRows: number): number {
  return Math.max(1, Math.ceil(totalRows / TABLE_PAGE_SIZE));
}

function getSafePage(page: number, totalRows: number): number {
  return Math.min(Math.max(page, 1), getPageCount(totalRows));
}

function emptyPaginatedList<T>(): PaginatedGovernanceList<T> {
  return {
    items: [],
    total: 0,
    limit: TABLE_PAGE_SIZE,
    offset: 0,
    has_more: false,
  };
}

function backendListParams(
  filters: ReturnType<typeof emptyGovernanceFilters>,
  page: number,
  extra: Partial<GovernanceListParams> = {},
): GovernanceListParams {
  return {
    limit: TABLE_PAGE_SIZE,
    offset: (getSafePage(page, Number.MAX_SAFE_INTEGER) - 1) * TABLE_PAGE_SIZE,
    project_id: filters.projectId !== "all" ? filters.projectId : undefined,
    status: filters.status !== "all" ? filters.status : undefined,
    search: filters.search.trim() || undefined,
    date_to: filters.dueBefore || undefined,
    ...extra,
  };
}

function useDebouncedValue<T>(value: T, delayMs: number): T {
  const [debouncedValue, setDebouncedValue] = useState(value);

  useEffect(() => {
    const timer = window.setTimeout(() => setDebouncedValue(value), delayMs);
    return () => window.clearTimeout(timer);
  }, [delayMs, value]);

  return debouncedValue;
}

function replaceOrAddById<T extends { id: string }>(rows: T[], next: T): T[] {
  return rows.some((row) => row.id === next.id)
    ? rows.map((row) => (row.id === next.id ? next : row))
    : [next, ...rows];
}

function canWriteGovernance(role: AppRole | undefined): boolean {
  return role === "delivery_manager" || role === "super_admin";
}

function canPublishCharter(role: AppRole | undefined): boolean {
  return role === "bsg_leadership" || role === "super_admin";
}

function canManageWeeklySummary(role: AppRole | undefined): boolean {
  return role === "delivery_manager" || role === "bsg_leadership" || role === "super_admin";
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

const EMPTY_GOVERNANCE_KPIS: GovernanceBootstrap["kpis"] = {
  open_actions: 0,
  overdue_actions: 0,
  open_escalations: 0,
  blocking_dependencies: 0,
  at_risk_items: 0,
  sla_adherence_pct: 100,
};

function LoadingRow({ colSpan }: { colSpan: number }) {
  return (
    <tr>
      <td colSpan={colSpan} className="py-8 text-center text-sm text-muted-foreground">
        Loading…
      </td>
    </tr>
  );
}

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
  onClientPublish,
  showResolve,
  resolveLabel = "Resolve",
  clientPublishLabel = "Client summary",
}: {
  canWrite: boolean;
  onEdit: () => void;
  onResolve?: () => void;
  onDelete?: () => void;
  onClientPublish?: () => void;
  showResolve?: boolean;
  resolveLabel?: string;
  clientPublishLabel?: string;
}) {
  if (!canWrite) return null;
  return (
    <div className="flex flex-wrap gap-1.5">
      <button
        type="button"
        className="rounded-md border border-border bg-card px-2 py-1 text-[10px] transition-colors hover:bg-elevated"
        onClick={onEdit}
      >
        Edit
      </button>
      {onClientPublish && (
        <button
          type="button"
          className="rounded-md border border-border bg-card px-2 py-1 text-[10px] transition-colors hover:bg-elevated"
          onClick={onClientPublish}
        >
          {clientPublishLabel}
        </button>
      )}
      {showResolve && onResolve && (
        <button
          type="button"
          className="rounded-md border border-border bg-card px-2 py-1 text-[10px] transition-colors hover:bg-elevated"
          onClick={onResolve}
        >
          {resolveLabel}
        </button>
      )}
      {onDelete && (
        <button
          type="button"
          className="rounded-md border border-destructive/40 bg-card px-2 py-1 text-[10px] text-destructive transition-colors hover:bg-destructive/5"
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
  const canPublish = canPublishCharter(role);
  const canManageSummary = canManageWeeklySummary(role);
  const showDelivery = canSeeDeliveryContext(role);
  const isClient = role === "client";
  const isReadOnly = role === "bsg_leadership";

  const [rawFilters, setRawFilters] = useState(emptyGovernanceFilters);
  const filters = useDebouncedValue(rawFilters, 250);
  const [dialog, setDialog] = useState<WorkflowDialogState>(null);
  const [confirm, setConfirm] = useState<ConfirmState>(null);
  const [clientPublish, setClientPublish] = useState<{
    id: string;
    title: string;
    summary: string;
    visible: boolean;
  } | null>(null);
  const [clientPublishBusy, setClientPublishBusy] = useState(false);
  const [selectedRow, setSelectedRow] = useState<GovernanceRegisterRow | null>(null);
  const [sheetOpen, setSheetOpen] = useState(false);
  const [promotingRiskId, setPromotingRiskId] = useState<string | null>(null);
  const [busyId, setBusyId] = useState<string | null>(null);
  const [activeTable, setActiveTable] = useState<GovernanceTableTab>(
    role === "client" ? "escalations" : "dependencies",
  );
  const [dependencyPage, setDependencyPage] = useState(1);
  const [actionPage, setActionPage] = useState(1);
  const [registerPage, setRegisterPage] = useState(1);
  const [escalationPage, setEscalationPage] = useState(1);
  const [governanceToolsTab, setGovernanceToolsTab] = useState<
    "agent" | "charters" | "weekly-summary"
  >("agent");
  const [filtersPopoverOpen, setFiltersPopoverOpen] = useState(false);
  const [analyticsProjectFilterOpen, setAnalyticsProjectFilterOpen] = useState(false);
  const [agentNeedsProjects, setAgentNeedsProjects] = useState(false);
  const [analyticsDeferredReady, setAnalyticsDeferredReady] = useState(false);
  const [analyticsDetailIdleReady, setAnalyticsDetailIdleReady] = useState(false);
  const [analyticsDetailInView, setAnalyticsDetailInView] = useState(false);
  const analyticsDetailSectionRef = useRef<HTMLDivElement>(null);

  const wantsRegisterData = activeTable === "register";
  const shouldEnableGovernanceRegister = wantsRegisterData;
  const wantsSheetDetail = sheetOpen && Boolean(selectedRow?.projectId);
  const sheetProjectId = selectedRow?.projectId;

  const dependencyListParams = useMemo(
    () =>
      backendListParams(filters, dependencyPage, {
        dependency_type: filters.dependencyType !== "all" ? filters.dependencyType : undefined,
        owner_id: filters.ownerId !== "all" ? filters.ownerId : undefined,
      }),
    [dependencyPage, filters],
  );
  const actionListParams = useMemo(
    () =>
      backendListParams(filters, actionPage, {
        owner_id: filters.ownerId !== "all" ? filters.ownerId : undefined,
      }),
    [actionPage, filters],
  );
  const escalationListParams = useMemo(
    () =>
      backendListParams(filters, escalationPage, {
        severity: filters.severity !== "all" ? filters.severity : undefined,
        assigned_to: filters.assigneeId !== "all" ? filters.assigneeId : undefined,
      }),
    [escalationPage, filters],
  );
  const registerListParams = useMemo(
    () =>
      backendListParams(filters, registerPage, {
        status: filters.scopeStatus !== "all" ? filters.scopeStatus : undefined,
      }),
    [filters, registerPage],
  );
  const dependenciesQuery = useQuery({
    ...governanceDependenciesQueryOptions(dependencyListParams),
    enabled: !isClient && activeTable === "dependencies",
    placeholderData: keepPreviousData,
  });
  const actionsQuery = useQuery({
    ...governanceActionsQueryOptions(actionListParams),
    enabled: !isClient && activeTable === "actions",
    placeholderData: keepPreviousData,
  });
  const escalationsQuery = useQuery({
    ...governanceEscalationsQueryOptions(escalationListParams),
    enabled: activeTable === "escalations",
    placeholderData: keepPreviousData,
  });
  const projectSheetQuery = useQuery({
    ...governanceProjectSheetQueryOptions(sheetProjectId ?? ""),
    enabled: wantsSheetDetail,
  });
  const registerQuery = useQuery({
    ...governanceRegisterQueryOptions(registerListParams),
    enabled: shouldEnableGovernanceRegister,
    placeholderData: keepPreviousData,
  });

  const primaryTableQuery = isClient ? escalationsQuery : dependenciesQuery;
  const showExecutiveAnalytics = !isClient;

  const bootstrapQuery = useQuery({
    ...governanceBootstrapQueryOptions,
    placeholderData: keepPreviousData,
  });

  const navigate = useNavigate({ from: GovernanceRoute.fullPath });
  const search = GovernanceRoute.useSearch();
  const [analyticsRangeDays] = useState(search.days ?? GOVERNANCE_DEFAULT_ANALYTICS_DAYS);
  const [analyticsProjectFilter, setAnalyticsProjectFilter] = useState<string | null>(
    search.projectId ?? null,
  );
  const [analyticsVerticalFilter, setAnalyticsVerticalFilter] = useState<string | null>(
    search.vertical ?? null,
  );

  useEffect(() => {
    void navigate({
      search: (prev) => ({
        ...prev,
        days: analyticsRangeDays,
        projectId: analyticsProjectFilter ?? undefined,
        vertical: analyticsVerticalFilter ?? undefined,
      }),
      replace: true,
    });
  }, [analyticsProjectFilter, analyticsRangeDays, analyticsVerticalFilter, navigate]);

  const analyticsFilters = useMemo(
    () => ({
      days: analyticsRangeDays,
      projectId: analyticsProjectFilter,
      vertical: analyticsVerticalFilter,
    }),
    [analyticsProjectFilter, analyticsRangeDays, analyticsVerticalFilter],
  );
  const analyticsSummaryQuery = useQuery({
    ...governanceAnalyticsSummaryQueryOptions(analyticsFilters),
    enabled: shouldEnableGovernanceAnalyticsSummary(showExecutiveAnalytics, analyticsDeferredReady),
    placeholderData: keepPreviousData,
  });
  const analyticsDetailEnabled = shouldEnableGovernanceAnalyticsDetail({
    showExecutiveAnalytics,
    analyticsDeferredReady,
    summaryReady: analyticsSummaryQuery.isSuccess,
    detailTriggerReady: analyticsDetailIdleReady || analyticsDetailInView,
  });
  const analyticsDetailQuery = useQuery({
    ...governanceAnalyticsDetailQueryOptions(analyticsFilters),
    enabled: analyticsDetailEnabled,
    placeholderData: keepPreviousData,
  });
  const mergedAnalytics = useMemo(() => {
    if (!analyticsSummaryQuery.data) return null;
    return mergeGovernanceAnalytics(analyticsSummaryQuery.data, analyticsDetailQuery.data);
  }, [analyticsDetailQuery.data, analyticsSummaryQuery.data]);
  const portfolioQuery = useQuery({
    ...deliveryPortfolioQueryOptions,
    enabled: showDelivery && activeTable === "register",
    placeholderData: keepPreviousData,
  });
  const needsProjects = shouldEnableGovernanceProjects({
    filtersOpen: filtersPopoverOpen || analyticsProjectFilterOpen,
    dialogOpen: Boolean(dialog),
    agentNeedsProjects: agentNeedsProjects && governanceToolsTab === "agent",
    chartersTabActive: governanceToolsTab === "charters",
  });
  const projectsQuery = useQuery({
    ...projectsQueryOptions,
    enabled: needsProjects,
  });
  const analyticsProjectOptions = useMemo(() => {
    const names = new Map<string, string>();
    for (const row of mergedAnalytics?.portfolio_risk_ranking ?? []) {
      names.set(row.project_id, row.project_name);
    }
    for (const project of projectsQuery.data ?? []) {
      names.set(project.id, project.name);
    }
    return Array.from(names, ([id, name]) => ({ id, name })).sort((left, right) =>
      left.name.localeCompare(right.name),
    );
  }, [mergedAnalytics?.portfolio_risk_ranking, projectsQuery.data]);
  const analyticsVerticalOptions = useMemo(() => {
    const values = new Set<string>();
    for (const project of projectsQuery.data ?? []) {
      if (project.vertical) values.add(project.vertical);
    }
    for (const row of mergedAnalytics?.portfolio_risk_ranking ?? []) {
      if (row.vertical) values.add(row.vertical);
    }
    return [...values].sort();
  }, [mergedAnalytics?.portfolio_risk_ranking, projectsQuery.data]);
  const usersQuery = useQuery({
    queryKey: ["users"],
    queryFn: listUsers,
    enabled: canWrite && Boolean(dialog),
    staleTime: 10 * 60 * 1000,
  });

  useEffect(() => {
    if (!showExecutiveAnalytics) {
      setAnalyticsDeferredReady(false);
      setAnalyticsDetailIdleReady(false);
      setAnalyticsDetailInView(false);
      return;
    }

    const timer = window.setTimeout(
      () => setAnalyticsDeferredReady(true),
      GOVERNANCE_ANALYTICS_DEFER_MS,
    );
    return () => window.clearTimeout(timer);
  }, [showExecutiveAnalytics]);

  useEffect(() => {
    if (!showExecutiveAnalytics || !analyticsSummaryQuery.isSuccess) {
      setAnalyticsDetailIdleReady(false);
      return;
    }

    const idleWindow = window as Window & {
      requestIdleCallback?: (callback: IdleRequestCallback, options?: IdleRequestOptions) => number;
      cancelIdleCallback?: (handle: number) => void;
    };

    if (idleWindow.requestIdleCallback) {
      const idleId = idleWindow.requestIdleCallback(() => setAnalyticsDetailIdleReady(true), {
        timeout: GOVERNANCE_ANALYTICS_DETAIL_IDLE_MS,
      });
      return () => idleWindow.cancelIdleCallback?.(idleId);
    }

    const timer = window.setTimeout(
      () => setAnalyticsDetailIdleReady(true),
      GOVERNANCE_ANALYTICS_DETAIL_IDLE_MS,
    );
    return () => window.clearTimeout(timer);
  }, [analyticsRangeDays, analyticsSummaryQuery.isSuccess, showExecutiveAnalytics]);

  useEffect(() => {
    if (!showExecutiveAnalytics) return;
    const node = analyticsDetailSectionRef.current;
    if (!node || typeof IntersectionObserver === "undefined") return;

    const observer = new IntersectionObserver(
      (entries) => {
        if (entries.some((entry) => entry.isIntersecting)) {
          setAnalyticsDetailInView(true);
        }
      },
      { rootMargin: "120px" },
    );
    observer.observe(node);
    return () => observer.disconnect();
  }, [showExecutiveAnalytics, mergedAnalytics]);

  const analyticsSummaryLoading = analyticsSummaryQuery.isLoading && !analyticsSummaryQuery.data;

  const bootstrapKpis = bootstrapQuery.data?.kpis ?? EMPTY_GOVERNANCE_KPIS;

  const data = useMemo<GovernanceBootstrap>(() => {
    const sheet = wantsSheetDetail ? projectSheetQuery.data : undefined;
    return {
      kpis: bootstrapKpis,
      dependencies: sheet?.dependencies.items ?? dependenciesQuery.data?.items ?? [],
      actions: sheet?.actions.items ?? actionsQuery.data?.items ?? [],
      escalations: sheet?.escalations.items ?? escalationsQuery.data?.items ?? [],
      scope_states: sheet?.scope ? [sheet.scope] : [],
    };
  }, [
    actionsQuery.data,
    dependenciesQuery.data,
    escalationsQuery.data,
    bootstrapKpis,
    projectSheetQuery.data,
    wantsSheetDetail,
  ]);

  const projectOptions = useMemo(
    () =>
      (projectsQuery.data ?? []).map((p) => ({
        value: p.id,
        label: p.name,
      })),
    [projectsQuery.data],
  );
  const prepareChartersTab = () => {
    preloadProjectChartersPanel();
    void queryClient
      .ensureQueryData(projectsQueryOptions)
      .then((projects) => {
        const firstProject = projects[0];
        if (!firstProject) return;
        return queryClient.prefetchQuery(
          governanceProjectChartersPanelQueryOptions({
            projectId: firstProject.id,
            limit: 5,
            offset: 0,
          }),
        );
      })
      .catch(() => undefined);
  };

  const prepareWeeklySummaryTab = () => {
    void queryClient.prefetchQuery(governanceWeeklySummaryQueryOptions);
  };

  const userOptions = useMemo(
    () =>
      (usersQuery.data ?? []).map((u) => ({
        value: u.id,
        label: u.full_name || u.email,
      })),
    [usersQuery.data],
  );

  const userNameById = useMemo(
    () => new Map(userOptions.map((userOption) => [userOption.value, userOption.label])),
    [userOptions],
  );

  const updateGovernanceDataCache = (
    updater: (current: GovernanceBootstrap) => GovernanceBootstrap,
    affectedProjectId?: string | null,
    affectedSection?: "dependencies" | "actions" | "escalations" | "scope-states",
  ) => {
    const next = updater(data);
    if (!wantsSheetDetail) {
      queryClient.setQueryData<PaginatedGovernanceList<ProjectDependencyListItem>>(
        queryKeys.governanceDependencies(dependencyListParams),
        {
          ...(dependenciesQuery.data ?? emptyPaginatedList<ProjectDependencyListItem>()),
          items: next.dependencies,
        },
      );
      queryClient.setQueryData<PaginatedGovernanceList<GovernanceActionListItem>>(
        queryKeys.governanceActions(actionListParams),
        {
          ...(actionsQuery.data ?? emptyPaginatedList<GovernanceActionListItem>()),
          items: next.actions,
        },
      );
      queryClient.setQueryData<PaginatedGovernanceList<GovernanceEscalationListItem>>(
        queryKeys.governanceEscalations(escalationListParams),
        {
          ...(escalationsQuery.data ?? emptyPaginatedList<GovernanceEscalationListItem>()),
          items: next.escalations,
        },
      );
    } else if (affectedSection) {
      void queryClient.invalidateQueries({ queryKey: ["governance", affectedSection] });
    }
    void queryClient.invalidateQueries({ queryKey: queryKeys.governanceBootstrap });
    if (affectedProjectId) {
      void invalidateGovernanceProjectSheet(queryClient, affectedProjectId);
    }
  };

  const hydrateDependency = (
    next: ProjectDependency,
    current?: ProjectDependencyListItem,
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

  const hydrateAction = (
    next: GovernanceAction,
    current?: GovernanceActionListItem,
  ): GovernanceAction => ({
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
    current?: GovernanceEscalationListItem,
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
    return (registerQuery.data?.items ?? []).map((row) =>
      mapRegisterApiRow(row, portfolioQuery.data),
    );
  }, [portfolioQuery.data, registerQuery.data?.items]);

  const dynamicKpis = useMemo<GovernanceBootstrap["kpis"]>(() => {
    if (registerRows.length === 0 && !registerQuery.data) {
      return bootstrapKpis;
    }
    const openActions = registerRows.reduce((sum, row) => sum + row.openActions, 0);
    return {
      open_actions: openActions,
      overdue_actions: bootstrapKpis.overdue_actions || openActions,
      open_escalations: registerRows.reduce((sum, row) => sum + row.openEscalations, 0),
      blocking_dependencies: registerRows.reduce((sum, row) => sum + row.blockingDependencies, 0),
      at_risk_items: registerRows.filter((row) => row.health !== "Green").length,
      sla_adherence_pct: bootstrapKpis.sla_adherence_pct,
    };
  }, [bootstrapKpis, registerQuery.data, registerRows]);

  const projectNameById = useMemo(() => {
    const fromRows = collectProjectNamesFromGovernanceRows([
      ...(dependenciesQuery.data?.items ?? []),
      ...(actionsQuery.data?.items ?? []),
      ...(escalationsQuery.data?.items ?? []),
    ]);
    for (const row of registerRows) {
      fromRows.set(row.projectId, row.projectName);
    }
    for (const project of projectsQuery.data ?? []) {
      fromRows.set(project.id, project.name);
    }
    return fromRows;
  }, [
    actionsQuery.data?.items,
    dependenciesQuery.data?.items,
    escalationsQuery.data?.items,
    projectsQuery.data,
    registerRows,
  ]);

  const filteredDependencies = data.dependencies;
  const filteredActions = data.actions;
  const filteredEscalations = data.escalations;
  const tabTotals = resolveGovernanceTabTotals({
    bootstrapKpis: bootstrapQuery.data?.kpis,
    dependenciesTotal: dependenciesQuery.data?.total,
    actionsTotal: actionsQuery.data?.total,
    escalationsTotal: escalationsQuery.data?.total,
    registerTotal: registerQuery.data?.total,
  });
  const dependencyTotal = tabTotals.dependencies;
  const actionTotal = tabTotals.actions;
  const escalationTotal = tabTotals.escalations;
  const registerTotal = tabTotals.register;

  const visibleTableTabs = useMemo(
    () =>
      (
        [
          !isClient && {
            value: "dependencies" as const,
            label: "Dependency Tracker",
            count: dependencyTotal,
          },
          !isClient && {
            value: "actions" as const,
            label: "Governance Actions",
            count: actionTotal,
          },
          {
            value: "register" as const,
            label: "Governance Register",
            count: registerTotal,
          },
          {
            value: "escalations" as const,
            label: "Escalation Register",
            count: escalationTotal,
          },
        ] satisfies Array<false | { value: GovernanceTableTab; label: string; count: number }>
      ).filter(Boolean) as Array<{ value: GovernanceTableTab; label: string; count: number }>,
    [actionTotal, dependencyTotal, escalationTotal, isClient, registerTotal],
  );
  const selectedTable = visibleTableTabs.some((tab) => tab.value === activeTable)
    ? activeTable
    : (visibleTableTabs[0]?.value ?? "register");
  const pagedDependencies = filteredDependencies;
  const pagedActions = filteredActions;
  const pagedRegisterRows = registerRows;
  const pagedEscalations = filteredEscalations;

  useEffect(() => {
    setDependencyPage(1);
    setActionPage(1);
    setRegisterPage(1);
    setEscalationPage(1);
  }, [filters]);

  const refetchDashboardData = async () => {
    await bootstrapQuery.refetch();
    if (!isClient && activeTable === "dependencies") {
      await dependenciesQuery.refetch();
    }
    if (!isClient && activeTable === "actions") {
      await actionsQuery.refetch();
    }
    if (activeTable === "escalations") {
      await escalationsQuery.refetch();
    }
    if (wantsRegisterData) {
      await registerQuery.refetch();
    }
    if (wantsSheetDetail) {
      await projectSheetQuery.refetch();
    }
    if (showDelivery && activeTable === "register") {
      await portfolioQuery.refetch();
    }
    if (showExecutiveAnalytics) {
      await Promise.all([analyticsSummaryQuery.refetch(), analyticsDetailQuery.refetch()]);
    }
  };

  const runConfirm = async () => {
    if (!confirm) return;
    const affectedProjectId = [...data.dependencies, ...data.actions, ...data.escalations].find(
      (row) => row.id === confirm.id,
    )?.project_id;
    let committed = false;
    setBusyId(confirm.id);
    try {
      if (confirm.kind === "resolve-dependency") {
        const dependency = await resolveDependency(confirm.id);
        updateGovernanceDataCache((current) => {
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
        committed = true;
      } else if (confirm.kind === "resolve-escalation") {
        const escalation = await updateGovernanceEscalation(confirm.id, { status: "resolved" });
        updateGovernanceDataCache((current) => {
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
        committed = true;
      } else if (confirm.kind === "complete-action") {
        const action = await updateGovernanceAction(confirm.id, { status: "completed" });
        updateGovernanceDataCache((current) => {
          const existing = current.actions.find((row) => row.id === action.id);
          return {
            ...current,
            actions: replaceOrAddById(current.actions, hydrateAction(action, existing)),
          };
        });
        toast.success("Action completed.");
        committed = true;
      } else if (confirm.kind === "delete-dependency") {
        await deleteDependency(confirm.id);
        updateGovernanceDataCache((current) => ({
          ...current,
          dependencies: current.dependencies.filter((row) => row.id !== confirm.id),
        }));
        toast.success("Dependency archived.");
        committed = true;
      } else if (confirm.kind === "delete-escalation") {
        await deleteGovernanceEscalation(confirm.id);
        updateGovernanceDataCache((current) => ({
          ...current,
          escalations: current.escalations.filter((row) => row.id !== confirm.id),
        }));
        toast.success("Escalation archived.");
        committed = true;
      } else if (confirm.kind === "delete-action") {
        await deleteGovernanceAction(confirm.id);
        updateGovernanceDataCache((current) => ({
          ...current,
          actions: current.actions.filter((row) => row.id !== confirm.id),
        }));
        toast.success("Action archived.");
        committed = true;
      }
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Action failed.");
    } finally {
      if (committed && affectedProjectId) {
        void invalidateGovernanceProjectSheet(queryClient, affectedProjectId);
      }
      setBusyId(null);
      setConfirm(null);
    }
  };

  const handlePromoteRisk = async (riskAlertId: string) => {
    setPromotingRiskId(riskAlertId);
    try {
      const escalation = await promoteRiskAlertToEscalation(riskAlertId);
      updateGovernanceDataCache(
        (current) => ({
          ...current,
          escalations: replaceOrAddById(current.escalations, hydrateEscalation(escalation)),
        }),
        escalation.project_id,
        "escalations",
      );
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

  const openAnalyticsProjectSheet = (projectId: string) => {
    const existingRow = registerRows.find((row) => row.projectId === projectId);
    if (existingRow) {
      openProjectSheet(existingRow);
      return;
    }

    const project =
      mergedAnalytics?.project_health.find((row) => row.project_id === projectId) ??
      mergedAnalytics?.portfolio_risk_ranking.find((row) => row.project_id === projectId);
    if (!project) return;

    setSelectedRow({
      projectId: project.project_id,
      projectName: project.project_name,
      scopeStatus: null,
      scopeVersion: null,
      openDependencies: project.open_dependencies,
      blockingDependencies: project.blocking_dependencies,
      openActions: project.overdue_actions,
      openEscalations: project.open_escalations,
      health: project.score < 40 ? "Red" : project.score < 75 ? "Amber" : "Green",
      deliveryTrafficLight:
        project.delivery_traffic_light === "green" ||
        project.delivery_traffic_light === "yellow" ||
        project.delivery_traffic_light === "red"
          ? project.delivery_traffic_light
          : null,
      deliveryConfidence: project.delivery_confidence,
      atRiskMilestones: 0,
    });
    setSheetOpen(true);
  };

  if (primaryTableQuery.isError && !primaryTableQuery.data) {
    return (
      <Card>
        <SectionError
          message={
            primaryTableQuery.error instanceof Error
              ? primaryTableQuery.error.message
              : "Unable to load governance data."
          }
          onRetry={() => void refetchDashboardData()}
        />
      </Card>
    );
  }

  return (
    <div className="governance-no-shadow space-y-5">
      {isReadOnly && (
        <div className="rounded-md border border-border bg-elevated px-3 py-2 text-xs text-muted-foreground">
          Read-only portfolio governance view.
        </div>
      )}
      {isClient && (
        <div className="rounded-md border border-border bg-elevated px-3 py-2 text-xs text-muted-foreground">
          Client-safe escalation visibility only. You see published summaries for your assigned
          projects; internal dependencies, actions, and draft narratives stay hidden.
        </div>
      )}
      {showExecutiveAnalytics && (
        <>
          {analyticsSummaryQuery.isError && !mergedAnalytics ? (
            <Card>
              <SectionError
                message={
                  analyticsSummaryQuery.error instanceof Error
                    ? analyticsSummaryQuery.error.message
                    : "Unable to load governance analytics summary."
                }
                onRetry={() => void analyticsSummaryQuery.refetch()}
              />
            </Card>
          ) : (
            <Suspense fallback={<ExecutiveDashboardFallback />}>
              <LazyExecutiveGovernanceDashboard
                analytics={mergedAnalytics}
                kpis={dynamicKpis}
                summaryLoading={analyticsSummaryLoading}
                projectFilter={analyticsProjectFilter}
                onProjectFilterChange={setAnalyticsProjectFilter}
                onProjectFilterOpenChange={setAnalyticsProjectFilterOpen}
                verticalFilter={analyticsVerticalFilter}
                onVerticalFilterChange={setAnalyticsVerticalFilter}
                projectOptions={analyticsProjectOptions}
                verticalOptions={analyticsVerticalOptions}
                onOpenProject={openAnalyticsProjectSheet}
                detailSectionRef={analyticsDetailSectionRef}
                canWrite={!isClient}
                recommendationsEnabled={analyticsDetailInView}
              />
            </Suspense>
          )}
        </>
      )}

      <div className="flex flex-wrap items-center gap-2">
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
        <div className="min-w-0 flex-1">
          <GovernanceFiltersBar
            filters={rawFilters}
            onChange={setRawFilters}
            projects={projectOptions}
            users={userOptions}
            showInternalFilters={!isClient}
            onFiltersOpenChange={setFiltersPopoverOpen}
          />
        </div>
      </div>

      <div className="space-y-5">
        <Tabs
          value={selectedTable}
          onValueChange={(value) => setActiveTable(value as GovernanceTableTab)}
          className="space-y-3"
        >
          <TabsList className="h-auto max-w-full flex-wrap justify-start gap-1 overflow-x-auto rounded-xl border border-border bg-card p-1">
            {visibleTableTabs.map((tab) => (
              <TabsTrigger
                key={tab.value}
                value={tab.value}
                className="shrink-0 gap-2 rounded-lg px-3 text-xs"
              >
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
                {dependenciesQuery.isFetching && dependenciesQuery.data && (
                  <div className="mb-2 flex items-center gap-2 text-[10px] text-muted-foreground">
                    <RefreshCw className="h-3 w-3 animate-spin" />
                    Refreshing dependencies...
                  </div>
                )}
                <div className="space-y-2 md:hidden">
                  {dependenciesQuery.isLoading && !dependenciesQuery.data ? (
                    <div className="flex h-40 items-center justify-center text-sm text-muted-foreground">
                      Loading dependencies...
                    </div>
                  ) : filteredDependencies.length === 0 ? (
                    <div className="flex h-40 items-center justify-center text-sm text-muted-foreground">
                      No dependencies match filters.
                    </div>
                  ) : (
                    pagedDependencies.map((dep) => (
                      <article
                        key={dep.id}
                        className={cn(
                          "rounded-lg border border-border p-3",
                          dependencyRowClass(dep),
                        )}
                      >
                        <div className="flex items-start justify-between gap-3">
                          <div className="min-w-0">
                            <p className="font-medium leading-5">Dependency · {dep.title}</p>
                            {isCriticalPathDependency(dep) && (
                              <span className="mt-1 inline-flex rounded border border-[color:var(--danger)]/40 bg-[color:var(--danger)]/10 px-1.5 py-0.5 text-[10px] font-medium uppercase tracking-wide text-[color:var(--danger)]">
                                Critical path
                              </span>
                            )}
                          </div>
                          <StatusPill status={formatDependencyStatus(dep.status)} />
                        </div>
                        <dl className="mt-3 grid grid-cols-2 gap-x-4 gap-y-2 text-xs">
                          <div>
                            <dt className="text-[10px] uppercase tracking-wide text-muted-foreground">
                              Project
                            </dt>
                            <dd className="mt-0.5 truncate">{dep.project_name ?? "—"}</dd>
                          </div>
                          <div>
                            <dt className="text-[10px] uppercase tracking-wide text-muted-foreground">
                              Due
                            </dt>
                            <dd className="mt-0.5 text-muted-foreground">
                              {formatDate(dep.due_date)}
                            </dd>
                          </div>
                          <div>
                            <dt className="text-[10px] uppercase tracking-wide text-muted-foreground">
                              Type
                            </dt>
                            <dd className="mt-0.5 text-muted-foreground">
                              {formatDependencyType(dep.dependency_type)}
                            </dd>
                          </div>
                          <div>
                            <dt className="text-[10px] uppercase tracking-wide text-muted-foreground">
                              Owner
                            </dt>
                            <dd className="mt-0.5 truncate text-muted-foreground">
                              {dep.owner_name ?? "—"}
                            </dd>
                          </div>
                        </dl>
                        {dep.overdue_days > 0 && (
                          <p className="mt-3 text-xs font-medium text-[color:var(--danger)]">
                            {dep.overdue_days}d overdue
                          </p>
                        )}
                        {canWrite && (
                          <div className="mt-3 border-t border-border/60 pt-2">
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
                          </div>
                        )}
                      </article>
                    ))
                  )}
                </div>
                <div className={`${GOVERNANCE_TABLE_VIEWPORT_CLASS} hidden md:block`}>
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
                      {dependenciesQuery.isLoading && !dependenciesQuery.data ? (
                        <LoadingRow colSpan={canWrite ? 8 : 7} />
                      ) : filteredDependencies.length === 0 ? (
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
                            <td className="py-2.5 pr-3 font-medium">
                              <div className="flex flex-wrap items-center gap-1.5">
                                <span>{dep.title}</span>
                                {isCriticalPathDependency(dep) && (
                                  <span className="rounded border border-[color:var(--danger)]/40 bg-[color:var(--danger)]/10 px-1.5 py-0.5 text-[10px] font-medium uppercase tracking-wide text-[color:var(--danger)]">
                                    Critical path
                                  </span>
                                )}
                              </div>
                            </td>
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
                  totalRows={dependencyTotal}
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
                {actionsQuery.isFetching && actionsQuery.data && (
                  <div className="mb-2 flex items-center gap-2 text-[10px] text-muted-foreground">
                    <RefreshCw className="h-3 w-3 animate-spin" />
                    Refreshing actions...
                  </div>
                )}
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
                      {actionsQuery.isLoading && !actionsQuery.data ? (
                        <LoadingRow colSpan={canWrite ? 6 : 5} />
                      ) : filteredActions.length === 0 ? (
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
                  totalRows={actionTotal}
                  onPageChange={setActionPage}
                />
              </Card>
            )}
          </TabsContent>

          <TabsContent value="register" className="mt-0">
            {selectedTable === "register" && (
              <Card>
                <SectionHeader title="Governance Register" sub="Click a project for details" />
                {(registerQuery.isFetching || portfolioQuery.isFetching) &&
                  (registerQuery.data || portfolioQuery.data) && (
                    <div className="mb-2 flex items-center gap-2 text-[10px] text-muted-foreground">
                      <RefreshCw className="h-3 w-3 animate-spin" />
                      Refreshing register...
                    </div>
                  )}
                <div className="space-y-2 md:hidden">
                  {registerQuery.isLoading && !registerQuery.data ? (
                    <div className="flex h-40 items-center justify-center text-sm text-muted-foreground">
                      Loading register...
                    </div>
                  ) : registerRows.length === 0 ? (
                    <div className="flex h-40 items-center justify-center text-sm text-muted-foreground">
                      No governance register entries match filters.
                    </div>
                  ) : (
                    pagedRegisterRows.map((row) => (
                      <button
                        key={row.projectId}
                        type="button"
                        className="w-full rounded-lg border border-border bg-card p-3 text-left transition-colors hover:bg-elevated"
                        onClick={() => openProjectSheet(row)}
                      >
                        <div className="flex items-start justify-between gap-3">
                          <div className="min-w-0">
                            <p className="truncate font-medium">Project · {row.projectName}</p>
                            <p className="mt-1 text-xs text-muted-foreground">
                              {row.scopeVersion
                                ? `Version ${row.scopeVersion}`
                                : "No scope version"}
                            </p>
                          </div>
                          <StatusPill status={row.health} />
                        </div>
                        <div className="mt-3 grid grid-cols-2 gap-2 text-xs sm:grid-cols-4">
                          <div>
                            <p className="text-[10px] uppercase tracking-wide text-muted-foreground">
                              Scope
                            </p>
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
                          </div>
                          {!isClient && (
                            <div>
                              <p className="text-[10px] uppercase tracking-wide text-muted-foreground">
                                Dependencies
                              </p>
                              <p className="mt-1">{row.openDependencies} open</p>
                            </div>
                          )}
                          {!isClient && (
                            <div>
                              <p className="text-[10px] uppercase tracking-wide text-muted-foreground">
                                Actions
                              </p>
                              <p className="mt-1">{row.openActions}</p>
                            </div>
                          )}
                          <div>
                            <p className="text-[10px] uppercase tracking-wide text-muted-foreground">
                              Delivery
                            </p>
                            {showDelivery ? (
                              <div className="mt-1 space-y-1">
                                <StatusPill
                                  status={deliveryTrafficLabel(row.deliveryTrafficLight)}
                                />
                                {row.deliveryConfidence !== null && (
                                  <p className="text-[10px] text-muted-foreground">
                                    {row.deliveryConfidence}% confidence
                                  </p>
                                )}
                              </div>
                            ) : (
                              <p className="mt-1 text-muted-foreground">—</p>
                            )}
                          </div>
                        </div>
                        <p className="mt-3 text-[11px] text-muted-foreground">
                          Click to view details →
                        </p>
                      </button>
                    ))
                  )}
                </div>
                <div className={`${GOVERNANCE_TABLE_VIEWPORT_CLASS} hidden md:block`}>
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
                      {registerQuery.isLoading && !registerQuery.data ? (
                        <LoadingRow
                          colSpan={isClient ? (showDelivery ? 5 : 4) : showDelivery ? 8 : 7}
                        />
                      ) : registerRows.length === 0 ? (
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
                  totalRows={registerTotal}
                  onPageChange={setRegisterPage}
                />
              </Card>
            )}
          </TabsContent>

          <TabsContent value="escalations" className="mt-0">
            {selectedTable === "escalations" && (
              <Card>
                <SectionHeader title="Escalation Register" />
                {escalationsQuery.isFetching && escalationsQuery.data && (
                  <div className="mb-2 flex items-center gap-2 text-[10px] text-muted-foreground">
                    <RefreshCw className="h-3 w-3 animate-spin" />
                    Refreshing escalations...
                  </div>
                )}
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
                      {escalationsQuery.isLoading && !escalationsQuery.data ? (
                        <LoadingRow colSpan={isClient ? 7 : canWrite ? 9 : 8} />
                      ) : filteredEscalations.length === 0 ? (
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
                            <td className="py-2.5 pr-3 font-medium">
                              <div className="space-y-1">
                                <div className="flex flex-wrap items-center gap-1.5">
                                  <span>{esc.title}</span>
                                  {!isClient && esc.client_visible && (
                                    <span className="rounded border border-border px-1.5 py-0.5 text-[10px] font-medium uppercase tracking-wide text-muted-foreground">
                                      Client visible
                                    </span>
                                  )}
                                </div>
                                {isClient && esc.description && (
                                  <p className="text-[11px] font-normal text-muted-foreground">
                                    {esc.description}
                                  </p>
                                )}
                              </div>
                            </td>
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
                                    : esc.source_type === "quality_risk"
                                      ? "Quality risk"
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
                                  onClientPublish={() =>
                                    setClientPublish({
                                      id: esc.id,
                                      title: esc.title,
                                      summary: esc.client_summary ?? esc.description ?? "",
                                      visible: Boolean(esc.client_visible),
                                    })
                                  }
                                  clientPublishLabel={
                                    esc.client_visible ? "Update client" : "Publish client"
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
                  totalRows={escalationTotal}
                  onPageChange={setEscalationPage}
                />
              </Card>
            )}
          </TabsContent>
        </Tabs>
      </div>

      <div className="space-y-3">
        <Tabs
          value={governanceToolsTab}
          onValueChange={(value) =>
            setGovernanceToolsTab(value as "agent" | "charters" | "weekly-summary")
          }
        >
          <TabsList className="h-auto flex-wrap justify-start gap-1 bg-elevated">
            <TabsTrigger value="agent" className="text-xs">
              Ask Governance Agent
            </TabsTrigger>
            <TabsTrigger
              value="charters"
              className="text-xs"
              onFocus={prepareChartersTab}
              onMouseEnter={prepareChartersTab}
            >
              Project Charters
            </TabsTrigger>
            <TabsTrigger
              value="weekly-summary"
              className="text-xs"
              onFocus={prepareWeeklySummaryTab}
              onMouseEnter={prepareWeeklySummaryTab}
            >
              Governance This Week
            </TabsTrigger>
          </TabsList>

          <TabsContent value="agent" className="mt-3">
            <Suspense fallback={<GovernanceToolsPanelFallback />}>
              <LazyAskGovernanceAgentPanel
                projects={projectOptions}
                onNeedsProjects={() => setAgentNeedsProjects(true)}
              />
            </Suspense>
          </TabsContent>

          <TabsContent value="charters" className="mt-3">
            {projectsQuery.isFetching && projectOptions.length === 0 ? (
              <ProjectChartersPanelFallback />
            ) : (
              <Suspense fallback={<ProjectChartersPanelFallback />}>
                <LazyProjectChartersPanel
                  projects={projectOptions}
                  canWrite={canWrite}
                  canPublish={canPublish}
                  isClient={isClient}
                  isReadOnly={isReadOnly}
                  loadCharters
                />
              </Suspense>
            )}
          </TabsContent>

          <TabsContent value="weekly-summary" className="mt-3">
            <GovernanceWeeklySummaryPanel canManage={canManageSummary} />
          </TabsContent>
        </Tabs>
      </div>

      {dialog && (
        <Suspense fallback={null}>
          <LazyGovernanceWorkflowDialogs
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
              updateGovernanceDataCache(
                (current) => {
                  const existing = current.dependencies.find((row) => row.id === dependency.id);
                  return {
                    ...current,
                    dependencies: replaceOrAddById(
                      current.dependencies,
                      hydrateDependency(dependency, existing),
                    ),
                  };
                },
                projectId,
                "dependencies",
              );
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
              updateGovernanceDataCache(
                (current) => {
                  const existing = current.actions.find((row) => row.id === action.id);
                  return {
                    ...current,
                    actions: replaceOrAddById(current.actions, hydrateAction(action, existing)),
                  };
                },
                projectId,
                "actions",
              );
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
              updateGovernanceDataCache(
                (current) => {
                  const existing = current.escalations.find((row) => row.id === escalation.id);
                  return {
                    ...current,
                    escalations: replaceOrAddById(
                      current.escalations,
                      hydrateEscalation(escalation, existing),
                    ),
                  };
                },
                projectId,
                "escalations",
              );
            }}
            onSaveScope={async ({ projectId, values }) => {
              const scope = await updateProjectScope(projectId, {
                scope_status: values.scope_status as GovernanceScopeStatus,
                version_label: values.version_label ?? undefined,
                notes: values.notes,
                linked_charter_document_id: values.linked_charter_document_id,
              });
              toast.success("Scope updated.");
              updateGovernanceDataCache(
                (current) => ({
                  ...current,
                  scope_states: current.scope_states.some((row) => row.id === scope.id)
                    ? current.scope_states.map((row) => (row.id === scope.id ? scope : row))
                    : replaceOrAddById(current.scope_states, scope),
                }),
                projectId,
                "scope-states",
              );
            }}
          />
        </Suspense>
      )}

      <ProjectGovernanceSheet
        open={sheetOpen}
        onClose={() => setSheetOpen(false)}
        row={selectedRow}
        data={projectSheetQuery.data}
        isLoading={projectSheetQuery.isLoading}
        error={projectSheetQuery.error}
        onRetry={() => void projectSheetQuery.refetch()}
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
        onViewAll={(section) => {
          if (selectedRow) {
            setRawFilters((current) => ({ ...current, projectId: selectedRow.projectId }));
          }
          setActiveTable(section);
          setSheetOpen(false);
        }}
        promotingRiskId={promotingRiskId}
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

      <Dialog
        open={Boolean(clientPublish)}
        onOpenChange={(open) => !open && !clientPublishBusy && setClientPublish(null)}
      >
        <DialogContent className="governance-no-shadow sm:max-w-lg">
          <DialogHeader>
            <DialogTitle>Client escalation summary</DialogTitle>
            <DialogDescription>
              Publish an approved, client-safe narrative for "{clientPublish?.title}". Internal
              notes stay hidden until you publish.
            </DialogDescription>
          </DialogHeader>
          <Textarea
            rows={5}
            value={clientPublish?.summary ?? ""}
            onChange={(event) =>
              setClientPublish((current) =>
                current ? { ...current, summary: event.target.value } : current,
              )
            }
            placeholder="Client-facing summary…"
          />
          <DialogFooter className="gap-2 sm:gap-0">
            {clientPublish?.visible && (
              <Button
                type="button"
                variant="outline"
                className="shadow-none"
                disabled={clientPublishBusy}
                onClick={() => {
                  void (async () => {
                    if (!clientPublish) return;
                    setClientPublishBusy(true);
                    try {
                      const escalation = await publishClientEscalationSummary(clientPublish.id, {
                        client_summary: clientPublish.summary,
                        client_visible: false,
                      });
                      updateGovernanceDataCache(
                        (current) => {
                          const existing = current.escalations.find(
                            (row) => row.id === escalation.id,
                          );
                          return {
                            ...current,
                            escalations: replaceOrAddById(
                              current.escalations,
                              hydrateEscalation(escalation, existing),
                            ),
                          };
                        },
                        escalation.project_id,
                        "escalations",
                      );
                      toast.success("Escalation unpublished from client view.");
                      setClientPublish(null);
                    } catch (error) {
                      toast.error(
                        error instanceof Error ? error.message : "Unable to unpublish summary.",
                      );
                    } finally {
                      setClientPublishBusy(false);
                    }
                  })();
                }}
              >
                Unpublish
              </Button>
            )}
            <Button
              type="button"
              className="shadow-none"
              disabled={clientPublishBusy || !clientPublish?.summary.trim()}
              onClick={() => {
                void (async () => {
                  if (!clientPublish) return;
                  setClientPublishBusy(true);
                  try {
                    const escalation = await publishClientEscalationSummary(clientPublish.id, {
                      client_summary: clientPublish.summary.trim(),
                      client_visible: true,
                    });
                    updateGovernanceDataCache(
                      (current) => {
                        const existing = current.escalations.find(
                          (row) => row.id === escalation.id,
                        );
                        return {
                          ...current,
                          escalations: replaceOrAddById(
                            current.escalations,
                            hydrateEscalation(escalation, existing),
                          ),
                        };
                      },
                      escalation.project_id,
                      "escalations",
                    );
                    toast.success("Client escalation summary published.");
                    setClientPublish(null);
                  } catch (error) {
                    toast.error(
                      error instanceof Error ? error.message : "Unable to publish summary.",
                    );
                  } finally {
                    setClientPublishBusy(false);
                  }
                })();
              }}
            >
              {clientPublishBusy ? "Saving…" : "Publish to client"}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}
