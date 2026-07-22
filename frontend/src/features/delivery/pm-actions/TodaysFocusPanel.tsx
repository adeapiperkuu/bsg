import { useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { ChevronDown } from "lucide-react";
import { AiBadge, Card, SectionHeader, StatusPill } from "@/components/bsg/widgets";
import {
  completeProjectDailyAction,
  generateProjectDailyActions,
  type PmDailyActionRead,
} from "@/lib/api";
import { useProjectDailyActionsQuery } from "@/lib/queries/delivery";
import { queryKeys } from "@/lib/queries/keys";
import { useAuthStore } from "@/stores/useAuthStore";
import { cn } from "@/lib/utils";

type Props = {
  projectId: string | null;
  projectName?: string;
};

const URGENCY_LABEL: Record<PmDailyActionRead["urgency"], string> = {
  critical: "Critical",
  high: "High",
  medium: "Medium",
  low: "Low",
};

export function TodaysFocusPanel({ projectId, projectName }: Props) {
  const queryClient = useQueryClient();
  const role = useAuthStore((s) => s.user?.role);
  const canOperate = role === "delivery_manager" || role === "super_admin";
  const canView = role !== "client";
  const query = useProjectDailyActionsQuery(projectId, canView);

  // Which action row has a completion request in flight, so only its own buttons show
  // the pending state instead of freezing every row's buttons at once.
  const [pendingActionId, setPendingActionId] = useState<string | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);
  const [expanded, setExpanded] = useState(false);

  const generateMutation = useMutation({
    mutationFn: () => generateProjectDailyActions(projectId!, { with_ai_rationale: false }),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: queryKeys.projectDailyActions(projectId!) });
    },
  });

  const completeMutation = useMutation({
    mutationFn: (vars: { id: string; status: "done" | "skipped" | "deferred" }) =>
      completeProjectDailyAction(vars.id, { status: vars.status }),
    onMutate: (vars) => {
      setPendingActionId(vars.id);
      setActionError(null);
    },
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: queryKeys.projectDailyActions(projectId!) });
    },
    onError: (error) => {
      setActionError(error instanceof Error ? error.message : "Could not update the action.");
    },
    onSettled: () => {
      setPendingActionId(null);
    },
  });

  const completeAction = (id: string, status: "done" | "skipped" | "deferred") => {
    if (completeMutation.isPending) return;
    completeMutation.mutate({ id, status });
  };

  if (!canView) return null;

  const focus = query.data?.todays_focus ?? [];
  const history = query.data?.history ?? [];

  return (
    <Card>
      <SectionHeader
        title="Today's Focus"
        sub={
          projectName
            ? `Prioritized PM actions for ${projectName}`
            : "Ranked daily actions from delivery evidence"
        }
        right={
          <div className="flex items-center gap-2">
            <AiBadge label="Planner" source="formula" />
            {canOperate ? (
              <button
                type="button"
                className="rounded border border-border px-2 py-1 text-xs text-muted-foreground hover:bg-elevated"
                disabled={!projectId || generateMutation.isPending}
                onClick={() => generateMutation.mutate()}
              >
                {generateMutation.isPending ? "Refreshing…" : "Refresh plan"}
              </button>
            ) : null}
          </div>
        }
      />

      <div className="mb-3 flex border-b border-border">
        <button
          type="button"
          aria-expanded={expanded}
          onClick={() => setExpanded((v) => !v)}
          className={cn(
            "flex items-center gap-1.5 border-b-2 px-3 py-1.5 text-xs font-medium transition-colors",
            expanded
              ? "border-[color:var(--brand)] text-foreground"
              : "border-transparent text-muted-foreground hover:text-foreground",
          )}
        >
          Focus
          <ChevronDown
            className={cn("h-3.5 w-3.5 transition-transform", expanded ? "" : "-rotate-90")}
          />
        </button>
      </div>

      {!expanded ? null : (
        <>
      {actionError ? (
        <p className="mb-3 rounded border border-[color:var(--danger)]/30 bg-[color:var(--danger)]/10 px-3 py-2 text-xs text-[color:var(--danger)]">
          {actionError}
        </p>
      ) : null}

      {query.isLoading ? (
        <div className="space-y-2">
          <div className="h-12 animate-pulse rounded bg-elevated" />
          <div className="h-12 animate-pulse rounded bg-elevated" />
        </div>
      ) : query.isError ? (
        <p className="text-sm text-muted-foreground">
          Could not load today's actions
          {query.error instanceof Error ? `: ${query.error.message}` : "."}
        </p>
      ) : focus.length === 0 ? (
        <div className="space-y-2">
          <p className="text-sm text-muted-foreground">
            No focus items for today yet. Refresh after scoring or operational updates.
          </p>
          {canOperate && projectId ? (
            <button
              type="button"
              className="rounded border border-border px-2 py-1 text-xs hover:bg-elevated"
              onClick={() => generateMutation.mutate()}
            >
              Generate today's plan
            </button>
          ) : null}
        </div>
      ) : (
        <ol className="space-y-3">
          {focus.map((action) => (
            <li
              key={action.id}
              className="rounded border border-border bg-elevated/30 px-3 py-2.5"
            >
              <div className="mb-1 flex flex-wrap items-center justify-between gap-2">
                <div className="flex items-center gap-2">
                  <span className="text-xs tabular-nums text-muted-foreground">#{action.rank}</span>
                  <p className="text-sm font-medium text-foreground">{action.title}</p>
                </div>
                <div className="flex items-center gap-2">
                  <StatusPill status={URGENCY_LABEL[action.urgency]} />
                  <span className="text-[11px] text-muted-foreground">
                    Impact ~{Math.round(action.estimated_impact_points)} pts · due {action.due_date}
                  </span>
                </div>
              </div>
              <p className="text-xs text-muted-foreground">
                {action.ai_rationale || action.deterministic_rationale}
              </p>
              {canOperate ? (
                <div className="mt-2 flex flex-wrap gap-2">
                  <button
                    type="button"
                    className={cn(
                      "cursor-pointer rounded px-2 py-1 text-[11px]",
                      "bg-[color:var(--brand)]/15 text-foreground hover:bg-[color:var(--brand)]/25",
                      "disabled:cursor-not-allowed disabled:opacity-50",
                    )}
                    disabled={completeMutation.isPending}
                    onClick={() => completeAction(action.id, "done")}
                  >
                    {pendingActionId === action.id ? "Saving…" : "Done"}
                  </button>
                  <button
                    type="button"
                    className="cursor-pointer rounded border border-border px-2 py-1 text-[11px] text-muted-foreground hover:bg-elevated disabled:cursor-not-allowed disabled:opacity-50"
                    disabled={completeMutation.isPending}
                    onClick={() => completeAction(action.id, "skipped")}
                  >
                    Skip
                  </button>
                  <button
                    type="button"
                    className="cursor-pointer rounded border border-border px-2 py-1 text-[11px] text-muted-foreground hover:bg-elevated disabled:cursor-not-allowed disabled:opacity-50"
                    disabled={completeMutation.isPending}
                    onClick={() => completeAction(action.id, "deferred")}
                  >
                    Defer
                  </button>
                </div>
              ) : null}
            </li>
          ))}
        </ol>
      )}

          {history.length > 0 ? (
            <div className="mt-4 border-t border-border pt-3">
          <p className="mb-2 text-xs uppercase tracking-wide text-muted-foreground">
            Recent completions
          </p>
          <ul className="space-y-1.5 text-xs text-muted-foreground">
            {history.slice(0, 5).map((item) => (
              <li key={item.id} className="flex justify-between gap-2">
                <span className="truncate">
                  {item.title} · {item.status}
                </span>
                <span className="shrink-0">{item.plan_date}</span>
              </li>
            ))}
          </ul>
        </div>
      ) : null}
        </>
      )}
    </Card>
  );
}
