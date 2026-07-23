import { Link } from "@tanstack/react-router";
import { useEffect, useState, type FormEvent, type ReactNode } from "react";
import { useQuery } from "@tanstack/react-query";
import {
  AlertTriangle,
  Bell,
  Bot,
  CalendarDays,
  Check,
  CheckCircle2,
  ChevronRight,
  CircleDot,
  ClipboardCheck,
  Clock3,
  Download,
  FileCheck2,
  FileText,
  Flag,
  FolderOpen,
  GitPullRequest,
  LayoutDashboard,
  ListChecks,
  MessageSquareText,
  Plus,
  RefreshCw,
  ShieldAlert,
  Sparkles,
  Users,
} from "lucide-react";

import { PageLoadingScreen } from "@/components/bsg/PageLoadingScreen";
import { Card, SectionHeader } from "@/components/bsg/widgets";
import { DeliveryMarkdown } from "@/components/delivery/delivery-markdown";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Progress } from "@/components/ui/progress";
import { Textarea } from "@/components/ui/textarea";
import { summarizeClientPortfolio } from "@/features/client-dashboard/client-dashboard-utils";
import { clientReportDownloadUrl } from "@/lib/api";
import {
  useClientProjectDashboardQuery,
  useSubmitClientChangeRequest,
} from "@/lib/queries/client-portal";
import { deliveryPortfolioQueryOptions } from "@/lib/queries/delivery";
import { cn } from "@/lib/utils";
import type {
  ClientAction,
  ClientChangeRequestStatus,
  ClientDeliverable,
  ClientMeeting,
  ClientMilestone,
  ClientNotification,
  ClientRisk,
} from "@/types/client-portal";

export type ClientWorkspaceView =
  | "overview"
  | "progress"
  | "risks"
  | "actions"
  | "summary"
  | "documents"
  | "deliverables"
  | "changes"
  | "meetings"
  | "notifications";

const STATUS_LABELS: Record<string, string> = {
  active: "Active",
  ramping: "Ramping",
  paused: "Paused",
  completed: "Completed",
  cancelled: "Cancelled",
  pending: "Pending",
  on_track: "On track",
  at_risk: "At risk",
  missed: "Missed",
  open: "Open",
  blocking: "Blocking",
  resolved: "Resolved",
  in_progress: "In progress",
  overdue: "Overdue",
  submitted: "Submitted",
  under_review: "Under review",
  approved: "Approved",
  rejected: "Rejected",
  implemented: "Implemented",
  planned: "Planned",
  scheduled: "Scheduled",
  critical: "Critical",
  high: "High",
  medium: "Medium",
  low: "Low",
};

function statusLabel(value: string): string {
  return STATUS_LABELS[value] ?? value.replaceAll("_", " ");
}

function formatDate(value: string | null, includeTime = false): string {
  if (!value) return "Not set";
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) return value;
  return parsed.toLocaleString(undefined, {
    dateStyle: "medium",
    ...(includeTime ? { timeStyle: "short" as const } : {}),
  });
}

function toneForStatus(status: string): string {
  if (["completed", "implemented", "approved", "resolved", "green", "on_track"].includes(status)) {
    return "border-[color:var(--success)]/30 bg-[color:var(--success)]/10 text-[color:var(--success)]";
  }
  if (["critical", "high", "rejected", "missed", "red", "blocking", "overdue"].includes(status)) {
    return "border-[color:var(--danger)]/30 bg-[color:var(--danger)]/10 text-[color:var(--danger)]";
  }
  if (["medium", "at_risk", "amber", "pending", "submitted", "under_review"].includes(status)) {
    return "border-[color:var(--warning)]/30 bg-[color:var(--warning)]/10 text-[color:var(--warning)]";
  }
  return "border-border bg-secondary text-muted-foreground";
}

function StatusTag({ value, label }: { value: string; label?: string }) {
  return (
    <span
      className={cn(
        "inline-flex items-center rounded-full border px-2 py-0.5 text-[10px] font-semibold",
        toneForStatus(value),
      )}
    >
      {label ?? statusLabel(value)}
    </span>
  );
}

function EmptyState({
  icon: Icon,
  title,
  body,
  action,
}: {
  icon: typeof Bell;
  title: string;
  body: string;
  action?: ReactNode;
}) {
  return (
    <div className="flex min-h-48 flex-col items-center justify-center rounded-lg border border-dashed border-border bg-elevated/40 px-6 py-10 text-center">
      <span className="rounded-full border border-border bg-card p-3">
        <Icon className="h-5 w-5 text-muted-foreground" />
      </span>
      <p className="mt-3 text-sm font-semibold">{title}</p>
      <p className="mt-1 max-w-md text-xs leading-5 text-muted-foreground">{body}</p>
      {action ? <div className="mt-4">{action}</div> : null}
    </div>
  );
}

function MetricTile({
  label,
  value,
  detail,
  tone = "neutral",
}: {
  label: string;
  value: ReactNode;
  detail?: string;
  tone?: "success" | "warning" | "danger" | "neutral";
}) {
  const dot =
    tone === "success"
      ? "bg-[color:var(--success)]"
      : tone === "warning"
        ? "bg-[color:var(--warning)]"
        : tone === "danger"
          ? "bg-[color:var(--danger)]"
          : "bg-[color:var(--brand)]";
  return (
    <div className="rounded-lg border border-border bg-card p-4">
      <div className="flex items-center gap-2 text-[10px] font-semibold uppercase tracking-[0.14em] text-muted-foreground">
        <span className={cn("h-1.5 w-1.5 rounded-full", dot)} />
        {label}
      </div>
      <div className="mt-2 text-xl font-semibold tracking-tight">{value}</div>
      {detail ? <p className="mt-1 text-[11px] text-muted-foreground">{detail}</p> : null}
    </div>
  );
}

function ViewHeader({
  eyebrow,
  title,
  description,
  action,
}: {
  eyebrow: string;
  title: string;
  description: string;
  action?: ReactNode;
}) {
  return (
    <div className="flex flex-col gap-3 border-b border-border pb-5 sm:flex-row sm:items-end sm:justify-between">
      <div>
        <p className="text-[10px] font-semibold uppercase tracking-[0.18em] text-[color:var(--brand)]">
          {eyebrow}
        </p>
        <h2 className="mt-1 text-xl font-semibold tracking-tight">{title}</h2>
        <p className="mt-1 max-w-2xl text-xs leading-5 text-muted-foreground">{description}</p>
      </div>
      {action}
    </div>
  );
}

function MilestoneTimeline({
  milestones,
  compact = false,
}: {
  milestones: ClientMilestone[];
  compact?: boolean;
}) {
  if (!milestones.length) {
    return (
      <EmptyState
        icon={Flag}
        title="No milestones published"
        body="The delivery team has not published a milestone plan for this project yet."
      />
    );
  }
  return (
    <ol className="relative space-y-0">
      {milestones.map((milestone, index) => {
        const complete = milestone.status === "completed";
        const active = ["on_track", "at_risk"].includes(milestone.status);
        return (
          <li
            key={milestone.id}
            className="relative grid grid-cols-[28px_1fr] gap-3 pb-5 last:pb-0"
          >
            {index < milestones.length - 1 ? (
              <span className="absolute left-[13px] top-7 h-[calc(100%-12px)] w-px bg-border" />
            ) : null}
            <span
              className={cn(
                "relative z-10 mt-0.5 flex h-7 w-7 items-center justify-center rounded-full border bg-card",
                complete
                  ? "border-[color:var(--success)] text-[color:var(--success)]"
                  : active
                    ? "border-[color:var(--brand)] text-[color:var(--brand)]"
                    : "border-border text-muted-foreground",
              )}
            >
              {complete ? (
                <Check className="h-3.5 w-3.5" />
              ) : active ? (
                <CircleDot className="h-3.5 w-3.5" />
              ) : (
                <Flag className="h-3 w-3" />
              )}
            </span>
            <div
              className={cn(
                "rounded-lg border border-border bg-elevated/45 p-3",
                compact && "p-2.5",
              )}
            >
              <div className="flex flex-wrap items-center justify-between gap-2">
                <div>
                  <p className="text-xs font-semibold">{milestone.name}</p>
                  <p className="mt-0.5 text-[10px] text-muted-foreground">
                    {complete && milestone.actual_date
                      ? `Completed ${formatDate(milestone.actual_date)}`
                      : `Due ${formatDate(milestone.planned_date)}`}
                  </p>
                </div>
                <StatusTag value={milestone.status} />
              </div>
              {!compact ? (
                <>
                  {milestone.description ? (
                    <p className="mt-2 text-xs leading-5 text-muted-foreground">
                      {milestone.description}
                    </p>
                  ) : null}
                  <div className="mt-3 flex items-center gap-3">
                    <Progress value={milestone.progress_percentage} className="h-1.5 flex-1" />
                    <span className="w-8 text-right text-[10px] font-medium text-muted-foreground">
                      {milestone.progress_percentage}%
                    </span>
                  </div>
                </>
              ) : null}
            </div>
          </li>
        );
      })}
    </ol>
  );
}

function OverviewView({
  data,
  onNavigate,
}: {
  data: NonNullable<ReturnType<typeof useClientProjectDashboardQuery>["data"]>;
  onNavigate: (view: ClientWorkspaceView) => void;
}) {
  const { overview } = data;
  const healthTone =
    overview.overall_health === "green"
      ? "success"
      : overview.overall_health === "amber"
        ? "warning"
        : overview.overall_health === "red"
          ? "danger"
          : "neutral";
  const completedMilestones = data.milestones.filter((item) => item.status === "completed").length;
  const activeRisks = data.risks.filter((item) => item.status !== "resolved").length;
  const pendingActions = data.client_actions.filter((item) => item.status !== "resolved").length;
  const nextMilestone = data.milestones.find((item) =>
    ["pending", "on_track", "at_risk"].includes(item.status),
  );

  return (
    <div className="space-y-5">
      <ViewHeader
        eyebrow="Project overview"
        title={overview.project_name}
        description={
          overview.description ??
          "A single, client-safe view of project health, progress, decisions, and upcoming work."
        }
        action={<StatusTag value={overview.current_status} />}
      />

      <div className="grid grid-cols-2 gap-3 xl:grid-cols-5">
        <MetricTile
          label="Overall health"
          value={statusLabel(overview.overall_health)}
          detail="Based on published delivery signals"
          tone={healthTone}
        />
        <MetricTile
          label="Delivery confidence"
          value={overview.delivery_confidence == null ? "—" : `${overview.delivery_confidence}%`}
          detail={overview.delivery_confidence_label}
          tone={healthTone}
        />
        <MetricTile
          label="Current phase"
          value={<span className="text-base">{overview.current_phase}</span>}
          detail={`Target ${formatDate(overview.target_end_date)}`}
        />
        <MetricTile
          label="Completion"
          value={`${overview.completion_percentage}%`}
          detail={`${completedMilestones} of ${data.milestones.length} milestones complete`}
          tone="success"
        />
        <MetricTile
          label="Client actions"
          value={pendingActions}
          detail={pendingActions ? "Items waiting for you" : "Nothing outstanding"}
          tone={pendingActions ? "warning" : "success"}
        />
      </div>

      <div className="grid gap-5 xl:grid-cols-[1.25fr_.75fr]">
        <Card className="overflow-hidden">
          <SectionHeader
            title="Project progress"
            sub={
              nextMilestone ? `Next milestone: ${nextMilestone.name}` : "Milestone delivery plan"
            }
            right={
              <button
                type="button"
                className="text-[11px] font-semibold text-[color:var(--brand)]"
                onClick={() => onNavigate("progress")}
              >
                View timeline
              </button>
            }
          />
          <div className="mb-5 rounded-lg border border-border bg-elevated/50 p-4">
            <div className="flex items-end justify-between gap-3">
              <div>
                <p className="text-[10px] uppercase tracking-wider text-muted-foreground">
                  Overall completion
                </p>
                <p className="mt-1 text-3xl font-semibold">{overview.completion_percentage}%</p>
              </div>
              <p className="text-right text-[11px] text-muted-foreground">
                {formatDate(overview.start_date)}
                <br />
                to {formatDate(overview.target_end_date)}
              </p>
            </div>
            <Progress value={overview.completion_percentage} className="mt-4 h-2" />
          </div>
          <MilestoneTimeline milestones={data.milestones.slice(0, 4)} compact />
        </Card>

        <div className="space-y-5">
          <Card>
            <SectionHeader
              title="Needs your attention"
              sub={`${activeRisks} active ${activeRisks === 1 ? "risk" : "risks"} · ${pendingActions} open ${pendingActions === 1 ? "action" : "actions"}`}
            />
            {pendingActions === 0 && activeRisks === 0 ? (
              <div className="flex items-center gap-3 rounded-lg border border-[color:var(--success)]/20 bg-[color:var(--success)]/5 p-4">
                <CheckCircle2 className="h-5 w-5 text-[color:var(--success)]" />
                <div>
                  <p className="text-xs font-semibold">Nothing needs your attention</p>
                  <p className="mt-0.5 text-[10px] text-muted-foreground">
                    No open client actions or published risks.
                  </p>
                </div>
              </div>
            ) : (
              <div className="space-y-2">
                {data.client_actions
                  .filter((item) => item.status !== "resolved")
                  .slice(0, 3)
                  .map((action) => (
                    <button
                      key={action.id}
                      type="button"
                      onClick={() => onNavigate("actions")}
                      className="flex w-full items-center justify-between gap-3 rounded-lg border border-border bg-elevated/40 p-3 text-left hover:border-[color:var(--brand)]/40"
                    >
                      <span className="min-w-0">
                        <span className="block truncate text-xs font-medium">{action.title}</span>
                        <span
                          className={cn(
                            "mt-0.5 block text-[10px]",
                            action.is_overdue
                              ? "text-[color:var(--danger)]"
                              : "text-muted-foreground",
                          )}
                        >
                          {action.is_overdue
                            ? "Overdue"
                            : action.due_date
                              ? `Due ${formatDate(action.due_date)}`
                              : "No due date"}
                        </span>
                      </span>
                      <ChevronRight className="h-3.5 w-3.5 shrink-0 text-muted-foreground" />
                    </button>
                  ))}
                {data.risks
                  .filter((item) => item.status !== "resolved")
                  .slice(0, 2)
                  .map((risk) => (
                    <button
                      key={risk.id}
                      type="button"
                      onClick={() => onNavigate("risks")}
                      className="flex w-full items-center justify-between gap-3 rounded-lg border border-border bg-elevated/40 p-3 text-left hover:border-[color:var(--brand)]/40"
                    >
                      <span className="min-w-0">
                        <span className="block truncate text-xs font-medium">{risk.title}</span>
                        <span className="mt-0.5 block text-[10px] text-muted-foreground">
                          {statusLabel(risk.severity)} risk
                        </span>
                      </span>
                      <AlertTriangle className="h-3.5 w-3.5 shrink-0 text-[color:var(--warning)]" />
                    </button>
                  ))}
              </div>
            )}
          </Card>

          <Card className="border-[color:var(--brand)]/25 bg-[color:var(--brand)]/[0.04]">
            <div className="flex items-start gap-3">
              <span className="rounded-lg bg-[color:var(--brand)]/10 p-2 text-[color:var(--brand)]">
                <Sparkles className="h-4 w-4" />
              </span>
              <div className="min-w-0 flex-1">
                <div className="flex items-center justify-between gap-2">
                  <p className="text-xs font-semibold">AI project summary</p>
                  <span className="text-[9px] uppercase tracking-wider text-muted-foreground">
                    Approved data only
                  </span>
                </div>
                <p className="mt-2 line-clamp-4 text-xs leading-5 text-muted-foreground">
                  {data.ai_summary.summary}
                </p>
                <div className="mt-3 flex gap-3">
                  <button
                    type="button"
                    className="text-[11px] font-semibold text-[color:var(--brand)]"
                    onClick={() => onNavigate("summary")}
                  >
                    Read summary
                  </button>
                  <Link to="/client/ask" className="text-[11px] font-semibold text-foreground">
                    Ask AI
                  </Link>
                </div>
              </div>
            </div>
          </Card>
        </div>
      </div>

      <Card>
        <SectionHeader
          title="Latest reports"
          sub="Published by your delivery team"
          right={
            <Link
              to="/client/reports"
              className="text-[11px] font-semibold text-[color:var(--brand)]"
            >
              Open report archive
            </Link>
          }
        />
        {data.reports.length ? (
          <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-3">
            {data.reports.slice(0, 3).map((report) => (
              <article
                key={report.id}
                className="rounded-lg border border-border bg-elevated/40 p-4"
              >
                <div className="flex items-center justify-between gap-2">
                  <FileText className="h-4 w-4 text-[color:var(--brand)]" />
                  <span className="text-[9px] uppercase tracking-wider text-muted-foreground">
                    {statusLabel(report.report_type)}
                  </span>
                </div>
                <h3 className="mt-3 truncate text-xs font-semibold">{report.title}</h3>
                <p className="mt-1 line-clamp-2 text-[10px] leading-4 text-muted-foreground">
                  {report.executive_summary}
                </p>
                <div className="mt-3 flex items-center justify-between">
                  <span className="text-[10px] text-muted-foreground">
                    {formatDate(report.published_at)}
                  </span>
                  <div className="flex gap-2">
                    <a
                      href={clientReportDownloadUrl(report.id, "pdf")}
                      className="text-[10px] font-semibold text-[color:var(--brand)]"
                    >
                      PDF
                    </a>
                    <a
                      href={clientReportDownloadUrl(report.id, "csv")}
                      className="text-[10px] font-semibold text-[color:var(--brand)]"
                    >
                      CSV
                    </a>
                  </div>
                </div>
              </article>
            ))}
          </div>
        ) : (
          <EmptyState
            icon={FileText}
            title="No published reports"
            body="Weekly and monthly reports will appear here after your delivery team publishes them."
          />
        )}
      </Card>
    </div>
  );
}

function ProgressView({
  milestones,
  completion,
}: {
  milestones: ClientMilestone[];
  completion: number;
}) {
  const completed = milestones.filter((item) => item.status === "completed");
  const current = milestones.find((item) => ["on_track", "at_risk"].includes(item.status));
  const upcoming = milestones.find((item) => item.status === "pending");
  return (
    <div className="space-y-5">
      <ViewHeader
        eyebrow="Project progress"
        title="Milestones & timeline"
        description="Track completed work, the active delivery phase, and what comes next."
      />
      <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
        <MetricTile label="Overall progress" value={`${completion}%`} tone="success" />
        <MetricTile
          label="Completed"
          value={completed.length}
          detail={`${milestones.length} total milestones`}
          tone="success"
        />
        <MetricTile
          label="Current milestone"
          value={<span className="text-base">{current?.name ?? "Not set"}</span>}
          detail={current ? `Due ${formatDate(current.planned_date)}` : undefined}
          tone={current?.status === "at_risk" ? "warning" : "neutral"}
        />
        <MetricTile
          label="Upcoming"
          value={<span className="text-base">{upcoming?.name ?? "Not set"}</span>}
          detail={upcoming ? `Due ${formatDate(upcoming.planned_date)}` : undefined}
        />
      </div>
      <Card>
        <SectionHeader
          title="Delivery timeline"
          sub="Milestone progress is based on the latest published plan."
        />
        <MilestoneTimeline milestones={milestones} />
      </Card>
    </div>
  );
}

function RisksView({ risks }: { risks: ClientRisk[] }) {
  const active = risks.filter((item) => item.status !== "resolved");
  return (
    <div className="space-y-5">
      <ViewHeader
        eyebrow="Risks & issues"
        title="Client-visible risk register"
        description="Only risks approved for client visibility are shown. Internal delivery risks remain excluded."
      />
      <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
        <MetricTile
          label="Active risks"
          value={active.length}
          tone={active.length ? "warning" : "success"}
        />
        <MetricTile
          label="Critical / high"
          value={active.filter((item) => ["critical", "high"].includes(item.severity)).length}
          tone={
            active.some((item) => ["critical", "high"].includes(item.severity))
              ? "danger"
              : "success"
          }
        />
        <MetricTile
          label="In mitigation"
          value={active.filter((item) => Boolean(item.mitigation)).length}
        />
        <MetricTile label="Resolved" value={risks.length - active.length} tone="success" />
      </div>
      {risks.length ? (
        <div className="space-y-3">
          {risks.map((risk) => (
            <Card key={risk.id}>
              <div className="flex flex-col gap-4 lg:flex-row lg:items-start lg:justify-between">
                <div className="min-w-0">
                  <div className="flex flex-wrap items-center gap-2">
                    <StatusTag
                      value={risk.severity}
                      label={`${statusLabel(risk.severity)} severity`}
                    />
                    <StatusTag value={risk.status} />
                    <span className="text-[10px] text-muted-foreground">
                      Updated {formatDate(risk.updated_at)}
                    </span>
                  </div>
                  <h3 className="mt-3 text-sm font-semibold">{risk.title}</h3>
                </div>
              </div>
              <div className="mt-4 grid gap-3 lg:grid-cols-2">
                <div className="rounded-lg border border-border bg-elevated/50 p-4">
                  <p className="text-[10px] font-semibold uppercase tracking-wider text-muted-foreground">
                    Business impact
                  </p>
                  <p className="mt-2 text-xs leading-5">
                    {risk.impact ?? "Impact details have not been published yet."}
                  </p>
                </div>
                <div className="rounded-lg border border-border bg-elevated/50 p-4">
                  <p className="text-[10px] font-semibold uppercase tracking-wider text-muted-foreground">
                    Mitigation
                  </p>
                  <p className="mt-2 text-xs leading-5">
                    {risk.mitigation ??
                      "A client-safe mitigation update has not been published yet."}
                  </p>
                </div>
              </div>
            </Card>
          ))}
        </div>
      ) : (
        <EmptyState
          icon={ShieldAlert}
          title="No client-visible risks"
          body="There are no active risks approved for client visibility at this time."
        />
      )}
    </div>
  );
}

function ActionsView({ actions }: { actions: ClientAction[] }) {
  const actionIcon = (type: ClientAction["action_type"]) =>
    type === "approval"
      ? ClipboardCheck
      : type === "information_request"
        ? MessageSquareText
        : ListChecks;
  return (
    <div className="space-y-5">
      <ViewHeader
        eyebrow="Client actions"
        title="Approvals & information requests"
        description="See what the delivery team needs from you, why it matters, and when it is due."
      />
      {actions.length ? (
        <div className="grid gap-3 xl:grid-cols-2">
          {actions.map((action) => {
            const Icon = actionIcon(action.action_type);
            return (
              <Card
                key={action.id}
                className={cn(action.is_overdue && "border-[color:var(--danger)]/30")}
              >
                <div className="flex items-start gap-3">
                  <span
                    className={cn(
                      "rounded-lg border p-2",
                      action.is_overdue
                        ? "border-[color:var(--danger)]/20 bg-[color:var(--danger)]/5 text-[color:var(--danger)]"
                        : "border-border bg-elevated text-[color:var(--brand)]",
                    )}
                  >
                    <Icon className="h-4 w-4" />
                  </span>
                  <div className="min-w-0 flex-1">
                    <div className="flex flex-wrap items-center justify-between gap-2">
                      <p className="text-sm font-semibold">{action.title}</p>
                      <StatusTag value={action.is_overdue ? "overdue" : action.status} />
                    </div>
                    <p className="mt-1 text-[10px] font-medium uppercase tracking-wider text-muted-foreground">
                      {statusLabel(action.action_type)}
                    </p>
                    {action.description ? (
                      <p className="mt-3 text-xs leading-5 text-muted-foreground">
                        {action.description}
                      </p>
                    ) : null}
                    <div className="mt-4 flex items-center gap-2 text-[11px]">
                      <Clock3 className="h-3.5 w-3.5 text-muted-foreground" />
                      <span
                        className={
                          action.is_overdue
                            ? "font-semibold text-[color:var(--danger)]"
                            : "text-muted-foreground"
                        }
                      >
                        {action.due_date
                          ? `${action.is_overdue ? "Was due" : "Due"} ${formatDate(action.due_date)}`
                          : "No due date"}
                      </span>
                    </div>
                  </div>
                </div>
              </Card>
            );
          })}
        </div>
      ) : (
        <EmptyState
          icon={ClipboardCheck}
          title="No outstanding actions"
          body="You have no pending approvals, information requests, or other project actions."
        />
      )}
    </div>
  );
}

function SummaryView({
  data,
}: {
  data: NonNullable<ReturnType<typeof useClientProjectDashboardQuery>["data"]>;
}) {
  const summary = data.ai_summary;
  return (
    <div className="space-y-5">
      <ViewHeader
        eyebrow="AI project summary"
        title={summary.title}
        description="A client-safe weekly synthesis generated from approved project information."
        action={
          <Link to="/client/ask">
            <Button size="sm">
              <Bot className="mr-2 h-3.5 w-3.5" />
              Ask AI
            </Button>
          </Link>
        }
      />
      <Card className="border-[color:var(--brand)]/25">
        <div className="mb-4 flex items-center justify-between gap-3 border-b border-border pb-4">
          <div className="flex items-center gap-3">
            <span className="rounded-lg bg-[color:var(--brand)]/10 p-2 text-[color:var(--brand)]">
              <Sparkles className="h-4 w-4" />
            </span>
            <div>
              <p className="text-xs font-semibold">Executive summary</p>
              <p className="mt-0.5 text-[10px] text-muted-foreground">
                {summary.generated_at
                  ? `Published ${formatDate(summary.generated_at, true)}`
                  : "Awaiting a published summary"}
              </p>
            </div>
          </div>
          <span className="rounded-full border border-[color:var(--brand)]/25 bg-[color:var(--brand)]/5 px-2 py-1 text-[9px] font-semibold uppercase tracking-wider text-[color:var(--brand)]">
            Approved sources
          </span>
        </div>
        <div className="prose-invert max-w-none text-sm leading-6">
          <DeliveryMarkdown content={summary.summary} />
        </div>
      </Card>
      <div className="grid gap-4 lg:grid-cols-3">
        {[
          {
            title: "Current progress",
            icon: CheckCircle2,
            items: summary.current_progress,
            empty: "No progress highlights published.",
          },
          {
            title: "Risks",
            icon: AlertTriangle,
            items: summary.risks,
            empty: "No client-visible risks in this summary.",
          },
          {
            title: "Upcoming work",
            icon: Flag,
            items: summary.upcoming_work,
            empty: "No upcoming work published.",
          },
        ].map(({ title, icon: Icon, items, empty }) => (
          <Card key={title}>
            <SectionHeader
              title={title}
              right={<Icon className="h-4 w-4 text-[color:var(--brand)]" />}
            />
            {items.length ? (
              <ul className="space-y-2">
                {items.map((item, index) => (
                  <li
                    key={`${title}-${index}`}
                    className="flex gap-2 rounded-lg border border-border bg-elevated/40 p-3 text-xs leading-5"
                  >
                    <span className="mt-2 h-1 w-1 shrink-0 rounded-full bg-[color:var(--brand)]" />
                    {item}
                  </li>
                ))}
              </ul>
            ) : (
              <p className="text-xs text-muted-foreground">{empty}</p>
            )}
          </Card>
        ))}
      </div>
    </div>
  );
}

function DocumentsView({
  data,
}: {
  data: NonNullable<ReturnType<typeof useClientProjectDashboardQuery>["data"]>;
}) {
  return (
    <div className="space-y-5">
      <ViewHeader
        eyebrow="Shared documents"
        title="Project document library"
        description="Only approved documents explicitly shared for client access appear here."
      />
      {data.documents.length ? (
        <div className="overflow-hidden rounded-lg border border-border bg-card">
          <div className="hidden grid-cols-[1.5fr_.7fr_.5fr_.7fr_80px] gap-4 border-b border-border bg-elevated/60 px-4 py-3 text-[10px] font-semibold uppercase tracking-wider text-muted-foreground md:grid">
            <span>Document</span>
            <span>Type</span>
            <span>Version</span>
            <span>Shared</span>
            <span />
          </div>
          {data.documents.map((document) => (
            <div
              key={document.id}
              className="grid gap-3 border-b border-border px-4 py-4 last:border-0 md:grid-cols-[1.5fr_.7fr_.5fr_.7fr_80px] md:items-center md:gap-4"
            >
              <div className="flex min-w-0 items-center gap-3">
                <span className="rounded-lg border border-border bg-elevated p-2 text-[color:var(--brand)]">
                  <FileText className="h-4 w-4" />
                </span>
                <div className="min-w-0">
                  <p className="truncate text-xs font-semibold">{document.title}</p>
                  <p className="mt-0.5 truncate text-[10px] text-muted-foreground">
                    {document.description ?? document.file_name}
                  </p>
                </div>
              </div>
              <span className="text-xs text-muted-foreground">
                {statusLabel(document.document_type)}
              </span>
              <span className="text-xs">{document.version}</span>
              <span className="text-xs text-muted-foreground">
                {formatDate(document.shared_at)}
              </span>
              <div>
                {document.file_url ? (
                  <a
                    href={document.file_url}
                    target="_blank"
                    rel="noreferrer"
                    className="inline-flex items-center gap-1 text-[11px] font-semibold text-[color:var(--brand)]"
                  >
                    <Download className="h-3 w-3" />
                    Open
                  </a>
                ) : (
                  <span className="text-[10px] text-muted-foreground">Unavailable</span>
                )}
              </div>
            </div>
          ))}
        </div>
      ) : (
        <EmptyState
          icon={FolderOpen}
          title="No documents shared"
          body="Approved project charters, requirements, release notes, user guides, and training documents will appear here."
        />
      )}
    </div>
  );
}

function DeliverablesView({ deliverables }: { deliverables: ClientDeliverable[] }) {
  const groups: Array<{ status: ClientDeliverable["status"]; title: string }> = [
    { status: "in_progress", title: "In progress" },
    { status: "planned", title: "Planned" },
    { status: "completed", title: "Completed" },
  ];
  return (
    <div className="space-y-5">
      <ViewHeader
        eyebrow="Client deliverables"
        title="Deliverable register"
        description="Follow deliverables from planning through completion and access shared outputs."
      />
      {deliverables.length ? (
        <div className="grid gap-4 xl:grid-cols-3">
          {groups.map((group) => {
            const items = deliverables.filter((item) => item.status === group.status);
            return (
              <Card key={group.status}>
                <SectionHeader
                  title={group.title}
                  sub={`${items.length} ${items.length === 1 ? "deliverable" : "deliverables"}`}
                  right={<StatusTag value={group.status} />}
                />
                {items.length ? (
                  <div className="space-y-2">
                    {items.map((item) => (
                      <article
                        key={item.id}
                        className="rounded-lg border border-border bg-elevated/40 p-3"
                      >
                        <p className="text-xs font-semibold">{item.title}</p>
                        {item.description ? (
                          <p className="mt-1 line-clamp-2 text-[10px] leading-4 text-muted-foreground">
                            {item.description}
                          </p>
                        ) : null}
                        <div className="mt-3 flex items-center justify-between gap-3">
                          <span className="text-[10px] text-muted-foreground">
                            {item.due_date
                              ? `Due ${formatDate(item.due_date)}`
                              : item.completed_at
                                ? `Completed ${formatDate(item.completed_at)}`
                                : "Date not set"}
                          </span>
                          {item.file_url ? (
                            <a
                              href={item.file_url}
                              target="_blank"
                              rel="noreferrer"
                              className="inline-flex items-center gap-1 text-[10px] font-semibold text-[color:var(--brand)]"
                            >
                              <Download className="h-3 w-3" />
                              Download
                            </a>
                          ) : null}
                        </div>
                      </article>
                    ))}
                  </div>
                ) : (
                  <p className="rounded-lg border border-dashed border-border p-4 text-center text-[10px] text-muted-foreground">
                    No {group.title.toLowerCase()} deliverables
                  </p>
                )}
              </Card>
            );
          })}
        </div>
      ) : (
        <EmptyState
          icon={FileCheck2}
          title="No deliverables published"
          body="Client-visible deliverables will appear here as the delivery plan is published."
        />
      )}
    </div>
  );
}

function ChangeRequestDialog({
  projectId,
  open,
  onOpenChange,
}: {
  projectId: string;
  open: boolean;
  onOpenChange: (open: boolean) => void;
}) {
  const mutation = useSubmitClientChangeRequest(projectId);
  const [title, setTitle] = useState("");
  const [description, setDescription] = useState("");
  const [justification, setJustification] = useState("");
  const [priority, setPriority] = useState<"low" | "medium" | "high" | "critical">("medium");

  const reset = () => {
    setTitle("");
    setDescription("");
    setJustification("");
    setPriority("medium");
    mutation.reset();
  };
  const submit = (event: FormEvent) => {
    event.preventDefault();
    mutation.mutate(
      {
        title: title.trim(),
        description: description.trim(),
        business_justification: justification.trim() || null,
        priority,
      },
      {
        onSuccess: () => {
          reset();
          onOpenChange(false);
        },
      },
    );
  };
  return (
    <Dialog
      open={open}
      onOpenChange={(next) => {
        if (!next && !mutation.isPending) reset();
        onOpenChange(next);
      }}
    >
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Submit a change request</DialogTitle>
          <DialogDescription>
            Describe the requested change and why it matters. Your delivery team will review scope,
            timing, and impact.
          </DialogDescription>
        </DialogHeader>
        <form onSubmit={submit} className="space-y-4">
          <label className="block text-xs font-medium">
            Request title
            <Input
              value={title}
              onChange={(event) => setTitle(event.target.value)}
              className="mt-1.5"
              placeholder="e.g. Add a regional approval workflow"
              minLength={3}
              maxLength={160}
              required
            />
          </label>
          <label className="block text-xs font-medium">
            Description
            <Textarea
              value={description}
              onChange={(event) => setDescription(event.target.value)}
              className="mt-1.5 min-h-28"
              placeholder="What needs to change? Include the desired outcome."
              minLength={10}
              maxLength={5000}
              required
            />
          </label>
          <label className="block text-xs font-medium">
            Business justification{" "}
            <span className="font-normal text-muted-foreground">(optional)</span>
            <Textarea
              value={justification}
              onChange={(event) => setJustification(event.target.value)}
              className="mt-1.5 min-h-20"
              placeholder="Why is this change valuable or necessary?"
              maxLength={3000}
            />
          </label>
          <label className="block text-xs font-medium">
            Priority
            <select
              value={priority}
              onChange={(event) => setPriority(event.target.value as typeof priority)}
              className="mt-1.5 h-9 w-full rounded-md border border-border bg-background px-3 text-xs"
            >
              <option value="low">Low</option>
              <option value="medium">Medium</option>
              <option value="high">High</option>
              <option value="critical">Critical</option>
            </select>
          </label>
          {mutation.isError ? (
            <p className="text-xs text-[color:var(--danger)]" role="alert">
              {mutation.error instanceof Error
                ? mutation.error.message
                : "Unable to submit this request."}
            </p>
          ) : null}
          <DialogFooter>
            <Button
              type="button"
              variant="outline"
              onClick={() => onOpenChange(false)}
              disabled={mutation.isPending}
            >
              Cancel
            </Button>
            <Button
              type="submit"
              disabled={
                mutation.isPending || title.trim().length < 3 || description.trim().length < 10
              }
            >
              {mutation.isPending ? "Submitting…" : "Submit request"}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}

function ChangesView({
  data,
}: {
  data: NonNullable<ReturnType<typeof useClientProjectDashboardQuery>["data"]>;
}) {
  const [open, setOpen] = useState(false);
  const orderedStatuses: ClientChangeRequestStatus[] = [
    "submitted",
    "under_review",
    "approved",
    "rejected",
    "implemented",
  ];
  return (
    <div className="space-y-5">
      <ViewHeader
        eyebrow="Change requests"
        title="Scope change tracker"
        description="Submit a new request and follow it from review through decision and implementation."
        action={
          <Button size="sm" onClick={() => setOpen(true)}>
            <Plus className="mr-2 h-3.5 w-3.5" />
            New request
          </Button>
        }
      />
      <div className="grid grid-cols-2 gap-3 lg:grid-cols-5">
        {orderedStatuses.map((status) => (
          <MetricTile
            key={status}
            label={statusLabel(status)}
            value={data.change_requests.filter((item) => item.status === status).length}
            tone={
              status === "rejected"
                ? "danger"
                : status === "implemented" || status === "approved"
                  ? "success"
                  : status === "under_review"
                    ? "warning"
                    : "neutral"
            }
          />
        ))}
      </div>
      {data.change_requests.length ? (
        <div className="overflow-hidden rounded-lg border border-border bg-card">
          {data.change_requests.map((request) => (
            <article key={request.id} className="border-b border-border p-4 last:border-0">
              <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
                <div>
                  <div className="flex flex-wrap items-center gap-2">
                    <StatusTag value={request.status} />
                    <StatusTag
                      value={request.priority}
                      label={`${statusLabel(request.priority)} priority`}
                    />
                    <span className="text-[10px] text-muted-foreground">
                      Submitted {formatDate(request.created_at)}
                    </span>
                  </div>
                  <h3 className="mt-2 text-sm font-semibold">{request.title}</h3>
                  <p className="mt-1 max-w-3xl text-xs leading-5 text-muted-foreground">
                    {request.description}
                  </p>
                </div>
                <span className="shrink-0 text-[10px] text-muted-foreground">
                  Updated {formatDate(request.updated_at)}
                </span>
              </div>
              {request.decision_notes ? (
                <div className="mt-3 rounded-lg border border-border bg-elevated/50 p-3 text-xs">
                  <span className="font-semibold">Decision note: </span>
                  {request.decision_notes}
                </div>
              ) : null}
            </article>
          ))}
        </div>
      ) : (
        <EmptyState
          icon={GitPullRequest}
          title="No change requests"
          body="You have not submitted any project change requests."
          action={
            <Button size="sm" onClick={() => setOpen(true)}>
              <Plus className="mr-2 h-3.5 w-3.5" />
              Submit your first request
            </Button>
          }
        />
      )}
      <ChangeRequestDialog
        projectId={data.overview.project_id}
        open={open}
        onOpenChange={setOpen}
      />
    </div>
  );
}

function MeetingCard({ meeting }: { meeting: ClientMeeting }) {
  return (
    <Card>
      <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
        <div className="flex gap-3">
          <span className="rounded-lg border border-border bg-elevated p-2 text-[color:var(--brand)]">
            <Users className="h-4 w-4" />
          </span>
          <div>
            <div className="flex flex-wrap items-center gap-2">
              <h3 className="text-sm font-semibold">{meeting.title}</h3>
              <StatusTag value={meeting.status} />
            </div>
            <p className="mt-1 text-[11px] text-muted-foreground">
              {formatDate(meeting.starts_at, true)} · {meeting.duration_minutes} minutes
            </p>
          </div>
        </div>
        {meeting.status === "scheduled" && meeting.meeting_url ? (
          <a href={meeting.meeting_url} target="_blank" rel="noreferrer">
            <Button size="sm">Join meeting</Button>
          </a>
        ) : null}
      </div>
      <div className="mt-4 grid gap-3 lg:grid-cols-2">
        <div className="rounded-lg border border-border bg-elevated/40 p-3">
          <p className="text-[10px] font-semibold uppercase tracking-wider text-muted-foreground">
            Agenda
          </p>
          <p className="mt-2 whitespace-pre-line text-xs leading-5">
            {meeting.agenda ?? "Agenda has not been published."}
          </p>
        </div>
        <div className="rounded-lg border border-border bg-elevated/40 p-3">
          <p className="text-[10px] font-semibold uppercase tracking-wider text-muted-foreground">
            Minutes
          </p>
          <p className="mt-2 whitespace-pre-line text-xs leading-5">
            {meeting.minutes ??
              (meeting.status === "completed"
                ? "Minutes have not been published."
                : "Available after the meeting.")}
          </p>
        </div>
      </div>
      {meeting.action_items.length ? (
        <div className="mt-3">
          <p className="mb-2 text-[10px] font-semibold uppercase tracking-wider text-muted-foreground">
            Action items
          </p>
          <div className="space-y-1.5">
            {meeting.action_items.map((item, index) => (
              <div
                key={`${meeting.id}-${index}`}
                className="flex flex-wrap items-center justify-between gap-2 rounded-lg border border-border px-3 py-2 text-xs"
              >
                <span>{item.title}</span>
                <span className="text-[10px] text-muted-foreground">
                  {item.owner ?? "Owner TBD"}
                  {item.due_date ? ` · Due ${formatDate(item.due_date)}` : ""}
                </span>
              </div>
            ))}
          </div>
        </div>
      ) : null}
    </Card>
  );
}

function MeetingsView({ meetings }: { meetings: ClientMeeting[] }) {
  const now = Date.now();
  const upcoming = meetings
    .filter((item) => item.status === "scheduled" && new Date(item.starts_at).getTime() >= now)
    .sort((a, b) => a.starts_at.localeCompare(b.starts_at));
  const past = meetings.filter(
    (item) => !upcoming.some((upcomingMeeting) => upcomingMeeting.id === item.id),
  );
  return (
    <div className="space-y-5">
      <ViewHeader
        eyebrow="Client meetings"
        title="Meetings, minutes & actions"
        description="Review upcoming sessions, agendas, published minutes, and follow-up actions."
      />
      {meetings.length ? (
        <>
          <div>
            <h3 className="mb-3 text-xs font-semibold uppercase tracking-wider text-muted-foreground">
              Upcoming meetings · {upcoming.length}
            </h3>
            <div className="space-y-3">
              {upcoming.length ? (
                upcoming.map((meeting) => <MeetingCard key={meeting.id} meeting={meeting} />)
              ) : (
                <EmptyState
                  icon={CalendarDays}
                  title="No upcoming meetings"
                  body="There are no client meetings scheduled."
                />
              )}
            </div>
          </div>
          {past.length ? (
            <div>
              <h3 className="mb-3 text-xs font-semibold uppercase tracking-wider text-muted-foreground">
                Previous meetings · {past.length}
              </h3>
              <div className="space-y-3">
                {past.map((meeting) => (
                  <MeetingCard key={meeting.id} meeting={meeting} />
                ))}
              </div>
            </div>
          ) : null}
        </>
      ) : (
        <EmptyState
          icon={CalendarDays}
          title="No meetings published"
          body="Upcoming meetings, agendas, minutes, and action items will appear here."
        />
      )}
    </div>
  );
}

const NOTIFICATION_ICONS: Record<ClientNotification["notification_type"], typeof Bell> = {
  report_published: FileText,
  milestone_completed: CheckCircle2,
  risk_updated: AlertTriangle,
  document_shared: FolderOpen,
  meeting_scheduled: CalendarDays,
};

function NotificationsView({ notifications }: { notifications: ClientNotification[] }) {
  return (
    <div className="space-y-5">
      <ViewHeader
        eyebrow="Project notifications"
        title="Recent project updates"
        description="Published project events, shared content, risk updates, and scheduled meetings."
      />
      {notifications.length ? (
        <div className="overflow-hidden rounded-lg border border-border bg-card">
          {notifications.map((notification) => {
            const Icon = NOTIFICATION_ICONS[notification.notification_type];
            const content = (
              <div className="flex items-center gap-3 border-b border-border px-4 py-3.5 text-left last:border-0 hover:bg-elevated/40">
                <span className="rounded-full border border-border bg-elevated p-2 text-[color:var(--brand)]">
                  <Icon className="h-3.5 w-3.5" />
                </span>
                <div className="min-w-0 flex-1">
                  <p className="text-xs font-semibold">{notification.title}</p>
                  <p className="mt-0.5 truncate text-[10px] text-muted-foreground">
                    {notification.detail ?? statusLabel(notification.notification_type)}
                  </p>
                </div>
                <span className="shrink-0 text-[10px] text-muted-foreground">
                  {formatDate(notification.occurred_at)}
                </span>
                {notification.href ? (
                  <ChevronRight className="h-3.5 w-3.5 shrink-0 text-muted-foreground" />
                ) : null}
              </div>
            );
            return notification.href ? (
              <a key={notification.id} href={notification.href}>
                {content}
              </a>
            ) : (
              <div key={notification.id}>{content}</div>
            );
          })}
        </div>
      ) : (
        <EmptyState
          icon={Bell}
          title="No notifications"
          body="New reports, completed milestones, shared documents, risk updates, and meeting invitations will appear here."
        />
      )}
    </div>
  );
}

function ErrorState({ onRetry }: { onRetry: () => void }) {
  return (
    <Card>
      <EmptyState
        icon={AlertTriangle}
        title="Project workspace unavailable"
        body="We could not load the client-safe project workspace. Your project data remains protected."
        action={
          <Button size="sm" variant="outline" onClick={onRetry}>
            <RefreshCw className="mr-2 h-3.5 w-3.5" />
            Try again
          </Button>
        }
      />
    </Card>
  );
}

export function ClientProjectWorkspace({
  activeView,
  onViewChange,
}: {
  activeView: ClientWorkspaceView;
  onViewChange: (view: ClientWorkspaceView) => void;
}) {
  const portfolioQuery = useQuery(deliveryPortfolioQueryOptions);
  const portfolio = summarizeClientPortfolio(portfolioQuery.data);
  const [projectId, setProjectId] = useState("");

  useEffect(() => {
    if (!projectId && portfolio.projects.length) setProjectId(portfolio.projects[0]!.id);
    if (
      projectId &&
      portfolio.projects.length &&
      !portfolio.projects.some((project) => project.id === projectId)
    ) {
      setProjectId(portfolio.projects[0]!.id);
    }
  }, [portfolio.projects, projectId]);

  const dashboardQuery = useClientProjectDashboardQuery(projectId || null);
  const data = dashboardQuery.data;

  if (portfolioQuery.isLoading && !portfolioQuery.isError) return <PageLoadingScreen />;
  if (portfolioQuery.isError) return <ErrorState onRetry={() => void portfolioQuery.refetch()} />;
  if (!portfolio.projects.length) {
    return (
      <Card>
        <EmptyState
          icon={LayoutDashboard}
          title="No assigned projects"
          body="A client project must be assigned to your account before the dashboard can be shown."
        />
      </Card>
    );
  }

  const viewContent = data
    ? ({
        overview: <OverviewView data={data} onNavigate={onViewChange} />,
        progress: (
          <ProgressView
            milestones={data.milestones}
            completion={data.overview.completion_percentage}
          />
        ),
        risks: <RisksView risks={data.risks} />,
        actions: <ActionsView actions={data.client_actions} />,
        summary: <SummaryView data={data} />,
        documents: <DocumentsView data={data} />,
        deliverables: <DeliverablesView deliverables={data.deliverables} />,
        changes: <ChangesView data={data} />,
        meetings: <MeetingsView meetings={data.meetings} />,
        notifications: <NotificationsView notifications={data.notifications} />,
      } satisfies Record<ClientWorkspaceView, ReactNode>)
    : null;

  return (
    <div className="space-y-4">
      <div className="flex flex-col gap-3 rounded-lg border border-border bg-card px-4 py-3 sm:flex-row sm:items-center sm:justify-between">
        <div>
          <p className="text-[10px] font-semibold uppercase tracking-[0.16em] text-muted-foreground">
            Client project workspace
          </p>
          <p className="mt-0.5 text-xs text-muted-foreground">
            All information is filtered to approved client-visible sources.
          </p>
        </div>
        <label className="flex items-center gap-2 text-[10px] font-semibold uppercase tracking-wider text-muted-foreground">
          Project
          <select
            value={projectId}
            onChange={(event) => setProjectId(event.target.value)}
            className="h-9 min-w-52 rounded-md border border-border bg-background px-3 text-xs font-medium normal-case tracking-normal text-foreground"
          >
            {portfolio.projects.map((project) => (
              <option key={project.id} value={project.id}>
                {project.name}
              </option>
            ))}
          </select>
        </label>
      </div>

      <main className="min-w-0">
        {dashboardQuery.isLoading && !dashboardQuery.isError ? (
          <PageLoadingScreen />
        ) : dashboardQuery.isError || !viewContent ? (
          <ErrorState onRetry={() => void dashboardQuery.refetch()} />
        ) : (
          viewContent[activeView]
        )}
      </main>
    </div>
  );
}
