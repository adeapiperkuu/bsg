import { useQuery } from "@tanstack/react-query";
import { AlertTriangle, FileText } from "lucide-react";

import { StatusPill } from "@/components/bsg/widgets";
import { Button } from "@/components/ui/button";
import {
  Sheet,
  SheetContent,
  SheetDescription,
  SheetHeader,
  SheetTitle,
} from "@/components/ui/sheet";
import { listProjectRiskAlerts, type DeliveryPortfolioResponse } from "@/lib/api";
import {
  formatActionStatus,
  formatDate,
  formatDependencyStatus,
  formatDependencyType,
  formatEscalationSeverity,
  formatEscalationStatus,
  formatScopeStatus,
} from "@/lib/governance-utils";
import type { GovernanceBootstrap } from "@/types/governance";
import type { GovernanceRegisterRow } from "@/lib/governance-utils";

type ProjectGovernanceSheetProps = {
  open: boolean;
  onClose: () => void;
  row: GovernanceRegisterRow | null;
  data: GovernanceBootstrap;
  portfolio?: DeliveryPortfolioResponse;
  canWrite: boolean;
  showDelivery: boolean;
  onEditScope: (projectId: string) => void;
  onEditDependency: (id: string) => void;
  onEditAction: (id: string) => void;
  onEditEscalation: (id: string) => void;
  onCreateDependency: (projectId: string) => void;
  onCreateAction: (projectId: string) => void;
  onCreateEscalation: (projectId: string) => void;
  onPromoteRisk: (riskAlertId: string) => void;
  promotingRiskId: string | null;
  escalatedRiskIds: Set<string>;
};

function deliveryTrafficLabel(value: "green" | "yellow" | "red" | null): string {
  if (value === "green") return "On Track";
  if (value === "yellow") return "At Risk";
  if (value === "red") return "Critical";
  return "—";
}

export function ProjectGovernanceSheet({
  open,
  onClose,
  row,
  data,
  portfolio,
  canWrite,
  showDelivery,
  onEditScope,
  onEditDependency,
  onEditAction,
  onEditEscalation,
  onCreateDependency,
  onCreateAction,
  onCreateEscalation,
  onPromoteRisk,
  promotingRiskId,
  escalatedRiskIds,
}: ProjectGovernanceSheetProps) {
  const projectId = row?.projectId ?? null;

  const riskQuery = useQuery({
    queryKey: ["projects", projectId, "risk-alerts"],
    queryFn: () => listProjectRiskAlerts(projectId!),
    enabled: open && Boolean(projectId) && showDelivery && canWrite,
    staleTime: 5 * 60 * 1000,
    refetchOnWindowFocus: false,
  });

  if (!row) return null;

  const scope = data.scope_states.find((s) => s.project_id === row.projectId);
  const deps = data.dependencies.filter((d) => d.project_id === row.projectId);
  const actions = data.actions.filter((a) => a.project_id === row.projectId);
  const escalations = data.escalations.filter((e) => e.project_id === row.projectId);
  const deliveryEntry = portfolio?.projects.find((p) => p.project_id === row.projectId);
  const charterRef = data.charter_references.find(
    (c) => scope?.linked_charter_document_id === c.document_id,
  );

  return (
    <Sheet open={open} onOpenChange={(next) => !next && onClose()}>
      <SheetContent
        side="right"
        className="governance-no-shadow w-full overflow-y-auto sm:max-w-2xl"
      >
        <SheetHeader>
          <SheetTitle>{row.projectName}</SheetTitle>
          <SheetDescription>Project governance details</SheetDescription>
        </SheetHeader>

        <div className="mt-6 space-y-6 text-xs">
          <section>
            <div className="mb-2 flex items-center justify-between">
              <h3 className="text-[10px] font-semibold uppercase tracking-wider text-muted-foreground">
                Scope
              </h3>
              {canWrite && (
                <Button
                  type="button"
                  variant="outline"
                  size="sm"
                  onClick={() => onEditScope(row.projectId)}
                >
                  Edit scope
                </Button>
              )}
            </div>
            <div className="rounded border border-border bg-elevated p-3 space-y-1">
              <div className="flex items-center gap-2">
                <StatusPill status={formatScopeStatus(row.scopeStatus)} />
                <span className="text-muted-foreground">v{row.scopeVersion ?? "—"}</span>
              </div>
              {scope?.notes && <p className="text-foreground/90">{scope.notes}</p>}
              {charterRef && (
                <div className="flex items-center gap-2 pt-1 text-muted-foreground">
                  <FileText className="h-3.5 w-3.5" />
                  Charter: {charterRef.title}
                </div>
              )}
            </div>
          </section>

          {showDelivery && deliveryEntry && (
            <section>
              <h3 className="mb-2 text-[10px] font-semibold uppercase tracking-wider text-muted-foreground">
                Delivery signals (read-only)
              </h3>
              <div className="rounded border border-border bg-elevated p-3 space-y-2">
                <div className="flex items-center gap-2">
                  <StatusPill status={deliveryTrafficLabel(row.deliveryTrafficLight)} />
                  {row.deliveryConfidence !== null && (
                    <span>{row.deliveryConfidence}% confidence</span>
                  )}
                </div>
                {row.atRiskMilestones > 0 && (
                  <p className="text-[color:var(--warning)]">
                    {row.atRiskMilestones} at-risk milestones
                  </p>
                )}
                {canWrite && riskQuery.data && riskQuery.data.length > 0 && (
                  <div className="space-y-2 border-t border-border pt-2">
                    <p className="font-medium">Delivery risk alerts</p>
                    {riskQuery.data.map((alert) => {
                      const promoted =
                        escalatedRiskIds.has(alert.id) ||
                        escalations.some(
                          (e) => e.source_type === "delivery_risk" && e.source_id === alert.id,
                        );
                      return (
                        <div
                          key={alert.id}
                          className="flex items-start justify-between gap-2 rounded border border-border px-2 py-1.5"
                        >
                          <div className="min-w-0">
                            <div className="flex items-center gap-1.5 font-medium">
                              <AlertTriangle className="h-3.5 w-3.5 shrink-0 text-[color:var(--warning)]" />
                              {alert.title}
                            </div>
                            <p className="mt-0.5 text-[10px] text-muted-foreground">
                              {alert.detail}
                            </p>
                          </div>
                          {promoted ? (
                            <span className="shrink-0 text-[10px] text-muted-foreground">
                              Promoted
                            </span>
                          ) : (
                            <Button
                              type="button"
                              size="sm"
                              variant="outline"
                              className="h-7 shrink-0 text-[10px]"
                              disabled={promotingRiskId === alert.id}
                              onClick={() => onPromoteRisk(alert.id)}
                            >
                              {promotingRiskId === alert.id ? "Promoting…" : "Promote"}
                            </Button>
                          )}
                        </div>
                      );
                    })}
                  </div>
                )}
              </div>
            </section>
          )}

          <section>
            <div className="mb-2 flex items-center justify-between">
              <h3 className="text-[10px] font-semibold uppercase tracking-wider text-muted-foreground">
                Dependencies ({deps.length})
              </h3>
              {canWrite && (
                <Button
                  type="button"
                  variant="outline"
                  size="sm"
                  onClick={() => onCreateDependency(row.projectId)}
                >
                  Add
                </Button>
              )}
            </div>
            {deps.length === 0 ? (
              <p className="text-muted-foreground">No dependencies.</p>
            ) : (
              <ul className="space-y-1.5">
                {deps.map((dep) => (
                  <li
                    key={dep.id}
                    className="flex items-center justify-between rounded border border-border px-2 py-1.5"
                  >
                    <div className="min-w-0">
                      <div className="font-medium">{dep.title}</div>
                      <div className="text-[10px] text-muted-foreground">
                        {formatDependencyType(dep.dependency_type)} · {dep.owner_name ?? "—"} ·{" "}
                        {formatDate(dep.due_date)}
                      </div>
                    </div>
                    <div className="flex shrink-0 items-center gap-1">
                      <StatusPill status={formatDependencyStatus(dep.status)} />
                      {canWrite && (
                        <Button
                          type="button"
                          variant="ghost"
                          size="sm"
                          className="h-7 px-2"
                          onClick={() => onEditDependency(dep.id)}
                        >
                          Edit
                        </Button>
                      )}
                    </div>
                  </li>
                ))}
              </ul>
            )}
          </section>

          <section>
            <div className="mb-2 flex items-center justify-between">
              <h3 className="text-[10px] font-semibold uppercase tracking-wider text-muted-foreground">
                Actions ({actions.length})
              </h3>
              {canWrite && (
                <Button
                  type="button"
                  variant="outline"
                  size="sm"
                  onClick={() => onCreateAction(row.projectId)}
                >
                  Add
                </Button>
              )}
            </div>
            {actions.length === 0 ? (
              <p className="text-muted-foreground">No actions.</p>
            ) : (
              <ul className="space-y-1.5">
                {actions.map((action) => (
                  <li
                    key={action.id}
                    className="flex items-center justify-between rounded border border-border px-2 py-1.5"
                  >
                    <div className="min-w-0">
                      <div className="font-medium">{action.title}</div>
                      <div className="text-[10px] text-muted-foreground">
                        {action.owner_name ?? "—"} · {formatDate(action.due_date)}
                      </div>
                    </div>
                    <div className="flex shrink-0 items-center gap-1">
                      <StatusPill status={formatActionStatus(action.status)} />
                      {canWrite && (
                        <Button
                          type="button"
                          variant="ghost"
                          size="sm"
                          className="h-7 px-2"
                          onClick={() => onEditAction(action.id)}
                        >
                          Edit
                        </Button>
                      )}
                    </div>
                  </li>
                ))}
              </ul>
            )}
          </section>

          <section>
            <div className="mb-2 flex items-center justify-between">
              <h3 className="text-[10px] font-semibold uppercase tracking-wider text-muted-foreground">
                Escalations ({escalations.length})
              </h3>
              {canWrite && (
                <Button
                  type="button"
                  variant="outline"
                  size="sm"
                  onClick={() => onCreateEscalation(row.projectId)}
                >
                  Add
                </Button>
              )}
            </div>
            {escalations.length === 0 ? (
              <p className="text-muted-foreground">No escalations.</p>
            ) : (
              <ul className="space-y-1.5">
                {escalations.map((esc) => (
                  <li
                    key={esc.id}
                    className="flex items-center justify-between rounded border border-border px-2 py-1.5"
                  >
                    <div className="min-w-0">
                      <div className="font-medium">{esc.title}</div>
                      <div className="text-[10px] text-muted-foreground">
                        {formatEscalationSeverity(esc.severity)} · {esc.assigned_to_name ?? "—"}
                        {esc.source_type === "delivery_risk" && " · From delivery risk"}
                      </div>
                    </div>
                    <div className="flex shrink-0 items-center gap-1">
                      <StatusPill status={formatEscalationStatus(esc.status)} />
                      {canWrite && (
                        <Button
                          type="button"
                          variant="ghost"
                          size="sm"
                          className="h-7 px-2"
                          onClick={() => onEditEscalation(esc.id)}
                        >
                          Edit
                        </Button>
                      )}
                    </div>
                  </li>
                ))}
              </ul>
            )}
          </section>
        </div>
      </SheetContent>
    </Sheet>
  );
}
