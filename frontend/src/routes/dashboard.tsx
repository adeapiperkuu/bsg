import { createFileRoute } from "@tanstack/react-router";
import {
  LineChart, Line, BarChart, Bar, PieChart, Pie, Cell, ResponsiveContainer,
  XAxis, YAxis, CartesianGrid, Tooltip, Legend, ReferenceLine,
} from "recharts";
import { Card, SectionHeader, KpiCard, AiBadge, EvidenceBadge, StatusPill } from "@/components/bsg/widgets";
import {
  kpis, riskTrend, qualityTrend, utilization, alerts, recommendations,
  milestones, activity, healthDistribution, aiSummary,
} from "@/lib/bsg/data";

export const Route = createFileRoute("/dashboard")({ component: Dashboard });

const axisProps = { tick: { fill: "#8b92a5", fontSize: 11 }, axisLine: { stroke: "#2a2d3a" }, tickLine: { stroke: "#2a2d3a" } };
const tooltipStyle = { backgroundColor: "#20242f", border: "1px solid #2a2d3a", borderRadius: 8, fontSize: 12, color: "#f0f2f7" };

function Dashboard() {
  return (
    <div className="space-y-5">
      <div className="grid grid-cols-2 gap-4 lg:grid-cols-4">
        <KpiCard label="Active Projects" value={kpis.activeProjects} delta="+2 this week" tone="success" />
        <KpiCard label="Schedule Confidence" value={`${kpis.scheduleConfidence}%`} delta="−1.2 pts vs last week" tone="warning" />
        <KpiCard label="Open Escalations" value={kpis.openEscalations} delta="2 critical" tone="danger" />
        <KpiCard label="Avg Quality Score" value={kpis.avgQualityScore} delta="+0.3 vs last week" tone="success" />
      </div>

      <div className="grid grid-cols-1 gap-5 lg:grid-cols-3">
        <Card className="lg:col-span-2">
          <SectionHeader title="Delivery Risk Trend" sub="8-week rolling risk score per project" right={<StatusPill status="Warning" />} />
          <ResponsiveContainer width="100%" height={220}>
            <LineChart data={riskTrend}>
              <CartesianGrid stroke="#2a2d3a" strokeDasharray="3 3" />
              <XAxis dataKey="week" {...axisProps} />
              <YAxis {...axisProps} />
              <Tooltip contentStyle={tooltipStyle} />
              <Legend wrapperStyle={{ fontSize: 11, color: "#8b92a5" }} />
              <Line type="monotone" dataKey="Aurora" stroke="#22c55e" strokeWidth={2} dot={false} />
              <Line type="monotone" dataKey="Helios" stroke="#f59e0b" strokeWidth={2} dot={false} />
              <Line type="monotone" dataKey="Nimbus" stroke="#ef4444" strokeWidth={2} dot={false} />
              <Line type="monotone" dataKey="Orion" stroke="#3b82f6" strokeWidth={2} dot={false} />
            </LineChart>
          </ResponsiveContainer>
          <div className="mt-2 text-xs text-muted-foreground">3 at risk this week · <AiBadge confidence={84} /></div>
        </Card>

        <Card>
          <SectionHeader title="Operational Health" sub="Distribution across portfolio" />
          <div className="relative">
            <ResponsiveContainer width="100%" height={220}>
              <PieChart>
                <Pie data={healthDistribution} dataKey="value" innerRadius={55} outerRadius={85} paddingAngle={3} stroke="none">
                  {healthDistribution.map((d) => <Cell key={d.name} fill={d.color} />)}
                </Pie>
                <Tooltip contentStyle={tooltipStyle} />
              </PieChart>
            </ResponsiveContainer>
            <div className="pointer-events-none absolute inset-0 grid place-items-center">
              <div className="text-center">
                <div className="text-2xl font-semibold">28</div>
                <div className="text-[10px] uppercase tracking-wider text-muted-foreground">Projects</div>
              </div>
            </div>
          </div>
          <div className="mt-2 flex flex-wrap gap-3 text-[11px] text-muted-foreground">
            {healthDistribution.map((d) => (
              <span key={d.name} className="flex items-center gap-1.5"><span className="h-2 w-2 rounded-full" style={{ background: d.color }} />{d.name} · {d.value}</span>
            ))}
          </div>
        </Card>

        <Card>
          <SectionHeader title="Quality Trend" sub="Gold-set & IAA · 12 weeks" right={<StatusPill status="Warning" />} />
          <ResponsiveContainer width="100%" height={200}>
            <LineChart data={qualityTrend}>
              <CartesianGrid stroke="#2a2d3a" strokeDasharray="3 3" />
              <XAxis dataKey="week" {...axisProps} />
              <YAxis yAxisId="l" {...axisProps} domain={[80, 100]} />
              <YAxis yAxisId="r" orientation="right" {...axisProps} domain={[0.75, 0.95]} />
              <Tooltip contentStyle={tooltipStyle} />
              <Line yAxisId="l" dataKey="goldAccuracy" stroke="#00c9a7" strokeWidth={2} dot={false} name="Gold Acc %" />
              <Line yAxisId="r" dataKey="iaa" stroke="#3b82f6" strokeWidth={2} dot={false} name="IAA" />
            </LineChart>
          </ResponsiveContainer>
          <div className="mt-2 text-xs"><span className="rounded bg-[color:var(--danger)]/15 px-1.5 py-0.5 text-[10px] font-medium text-[color:var(--danger)]">Drift Alert</span> Radiology subset trending down</div>
        </Card>

        <Card>
          <SectionHeader title="Resource Utilization" sub="By team · threshold 85%" />
          <ResponsiveContainer width="100%" height={220}>
            <BarChart data={utilization} layout="vertical" margin={{ left: 20 }}>
              <CartesianGrid stroke="#2a2d3a" strokeDasharray="3 3" horizontal={false} />
              <XAxis type="number" {...axisProps} domain={[0, 100]} />
              <YAxis dataKey="team" type="category" {...axisProps} width={110} />
              <Tooltip contentStyle={tooltipStyle} />
              <ReferenceLine x={85} stroke="#ef4444" strokeDasharray="4 4" />
              <Bar dataKey="value" fill="#00c9a7" radius={[0, 4, 4, 0]} />
            </BarChart>
          </ResponsiveContainer>
        </Card>

        <Card>
          <SectionHeader title="Critical Alerts" sub="Top 5 active" right={<EvidenceBadge />} />
          <ul className="space-y-2">
            {alerts.map((a) => (
              <li key={a.desc} className="flex items-start justify-between gap-3 rounded-md border border-border bg-elevated p-3">
                <div className="min-w-0">
                  <div className="flex items-center gap-2">
                    <StatusPill status={a.sev} />
                    <span className="truncate text-xs font-medium">{a.project}</span>
                  </div>
                  <div className="mt-1 text-[11px] text-muted-foreground">{a.desc}</div>
                  <div className="mt-1 text-[10px] text-muted-foreground">{a.ts}</div>
                </div>
                <button className="shrink-0 rounded border border-border px-2 py-1 text-[11px] hover:bg-card">View</button>
              </li>
            ))}
          </ul>
        </Card>
      </div>

      <div className="grid grid-cols-1 gap-5 lg:grid-cols-3">
        <Card className="lg:col-span-2">
          <SectionHeader title="AI Recommendations" sub="Generated by Delivery & Workforce agents" right={<AiBadge confidence={88} />} />
          <ul className="space-y-2">
            {recommendations.map((r) => (
              <li key={r.title} className="flex items-center justify-between gap-3 rounded-md border border-border bg-elevated p-3">
                <div className="min-w-0">
                  <div className="flex items-center gap-2">
                    <StatusPill status={r.priority} />
                    <span className="text-[10px] text-muted-foreground">{r.evidence} evidence items</span>
                    <AiBadge confidence={r.confidence} />
                  </div>
                  <div className="mt-1 text-sm">{r.title}</div>
                </div>
                <div className="flex shrink-0 gap-1.5">
                  <button className="rounded bg-[color:var(--brand)] px-2.5 py-1 text-[11px] font-medium text-[color:var(--brand-foreground)]">Take action</button>
                  <button className="rounded border border-border px-2.5 py-1 text-[11px]">Dismiss</button>
                </div>
              </li>
            ))}
          </ul>
        </Card>

        <Card>
          <SectionHeader title="Recent Activity" sub="Last 10 operational events" />
          <ul className="space-y-2.5 text-xs">
            {activity.map((a) => (
              <li key={a.text} className="flex gap-2.5">
                <span className="mt-1 h-1.5 w-1.5 shrink-0 rounded-full bg-[color:var(--brand)]" />
                <div className="min-w-0">
                  <div className="truncate"><span className="font-medium">{a.actor}</span> <span className="text-muted-foreground">· {a.ts}</span></div>
                  <div className="text-muted-foreground">{a.text}</div>
                </div>
              </li>
            ))}
          </ul>
        </Card>
      </div>

      <Card>
        <SectionHeader title="Upcoming Milestones" sub="Sortable across portfolio" />
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
              {milestones.map((m) => (
                <tr key={m.name} className="border-b border-border/50">
                  <td className="py-2.5 pr-3 font-medium">{m.project}</td>
                  <td className="py-2.5 pr-3 text-muted-foreground">{m.name}</td>
                  <td className="py-2.5 pr-3">{m.due}</td>
                  <td className="py-2.5 pr-3">{m.confidence}%</td>
                  <td className="py-2.5 pr-3"><StatusPill status={m.status} /></td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Card>

      <Card>
        <SectionHeader
          title="Executive AI Summary"
          sub="Auto-generated · Week 24 · Reviewed by Maya Chen"
          right={<div className="flex gap-2"><AiBadge confidence={92} label="AI" /><EvidenceBadge /></div>}
        />
        {aiSummary.split("\n\n").map((p, i) => (
          <p key={i} className="mb-3 text-sm leading-6 text-foreground/90">{p}</p>
        ))}
        <div className="mt-2 flex gap-2">
          <button className="rounded border border-border px-3 py-1.5 text-xs hover:bg-elevated">Regenerate</button>
          <button className="rounded bg-[color:var(--brand)] px-3 py-1.5 text-xs font-medium text-[color:var(--brand-foreground)]">Approve & Send</button>
        </div>
      </Card>
    </div>
  );
}
