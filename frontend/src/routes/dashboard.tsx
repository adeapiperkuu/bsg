import { lazy, Suspense, useEffect, useMemo, useState } from "react";
import { createFileRoute } from "@tanstack/react-router";
import { useQuery } from "@tanstack/react-query";
import {
  Card,
  SectionHeader,
  KpiCard,
  AiBadge,
  EvidenceBadge,
  StatusPill,
} from "@/components/bsg/widgets";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from "@/components/ui/dialog";
// Import the markdown pieces directly rather than through the components/delivery barrel:
// the barrel re-exports DeliveryChat and its dependency tree (chat input, history popover,
// alert-dialog, popover, use-delivery-chat), none of which the dashboard renders, and a
// barrel import pulls all of it into this route's chunk.
import { DeliveryMarkdown } from "@/components/delivery/delivery-markdown";
import { sanitizeDeliveryMarkdown } from "@/components/delivery/delivery-markdown-utils";
import {
  executiveSummaryQueryOptions,
  prefetchTowerSections,
  useTowerActivityQuery,
  useTowerEscalationsQuery,
  useTowerHealthQuery,
  useTowerPulseQuery,
  useTowerWorkQuery,
} from "@/lib/queries/dashboard";

const DashboardCharts = lazy(() => import("@/features/dashboard/DashboardCharts"));

export const Route = createFileRoute("/dashboard")({
  component: Dashboard,
  loader: ({ context: { queryClient } }) => {
    prefetchTowerSections(queryClient);
  },
});

const RECS_PREVIEW = 3;
const MILESTONES_PREVIEW = 5;
const ACTIVITY_PREVIEW = 3;

function formatRelative(iso: string): string {
  const then = new Date(iso).getTime();
  if (Number.isNaN(then)) return iso;
  const diff = Math.max(0, Date.now() - then);
  const mins = Math.floor(diff / 60000);
  if (mins < 1) return "just now";
  if (mins < 60) return `${mins}m ago`;
  const hrs = Math.floor(mins / 60);
  if (hrs < 24) return `${hrs}h ago`;
  const days = Math.floor(hrs / 24);
  return `${days}d ago`;
}

function formatDueDate(iso: string): string {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  return d.toLocaleDateString(undefined, { month: "short", day: "2-digit" });
}

function confidenceTone(value: number | null): "success" | "warning" | "danger" | "default" {
  if (value == null) return "default";
  if (value >= 85) return "success";
  if (value >= 70) return "warning";
  return "danger";
}

const EVIDENCE_TYPES = "dependency|action|escalation|scope_state|delivery_signal";
const INLINE_EVIDENCE_RE = new RegExp(`\\s*\\((?:${EVIDENCE_TYPES}):[0-9a-fA-F-]{8,}\\)`, "g");
const BOLD_EVIDENCE_RE = new RegExp(`\\*\\*(${EVIDENCE_TYPES}):[0-9a-fA-F-]{8,}\\*\\*`, "g");

function prepareSummary(text: string): string {
  return sanitizeDeliveryMarkdown(text)
    .replace(/^#\s+.+\n+/, "")
    .replace(INLINE_EVIDENCE_RE, "")
    .replace(BOLD_EVIDENCE_RE, (_m, type: string) => `**${type.replace(/_/g, " ")}**`);
}

const ALL = "all";

function FilterDropdown({
  value,
  onChange,
  options,
  allLabel,
  ariaLabel,
}: {
  value: string;
  onChange: (value: string) => void;
  options: string[];
  allLabel: string;
  ariaLabel: string;
}) {
  const humanise = (s: string) =>
    s.replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());
  return (
    <Select value={value} onValueChange={onChange}>
      <SelectTrigger aria-label={ariaLabel} className="h-8 w-[130px] text-xs">
        <SelectValue />
      </SelectTrigger>
      <SelectContent>
        <SelectItem value={ALL}>{allLabel}</SelectItem>
        {options.map((o) => (
          <SelectItem key={o} value={o}>
            {humanise(o)}
          </SelectItem>
        ))}
      </SelectContent>
    </Select>
  );
}

function ChartsSkeleton() {
  return (
    <div className="grid grid-cols-1 items-start gap-5 lg:grid-cols-3">
      <Card className="lg:col-span-2 h-[292px] animate-pulse"><span /></Card>
      <Card className="h-[292px] animate-pulse"><span /></Card>
      <Card className="h-[272px] animate-pulse"><span /></Card>
      <Card className="lg:col-span-2 h-[272px] animate-pulse"><span /></Card>
    </div>
  );
}

function ViewAllButton({ onClick, label }: { onClick: () => void; label: string }) {
  return (
    <button
      onClick={onClick}
      className="mt-2 text-[11px] font-medium text-[color:var(--brand)] hover:underline"
    >
      {label}
    </button>
  );
}

function WeeklySummaryDialog() {
  const [open, setOpen] = useState(false);
  const { data: summary, isLoading } = useQuery({
    ...executiveSummaryQueryOptions,
    enabled: open,
  });
  const summaryBody = summary ? prepareSummary(summary.text) : "";

  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogTrigger asChild>
        <button className="rounded border border-border px-3 py-1.5 text-xs font-medium hover:bg-elevated">
          View Weekly Summary
        </button>
      </DialogTrigger>
      <DialogContent className="max-h-[80vh] max-w-2xl overflow-y-auto">
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2">
            Weekly Executive Summary
            {summary?.generated_by_ai && <AiBadge label="AI" />}
          </DialogTitle>
          {summary && (
            <DialogDescription>
              Week of {formatDueDate(summary.week)} ·{" "}
              {summary.approved ? "Approved" : "Pending review"}
            </DialogDescription>
          )}
        </DialogHeader>
        {isLoading ? (
          <p className="text-sm text-muted-foreground">Loading summary…</p>
        ) : summary ? (
          <DeliveryMarkdown content={summaryBody} />
        ) : (
          <p className="text-sm text-muted-foreground">
            No executive summary has been generated yet.
          </p>
        )}
      </DialogContent>
    </Dialog>
  );
}

function FreshnessStamp({
  updatedAt,
  isFetching,
  hasData,
}: {
  updatedAt: number;
  isFetching: boolean;
  hasData: boolean;
}) {
  const [, forceTick] = useState(0);

  useEffect(() => {
    const id = setInterval(() => forceTick((n) => n + 1), 30_000);
    return () => clearInterval(id);
  }, []);

  if (!hasData) {
    return (
      <span className="text-xs text-muted-foreground">
        {isFetching ? "Loading portfolio…" : null}
      </span>
    );
  }

  return (
    <span className="flex items-center gap-1.5 text-xs text-muted-foreground">
      <span
        className={`size-1.5 rounded-full ${
          isFetching ? "animate-pulse bg-amber-500" : "bg-transparent"
        }`}
        aria-hidden="true"
      />
      <span>Updated {formatRelative(new Date(updatedAt).toISOString())}</span>
      <span className="sr-only">{isFetching ? " — refreshing now" : ""}</span>
    </span>
  );
}

function Dashboard() {
  const pulse = useTowerPulseQuery();
  const escalations = useTowerEscalationsQuery();
  const health = useTowerHealthQuery();
  const work = useTowerWorkQuery();
  const activityQuery = useTowerActivityQuery();

  const healthDistribution = health.data?.healthDistribution ?? [];
  const riskTrend = pulse.data?.riskTrend ?? { series: [], data: [] };
  const qualityTrend = pulse.data?.qualityTrend ?? [];
  const utilization = activityQuery.data?.utilization ?? [];
  const alerts = pulse.data?.alerts ?? [];
  const recommendations = work.data?.recommendations ?? [];
  const milestones = work.data?.milestones ?? [];
  const activity = activityQuery.data?.activity ?? [];

  const totalProjects = pulse.data?.totalProjects ?? 0;
  const atRiskCount = healthDistribution.find((d) => d.name === "At Risk")?.value ?? 0;
  const criticalEscalations = escalations.data?.criticalEscalations ?? 0;

  const sections = [pulse, escalations, health, work, activityQuery];
  const loadedSections = sections.filter((s) => s.data !== undefined);
  const dataUpdatedAt = loadedSections.length
    ? Math.min(...loadedSections.map((s) => s.dataUpdatedAt))
    : 0;
  const isFetching = sections.some((s) => s.isFetching);
  const iaaTrendingDown =
    qualityTrend.length >= 2 &&
    (qualityTrend.at(-1)?.iaa ?? 0) < (qualityTrend.at(-2)?.iaa ?? 0);
  const recConfidence = recommendations.length
    ? Math.round(
        recommendations.reduce((sum, r) => sum + r.confidence, 0) / recommendations.length,
      )
    : null;

  const [showAllRecs, setShowAllRecs] = useState(false);
  const [showAllMilestones, setShowAllMilestones] = useState(false);
  const [showAllActivity, setShowAllActivity] = useState(false);

  const [alertSev, setAlertSev] = useState(ALL);
  const [recPriority, setRecPriority] = useState(ALL);
  const [milestoneStatus, setMilestoneStatus] = useState(ALL);

  const alertSevOptions = useMemo(
    () => Array.from(new Set(alerts.map((a) => a.sev))),
    [alerts],
  );
  const recPriorityOptions = useMemo(
    () => Array.from(new Set(recommendations.map((r) => r.priority))),
    [recommendations],
  );
  const milestoneStatusOptions = useMemo(
    () => Array.from(new Set(milestones.map((m) => m.status))),
    [milestones],
  );

  const filteredAlerts =
    alertSev === ALL ? alerts : alerts.filter((a) => a.sev === alertSev);
  const filteredRecs =
    recPriority === ALL
      ? recommendations
      : recommendations.filter((r) => r.priority === recPriority);
  const filteredMilestones =
    milestoneStatus === ALL
      ? milestones
      : milestones.filter((m) => m.status === milestoneStatus);

  const visibleRecs = showAllRecs ? filteredRecs : filteredRecs.slice(0, RECS_PREVIEW);
  const visibleMilestones = showAllMilestones
    ? filteredMilestones
    : filteredMilestones.slice(0, MILESTONES_PREVIEW);
  const visibleActivity = showAllActivity ? activity : activity.slice(0, ACTIVITY_PREVIEW);

  return (
    <div className="space-y-5">
      {/* Action bar — the full weekly report lives behind an action, not on the page. */}
      <div className="flex items-center justify-end gap-3">
        <FreshnessStamp
          updatedAt={dataUpdatedAt}
          isFetching={isFetching}
          hasData={loadedSections.length > 0}
        />
        <WeeklySummaryDialog />
      </div>

      {/* 1. KPIs — portfolio health at a glance */}
      <div className="grid grid-cols-2 gap-4 lg:grid-cols-4">
        <KpiCard
          label="Active Projects"
          value={pulse.data?.activeProjects ?? "—"}
          delta={totalProjects ? `${totalProjects} total in portfolio` : undefined}
          tone="success"
        />
        <KpiCard
          label="Schedule Confidence"
          value={
            health.data?.scheduleConfidence != null ? `${health.data.scheduleConfidence}%` : "—"
          }
          tone={confidenceTone(health.data?.scheduleConfidence ?? null)}
        />
        <KpiCard
          label="Open Escalations"
          value={escalations.data?.openEscalations ?? "—"}
          delta={criticalEscalations ? `${criticalEscalations} critical` : undefined}
          tone={criticalEscalations ? "danger" : "default"}
        />
        <KpiCard
          label="Avg Quality Score"
          value={pulse.data?.avgQualityScore != null ? pulse.data.avgQualityScore : "—"}
          tone={confidenceTone(pulse.data?.avgQualityScore ?? null)}
        />
      </div>

      {/* 1b. Trend charts — lazily loaded so KPI cards paint first (recharts is heavy). */}
      <Suspense fallback={<ChartsSkeleton />}>
        <DashboardCharts
          riskTrend={riskTrend}
          qualityTrend={qualityTrend}
          utilization={utilization}
          healthDistribution={healthDistribution}
          totalProjects={totalProjects}
          atRiskCount={atRiskCount}
          iaaTrendingDown={iaaTrendingDown}
        />
      </Suspense>

      {/* 2 + 3. Critical Alerts (primary) beside AI Recommendations */}
      <div className="grid grid-cols-1 items-start gap-5 lg:grid-cols-3">
        <Card className="lg:col-span-2">
          <SectionHeader
            title="Critical Alerts"
            sub="What needs attention now"
            right={
              <div className="flex items-center gap-2">
                {alertSevOptions.length > 1 && (
                  <FilterDropdown
                    ariaLabel="Filter alerts by severity"
                    value={alertSev}
                    onChange={setAlertSev}
                    options={alertSevOptions}
                    allLabel="All severities"
                  />
                )}
                <EvidenceBadge />
              </div>
            }
          />
          {alerts.length === 0 ? (
            <p className="rounded-md border border-border bg-elevated p-4 text-xs text-muted-foreground">
              No active alerts across the portfolio.
            </p>
          ) : filteredAlerts.length === 0 ? (
            <p className="rounded-md border border-border bg-elevated p-4 text-xs text-muted-foreground">
              No alerts match this severity.
            </p>
          ) : (
            <ul className="space-y-2">
              {filteredAlerts.map((a) => (
                <li
                  key={`${a.project}-${a.desc}`}
                  className="flex items-start justify-between gap-3 rounded-md border border-border bg-elevated p-3"
                >
                  <div className="min-w-0">
                    <div className="flex items-center gap-2">
                      <StatusPill status={a.sev} />
                      <span className="truncate text-xs font-medium">{a.project}</span>
                    </div>
                    <div className="mt-1 text-[11px] text-muted-foreground">{a.desc}</div>
                    <div className="mt-1 text-[10px] text-muted-foreground">
                      {formatRelative(a.ts)}
                    </div>
                  </div>
                  <button className="shrink-0 rounded border border-border px-2 py-1 text-[11px] hover:bg-card">
                    View
                  </button>
                </li>
              ))}
            </ul>
          )}
        </Card>

        <Card>
          <SectionHeader
            title="AI Recommendations"
            sub="Top actions"
            right={
              <div className="flex items-center gap-2">
                {recPriorityOptions.length > 1 && (
                  <FilterDropdown
                    ariaLabel="Filter recommendations by priority"
                    value={recPriority}
                    onChange={setRecPriority}
                    options={recPriorityOptions}
                    allLabel="All priorities"
                  />
                )}
                {recConfidence != null && <AiBadge confidence={recConfidence} label="AI" />}
              </div>
            }
          />
          {recommendations.length === 0 ? (
            <p className="rounded-md border border-border bg-elevated p-4 text-xs text-muted-foreground">
              No open recommendations.
            </p>
          ) : filteredRecs.length === 0 ? (
            <p className="rounded-md border border-border bg-elevated p-4 text-xs text-muted-foreground">
              No recommendations match this priority.
            </p>
          ) : (
            <>
              <ul className="space-y-2">
                {visibleRecs.map((r) => (
                  <li
                    key={r.title}
                    className="rounded-md border border-border bg-elevated p-3"
                  >
                    <div className="flex items-center gap-2">
                      <StatusPill status={r.priority} />
                      <AiBadge confidence={r.confidence} label="AI" />
                    </div>
                    <div className="mt-1.5 text-xs">{r.title}</div>
                    <div className="mt-2 flex gap-1.5">
                      <button className="rounded bg-[color:var(--brand)] px-2.5 py-1 text-[11px] font-medium text-[color:var(--brand-foreground)]">
                        Take action
                      </button>
                      <button className="rounded border border-border px-2.5 py-1 text-[11px]">
                        Dismiss
                      </button>
                    </div>
                  </li>
                ))}
              </ul>
              {filteredRecs.length > RECS_PREVIEW && (
                <ViewAllButton
                  onClick={() => setShowAllRecs((v) => !v)}
                  label={showAllRecs ? "Show less" : `View all (${filteredRecs.length})`}
                />
              )}
            </>
          )}
        </Card>
      </div>

      {/* 5. Upcoming Milestones — nearest few, full list behind View all */}
      <Card>
        <SectionHeader
          title="Upcoming Milestones"
          sub="Next by due date"
          right={
            milestoneStatusOptions.length > 1 ? (
              <FilterDropdown
                ariaLabel="Filter milestones by status"
                value={milestoneStatus}
                onChange={setMilestoneStatus}
                options={milestoneStatusOptions}
                allLabel="All statuses"
              />
            ) : undefined
          }
        />
        {milestones.length === 0 ? (
          <p className="rounded-md border border-border bg-elevated p-4 text-xs text-muted-foreground">
            No upcoming milestones.
          </p>
        ) : filteredMilestones.length === 0 ? (
          <p className="rounded-md border border-border bg-elevated p-4 text-xs text-muted-foreground">
            No milestones match this status.
          </p>
        ) : (
          <>
            <div className="overflow-x-auto">
              <table className="w-full text-xs">
                <thead className="text-left text-muted-foreground">
                  <tr className="border-b border-border">
                    <th className="py-2 pr-3 font-medium">Project</th>
                    <th className="py-2 pr-3 font-medium">Milestone</th>
                    <th className="py-2 pr-3 font-medium">Due</th>
                    <th className="py-2 pr-3 font-medium">Confidence</th>
                    <th className="py-2 pr-3 font-medium">Status</th>
                  </tr>
                </thead>
                <tbody>
                  {visibleMilestones.map((m) => (
                    <tr key={`${m.project}-${m.name}`} className="border-b border-border/50">
                      <td className="py-2.5 pr-3 font-medium">{m.project}</td>
                      <td className="py-2.5 pr-3 text-muted-foreground">{m.name}</td>
                      <td className="py-2.5 pr-3">{formatDueDate(m.due)}</td>
                      <td className="py-2.5 pr-3">
                        {m.confidence != null ? `${m.confidence}%` : "—"}
                      </td>
                      <td className="py-2.5 pr-3">
                        <StatusPill status={m.status} />
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            {filteredMilestones.length > MILESTONES_PREVIEW && (
              <ViewAllButton
                onClick={() => setShowAllMilestones((v) => !v)}
                label={showAllMilestones ? "Show less" : `View all (${filteredMilestones.length})`}
              />
            )}
          </>
        )}
      </Card>

      {/* Secondary. Recent Activity — collapsed to the latest few */}
      <Card>
        <SectionHeader title="Recent Activity" sub="Latest operational events" />
        {activity.length === 0 ? (
          <p className="text-xs text-muted-foreground">No recent activity.</p>
        ) : (
          <>
            <ul className="space-y-2.5 text-xs">
              {visibleActivity.map((a) => (
                <li key={`${a.actor}-${a.ts}-${a.text}`} className="flex gap-2.5">
                  <span className="mt-1 h-1.5 w-1.5 shrink-0 rounded-full bg-[color:var(--brand)]" />
                  <div className="min-w-0">
                    <div className="truncate">
                      <span className="font-medium">{a.actor}</span>{" "}
                      <span className="text-muted-foreground">· {formatRelative(a.ts)}</span>
                    </div>
                    <div className="text-muted-foreground">{a.text}</div>
                  </div>
                </li>
              ))}
            </ul>
            {activity.length > ACTIVITY_PREVIEW && (
              <ViewAllButton
                onClick={() => setShowAllActivity((v) => !v)}
                label={showAllActivity ? "Show less" : `View all (${activity.length})`}
              />
            )}
          </>
        )}
      </Card>
    </div>
  );
}
