import { useMemo, useState } from "react";
import { createFileRoute } from "@tanstack/react-router";
import { useQuery } from "@tanstack/react-query";
import {
  LineChart,
  Line,
  BarChart,
  Bar,
  PieChart,
  Pie,
  Cell,
  ResponsiveContainer,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  Legend,
  ReferenceLine,
} from "recharts";
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
import { DeliveryMarkdown } from "@/components/delivery";
import { sanitizeDeliveryMarkdown } from "@/components/delivery/delivery-markdown-utils";
import {
  executiveSummaryQueryOptions,
  operationalTowerQueryOptions,
  useOperationalTowerQuery,
} from "@/lib/queries/dashboard";

export const Route = createFileRoute("/dashboard")({
  component: Dashboard,
  loader: async ({ context: { queryClient } }) => {
    await queryClient.prefetchQuery(operationalTowerQueryOptions);
  },
});

// How many rows each secondary list shows before "View all".
const RECS_PREVIEW = 3;
const MILESTONES_PREVIEW = 5;
const ACTIVITY_PREVIEW = 3;

const axisProps = {
  tick: { fill: "#8b92a5", fontSize: 11 },
  axisLine: { stroke: "#2a2d3a" },
  tickLine: { stroke: "#2a2d3a" },
};
const tooltipStyle = {
  backgroundColor: "#20242f",
  border: "1px solid #2a2d3a",
  borderRadius: 8,
  fontSize: 12,
  color: "#f0f2f7",
};

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

/** Strip the redundant top-level H1 and noisy raw evidence UUID tokens for readable display. */
function prepareSummary(text: string): string {
  return sanitizeDeliveryMarkdown(text)
    .replace(/^#\s+.+\n+/, "")
    .replace(INLINE_EVIDENCE_RE, "")
    .replace(BOLD_EVIDENCE_RE, (_m, type: string) => `**${type.replace(/_/g, " ")}**`);
}

const ALL = "all";

/** Compact dropdown filter used in section headers. Values are humanised for display. */
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

/** "View Weekly Summary" — exposes the stored executive summary behind an action (lazy-loaded). */
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

function Dashboard() {
  const { data } = useOperationalTowerQuery();

  const kpis = data?.kpis;
  const healthDistribution = data?.healthDistribution ?? [];
  const riskTrend = data?.riskTrend ?? { series: [], data: [] };
  const qualityTrend = data?.qualityTrend ?? [];
  const utilization = data?.utilization ?? [];
  const alerts = data?.alerts ?? [];
  const recommendations = data?.recommendations ?? [];
  const milestones = data?.milestones ?? [];
  const activity = data?.activity ?? [];

  const totalProjects = kpis?.totalProjects ?? 0;
  const atRiskCount = healthDistribution.find((d) => d.name === "At Risk")?.value ?? 0;
  const criticalEscalations = data?.criticalEscalations ?? 0;
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

  // Dropdown filters for the three list/table sections.
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
      <div className="flex items-center justify-end">
        <WeeklySummaryDialog />
      </div>

      {/* 1. KPIs — portfolio health at a glance */}
      <div className="grid grid-cols-2 gap-4 lg:grid-cols-4">
        <KpiCard
          label="Active Projects"
          value={kpis?.activeProjects ?? "—"}
          delta={totalProjects ? `${totalProjects} total in portfolio` : undefined}
          tone="success"
        />
        <KpiCard
          label="Schedule Confidence"
          value={kpis?.scheduleConfidence != null ? `${kpis.scheduleConfidence}%` : "—"}
          tone={confidenceTone(kpis?.scheduleConfidence ?? null)}
        />
        <KpiCard
          label="Open Escalations"
          value={kpis?.openEscalations ?? "—"}
          delta={criticalEscalations ? `${criticalEscalations} critical` : undefined}
          tone={criticalEscalations ? "danger" : "default"}
        />
        <KpiCard
          label="Avg Quality Score"
          value={kpis?.avgQualityScore != null ? kpis.avgQualityScore : "—"}
          tone={confidenceTone(kpis?.avgQualityScore ?? null)}
        />
      </div>

      {/* 1b. Trend charts — delivery risk, portfolio health, quality, utilization */}
      <div className="grid grid-cols-1 items-start gap-5 lg:grid-cols-3">
        <Card className="lg:col-span-2">
          <SectionHeader
            title="Delivery Risk Trend"
            sub="8-week rolling risk score per project"
            right={<StatusPill status={atRiskCount ? "Warning" : "On Track"} />}
          />
          <ResponsiveContainer width="100%" height={220}>
            <LineChart data={riskTrend.data}>
              <CartesianGrid stroke="#2a2d3a" strokeDasharray="3 3" />
              <XAxis dataKey="week" {...axisProps} />
              <YAxis {...axisProps} />
              <Tooltip contentStyle={tooltipStyle} />
              <Legend wrapperStyle={{ fontSize: 11, color: "#8b92a5" }} />
              {riskTrend.series.map((s) => (
                <Line
                  key={s.name}
                  type="monotone"
                  dataKey={s.name}
                  stroke={s.color}
                  strokeWidth={2}
                  dot={false}
                />
              ))}
            </LineChart>
          </ResponsiveContainer>
          <div className="mt-2 text-xs text-muted-foreground">
            {atRiskCount} at risk this week
          </div>
        </Card>

        <Card>
          <SectionHeader title="Operational Health" sub="Distribution across portfolio" />
          <div className="relative">
            <ResponsiveContainer width="100%" height={220}>
              <PieChart>
                <Pie
                  data={healthDistribution}
                  dataKey="value"
                  innerRadius={55}
                  outerRadius={85}
                  paddingAngle={3}
                  stroke="none"
                >
                  {healthDistribution.map((d) => (
                    <Cell key={d.name} fill={d.color} />
                  ))}
                </Pie>
                <Tooltip contentStyle={tooltipStyle} />
              </PieChart>
            </ResponsiveContainer>
            <div className="pointer-events-none absolute inset-0 grid place-items-center">
              <div className="text-center">
                <div className="text-2xl font-semibold">{totalProjects}</div>
                <div className="text-[10px] uppercase tracking-wider text-muted-foreground">
                  Projects
                </div>
              </div>
            </div>
          </div>
          <div className="mt-2 flex flex-wrap gap-3 text-[11px] text-muted-foreground">
            {healthDistribution.map((d) => (
              <span key={d.name} className="flex items-center gap-1.5">
                <span className="h-2 w-2 rounded-full" style={{ background: d.color }} />
                {d.name} · {d.value}
              </span>
            ))}
          </div>
        </Card>

        <Card>
          <SectionHeader
            title="Quality Trend"
            sub="Gold-set & IAA · 12 weeks"
            right={<StatusPill status={iaaTrendingDown ? "Warning" : "On Track"} />}
          />
          <ResponsiveContainer width="100%" height={200}>
            <LineChart data={qualityTrend}>
              <CartesianGrid stroke="#2a2d3a" strokeDasharray="3 3" />
              <XAxis dataKey="week" {...axisProps} />
              <YAxis yAxisId="l" {...axisProps} domain={[80, 100]} />
              <YAxis yAxisId="r" orientation="right" {...axisProps} domain={[0.75, 0.95]} />
              <Tooltip contentStyle={tooltipStyle} />
              <Line
                yAxisId="l"
                dataKey="goldAccuracy"
                stroke="#0D1240"
                strokeWidth={2}
                dot={false}
                name="Gold Acc %"
              />
              <Line
                yAxisId="r"
                dataKey="iaa"
                stroke="#3b82f6"
                strokeWidth={2}
                dot={false}
                name="IAA"
              />
            </LineChart>
          </ResponsiveContainer>
          {iaaTrendingDown && (
            <div className="mt-2 text-xs">
              <span className="rounded bg-[color:var(--danger)]/15 px-1.5 py-0.5 text-[10px] font-medium text-[color:var(--danger)]">
                Drift Alert
              </span>{" "}
              Inter-annotator agreement trending down
            </div>
          )}
        </Card>

        <Card className="lg:col-span-2">
          <SectionHeader title="Resource Utilization" sub="By team · threshold 85%" />
          <ResponsiveContainer width="100%" height={220}>
            <BarChart data={utilization} layout="vertical" margin={{ left: 20 }}>
              <CartesianGrid stroke="#2a2d3a" strokeDasharray="3 3" horizontal={false} />
              <XAxis type="number" {...axisProps} domain={[0, 100]} />
              <YAxis dataKey="team" type="category" {...axisProps} width={110} />
              <Tooltip contentStyle={tooltipStyle} />
              <ReferenceLine x={85} stroke="#ef4444" strokeDasharray="4 4" />
              <Bar dataKey="value" fill="#0D1240" radius={[0, 4, 4, 0]} />
            </BarChart>
          </ResponsiveContainer>
        </Card>
      </div>

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
