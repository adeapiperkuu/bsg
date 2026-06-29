import { useQuery, useQueryClient } from "@tanstack/react-query";
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
import { ProjectGovernanceSheet } from "@/features/governance/ProjectGovernanceSheet";
import {
  GovernanceWorkflowDialogs,
  type WorkflowDialogState,
} from "@/features/governance/GovernanceWorkflowDialogs";
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
  overdueActions,
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
  GovernanceDependencyType,
  GovernanceEscalationSeverity,
  GovernanceEscalationSourceType,
  GovernanceScopeStatus,
} from "@/types/governance";

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

type ConfirmState =
  | {
      kind:
        | "resolve-dependency"
        | "resolve-escalation"
        | "complete-action"
        | "delete-dependency"
        | "delete-escalation"
        | "delete-action";
      id: string;
      label: string;
    }
  | null;

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
      <Button type="button" variant="outline" size="sm" onClick={onRetry}>
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
      <button type="button" className="rounded border border-border px-2 py-0.5 text-[10px]" onClick={onEdit}>
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

export function GovernanceDashboard() {
  const queryClient = useQueryClient();
  const user = useAuthStore((state) => state.user);
  const role = user?.role;
  const canWrite = canWriteGovernance(role);
  const showDelivery = canSeeDeliveryContext(role);
  const isClient = role === "client";
  const isReadOnly = role === "bsg_leadership";

  const bootstrapQuery = useQuery(governanceBootstrapQueryOptions);
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

  const data = bootstrapQuery.data;

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

  const dueThisWeek = useMemo(() => (data ? actionsDueThisWeek(data.actions) : []), [data]);
  const overdue = useMemo(() => (data ? overdueActions(data.actions) : []), [data]);

  const escalatedRiskIds = useMemo(() => {
    if (!data) return new Set<string>();
    return new Set(
      data.escalations
        .filter((e) => e.source_type === "delivery_risk" && e.source_id)
        .map((e) => e.source_id as string),
    );
  }, [data]);

  const refreshAll = async () => {
    await queryClient.invalidateQueries({ queryKey: governanceBootstrapQueryOptions.queryKey });
    if (showDelivery) {
      await queryClient.invalidateQueries({ queryKey: deliveryPortfolioQueryOptions.queryKey });
    }
  };

  const runConfirm = async () => {
    if (!confirm) return;
    setBusyId(confirm.id);
    try {
      if (confirm.kind === "resolve-dependency") {
        await resolveDependency(confirm.id);
        toast.success("Dependency resolved.");
      } else if (confirm.kind === "resolve-escalation") {
        await updateGovernanceEscalation(confirm.id, { status: "resolved" });
        toast.success("Escalation resolved.");
      } else if (confirm.kind === "complete-action") {
        await updateGovernanceAction(confirm.id, { status: "completed" });
        toast.success("Action completed.");
      } else if (confirm.kind === "delete-dependency") {
        await deleteDependency(confirm.id);
        toast.success("Dependency archived.");
      } else if (confirm.kind === "delete-escalation") {
        await deleteGovernanceEscalation(confirm.id);
        toast.success("Escalation archived.");
      } else if (confirm.kind === "delete-action") {
        await deleteGovernanceAction(confirm.id);
        toast.success("Action archived.");
      }
      await refreshAll();
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
      await promoteRiskAlertToEscalation(riskAlertId);
      toast.success("Delivery risk promoted to escalation.");
      await refreshAll();
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

  if (bootstrapQuery.isLoading) {
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
          onRetry={() => void refreshAll()}
        />
      </Card>
    );
  }

  const { kpis, weekly_summary, charter_references } = data;
  const openActionsDelta =
    dueThisWeek.length > 0 ? `${dueThisWeek.length} due this week` : undefined;

  return (
    <div className="space-y-5">
      {isReadOnly && (
        <div className="rounded-md border border-border bg-elevated px-3 py-2 text-xs text-muted-foreground">
          Read-only portfolio governance view.
        </div>
      )}
      {isClient && (
        <div className="rounded-md border border-border bg-elevated px-3 py-2 text-xs text-muted-foreground">
          Client-safe escalation visibility only. Internal dependencies, actions, and draft summaries are hidden.
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
          <Button type="button" size="sm" variant="outline" onClick={() => setDialog({ kind: "dependency", mode: "create" })}>
            <Plus className="mr-1 h-3.5 w-3.5" />
            Dependency
          </Button>
          <Button type="button" size="sm" variant="outline" onClick={() => setDialog({ kind: "action", mode: "create" })}>
            <Plus className="mr-1 h-3.5 w-3.5" />
            Action
          </Button>
          <Button type="button" size="sm" variant="outline" onClick={() => setDialog({ kind: "escalation", mode: "create" })}>
            <Plus className="mr-1 h-3.5 w-3.5" />
            Escalation
          </Button>
        </div>
      )}

      <div className="grid grid-cols-1 gap-5 lg:grid-cols-3">
        <div className="space-y-5 lg:col-span-2">
          <div className="grid grid-cols-2 gap-4 lg:grid-cols-3">
            <KpiCard label="Open Actions" value={kpis.open_actions} delta={openActionsDelta} tone={kpis.open_actions > 0 ? "warning" : "default"} />
            <KpiCard label="Overdue Actions" value={kpis.overdue_actions} tone={kpis.overdue_actions > 0 ? "danger" : "default"} />
            <KpiCard label="At-Risk Items" value={kpis.at_risk_items} tone={kpis.at_risk_items > 0 ? "danger" : "success"} />
            <KpiCard label="Open Escalations" value={kpis.open_escalations} tone={kpis.open_escalations > 0 ? "danger" : "default"} />
            <KpiCard label="Blocking Dependencies" value={kpis.blocking_dependencies} tone={kpis.blocking_dependencies > 0 ? "danger" : "default"} />
            <KpiCard label="SLA Adherence" value={`${kpis.sla_adherence_pct}%`} tone={kpis.sla_adherence_pct >= 90 ? "success" : "warning"} />
          </div>

          {!isClient && (
            <Card>
              <SectionHeader title="Dependency Tracker" sub="Cross-project dependencies" />
              <div className="overflow-x-auto">
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
                      <EmptyRow colSpan={canWrite ? 8 : 7} message="No dependencies match filters." />
                    ) : (
                      filteredDependencies.map((dep) => (
                        <tr key={dep.id} className={cn("border-b border-border/50", dependencyRowClass(dep))}>
                          <td className="py-2.5 pr-3 font-medium">{dep.title}</td>
                          <td className="py-2.5 pr-3">{dep.project_name ?? "—"}</td>
                          <td className="py-2.5 pr-3 text-muted-foreground">{formatDependencyType(dep.dependency_type)}</td>
                          <td className="py-2.5 pr-3 text-muted-foreground">{dep.owner_name ?? "—"}</td>
                          <td className="py-2.5 pr-3 text-muted-foreground">{formatDate(dep.due_date)}</td>
                          <td className="py-2.5 pr-3">
                            {dep.overdue_days > 0 ? (
                              <span className="text-[color:var(--danger)]">{dep.overdue_days}d</span>
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
                                onEdit={() => setDialog({ kind: "dependency", mode: "edit", id: dep.id, projectId: dep.project_id })}
                                showResolve={dep.status !== "resolved"}
                                onResolve={() =>
                                  setConfirm({ kind: "resolve-dependency", id: dep.id, label: dep.title })
                                }
                                onDelete={() =>
                                  setConfirm({ kind: "delete-dependency", id: dep.id, label: dep.title })
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
            </Card>
          )}

          {!isClient && (
            <Card>
              <SectionHeader title="Governance Actions" sub="Tracked follow-ups and commitments" />
              <div className="overflow-x-auto">
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
                      filteredActions.map((action) => (
                        <tr key={action.id} className="border-b border-border/50">
                          <td className="py-2.5 pr-3 font-medium">{action.title}</td>
                          <td className="py-2.5 pr-3">{action.project_name ?? "—"}</td>
                          <td className="py-2.5 pr-3 text-muted-foreground">{action.owner_name ?? "—"}</td>
                          <td className="py-2.5 pr-3 text-muted-foreground">{formatDate(action.due_date)}</td>
                          <td className="py-2.5 pr-3">
                            <StatusPill status={formatActionStatus(action.status)} />
                          </td>
                          {canWrite && (
                            <td className="py-2.5 pr-3">
                              <RowActions
                                canWrite={canWrite}
                                onEdit={() => setDialog({ kind: "action", mode: "edit", id: action.id, projectId: action.project_id })}
                                showResolve={action.status !== "completed"}
                                resolveLabel="Complete"
                                onResolve={() =>
                                  setConfirm({ kind: "complete-action", id: action.id, label: action.title })
                                }
                                onDelete={() =>
                                  setConfirm({ kind: "delete-action", id: action.id, label: action.title })
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
            </Card>
          )}

          <Card>
            <SectionHeader title="Governance Register" sub="Click a project for details" />
            <div className="overflow-x-auto">
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
                    registerRows.map((row) => (
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
                        <td className="py-2.5 pr-3 text-muted-foreground">{row.scopeVersion ?? "—"}</td>
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
                            <span className="text-[color:var(--danger)]">{row.openEscalations}</span>
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
                              <StatusPill status={deliveryTrafficLabel(row.deliveryTrafficLight)} />
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
          </Card>
        </div>

        <Card>
          <SectionHeader title="Governance This Week" />
          {!isClient && (
            <>
              <div className="mt-1">
                <div className="mb-2 text-[10px] font-semibold uppercase tracking-wider text-muted-foreground">
                  Due this week
                </div>
                {dueThisWeek.length === 0 ? (
                  <p className="text-xs text-muted-foreground">No actions due this week.</p>
                ) : (
                  <ul className="space-y-1.5 text-xs">
                    {dueThisWeek.map((action) => (
                      <li
                        key={action.id}
                        className="flex items-center justify-between rounded border border-border bg-elevated px-2.5 py-1.5"
                      >
                        <span className="min-w-0 truncate pr-2">{action.title}</span>
                        <span className="shrink-0 text-[10px] text-muted-foreground">
                          {action.owner_name ?? action.project_name ?? "—"}
                        </span>
                      </li>
                    ))}
                  </ul>
                )}
              </div>
              <div className="mt-4">
                <div className="mb-2 text-[10px] font-semibold uppercase tracking-wider text-muted-foreground">
                  Overdue actions
                </div>
                {overdue.length === 0 ? (
                  <p className="text-xs text-muted-foreground">No overdue actions.</p>
                ) : (
                  <ul className="space-y-1.5 text-xs">
                    {overdue.map((action) => (
                      <li
                        key={action.id}
                        className="flex items-center justify-between rounded border border-[color:var(--danger)]/30 bg-[color:var(--danger)]/5 px-2.5 py-1.5"
                      >
                        <span className="min-w-0 truncate pr-2">{action.title}</span>
                        <StatusPill status="Overdue" />
                      </li>
                    ))}
                  </ul>
                )}
              </div>
            </>
          )}
          <div className="mt-4 rounded-md border border-border bg-elevated p-3 text-xs">
            <div className="mb-1 text-[10px] font-semibold uppercase tracking-wider text-muted-foreground">
              Weekly summary
            </div>
            {weekly_summary ? (
              <>
                <div className="mb-2 flex items-center gap-2">
                  <StatusPill status={weekly_summary.status === "approved" ? "Approved" : "Draft"} />
                  <span className="text-[10px] text-muted-foreground">
                    Week of {formatDate(weekly_summary.summary_week)}
                  </span>
                </div>
                <p className="leading-5 text-foreground/90">{weekly_summary.summary_text}</p>
              </>
            ) : (
              <p className="text-muted-foreground">No weekly summary available.</p>
            )}
            <button
              type="button"
              disabled
              title="AI summary generation coming in Phase 4"
              className="mt-3 cursor-not-allowed rounded border border-border px-2.5 py-1 text-[11px] font-medium text-muted-foreground"
            >
              Generate summary (Phase 4)
            </button>
          </div>
        </Card>
      </div>

      <Card>
        <SectionHeader title="Escalation Register" />
        <div className="overflow-x-auto">
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
                <EmptyRow colSpan={isClient ? 7 : canWrite ? 9 : 8} message="No escalations match filters." />
              ) : (
                filteredEscalations.map((esc) => (
                  <tr key={esc.id} className={cn("border-b border-border/50", escalationRowClass(esc))}>
                    <td className="py-2.5 pr-3 font-medium">{esc.title}</td>
                    <td className="py-2.5 pr-3">{esc.project_name ?? "—"}</td>
                    <td className="py-2.5 pr-3">
                      <StatusPill status={formatEscalationSeverity(esc.severity)} />
                    </td>
                    <td className="py-2.5 pr-3">
                      <StatusPill status={formatEscalationStatus(esc.status)} />
                    </td>
                    <td className="py-2.5 pr-3 text-muted-foreground">{esc.raised_by_name ?? "—"}</td>
                    <td className="py-2.5 pr-3">{esc.assigned_to_name ?? "—"}</td>
                    <td className="py-2.5 pr-3 text-muted-foreground">{formatDate(esc.raised_at)}</td>
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
                            setConfirm({ kind: "resolve-escalation", id: esc.id, label: esc.title })
                          }
                          onDelete={() =>
                            setConfirm({ kind: "delete-escalation", id: esc.id, label: esc.title })
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
      </Card>

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
          if (id) {
            await updateDependency(id, {
              title: values.title ?? undefined,
              description: values.description,
              dependency_type: values.dependency_type as GovernanceDependencyType,
              owner_id: values.owner_id,
              due_date: values.due_date,
              status: values.status as "open" | "blocking" | "resolved",
            });
            toast.success("Dependency updated.");
          } else {
            await createProjectDependency(projectId, {
              title: values.title!,
              description: values.description,
              dependency_type: values.dependency_type as GovernanceDependencyType,
              owner_id: values.owner_id,
              due_date: values.due_date,
              status: values.status as "open" | "blocking" | "resolved",
            });
            toast.success("Dependency created.");
          }
          await refreshAll();
        }}
        onSaveAction={async ({ projectId, id, values }) => {
          if (id) {
            await updateGovernanceAction(id, {
              title: values.title ?? undefined,
              description: values.description,
              owner_id: values.owner_id,
              due_date: values.due_date,
              status: values.status as "open" | "in_progress" | "completed" | "overdue",
              linked_knowledge_document_id: values.linked_knowledge_document_id,
            });
            toast.success("Action updated.");
          } else {
            await createGovernanceAction({
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
          await refreshAll();
        }}
        onSaveEscalation={async ({ projectId, id, values }) => {
          if (id) {
            await updateGovernanceEscalation(id, {
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
            await createGovernanceEscalation({
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
          await refreshAll();
        }}
        onSaveScope={async ({ projectId, values }) => {
          await updateProjectScope(projectId, {
            scope_status: values.scope_status as GovernanceScopeStatus,
            version_label: values.version_label ?? undefined,
            notes: values.notes,
            linked_charter_document_id: values.linked_charter_document_id,
          });
          toast.success("Scope updated.");
          await refreshAll();
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
        onCreateDependency={(projectId) => setDialog({ kind: "dependency", mode: "create", projectId })}
        onCreateAction={(projectId) => setDialog({ kind: "action", mode: "create", projectId })}
        onCreateEscalation={(projectId) => setDialog({ kind: "escalation", mode: "create", projectId })}
        onPromoteRisk={(riskAlertId) => void handlePromoteRisk(riskAlertId)}
        promotingRiskId={promotingRiskId}
        escalatedRiskIds={escalatedRiskIds}
      />

      <AlertDialog open={Boolean(confirm)} onOpenChange={(open) => !open && setConfirm(null)}>
        <AlertDialogContent>
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
