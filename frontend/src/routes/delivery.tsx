import { createFileRoute } from "@tanstack/react-router";
import { useQuery } from "@tanstack/react-query";
import { LineChart, Line, ResponsiveContainer, XAxis, YAxis, CartesianGrid, Tooltip } from "recharts";
import { useMemo, useState } from "react";
import { Card, SectionHeader, KpiCard, AiBadge, EvidenceBadge, StatusPill } from "@/components/bsg/widgets";
import { confidenceForecast, recommendations, rootCauses } from "@/lib/bsg/data";
import { fetchRiskAlerts, fetchThroughput, listProjects } from "@/lib/api";

export const Route = createFileRoute("/delivery")({ component: DeliveryPage });

const axis = { tick: { fill: "#8b92a5", fontSize: 11 }, axisLine: { stroke: "#2a2d3a" }, tickLine: { stroke: "#2a2d3a" } };
const tip = { backgroundColor: "#20242f", border: "1px solid #2a2d3a", borderRadius: 8, fontSize: 12, color: "#f0f2f7" };

function DeliveryPage() {
  type Msg = { role: "ai" | "user"; text: string };
  const [messages, setMessages] = useState<Msg[]>([
    { role: "ai", text: "Select a project to view live throughput and quality drift alerts." },
  ]);
  const [input, setInput] = useState("");

  const { data: projects = [] } = useQuery({ queryKey: ["projects"], queryFn: listProjects });
  const [projectId, setProjectId] = useState<string | undefined>(undefined);
  const activeProjectId = projectId ?? projects[0]?.id;

  const { data: throughput = [] } = useQuery({
    queryKey: ["throughput", activeProjectId],
    queryFn: () => fetchThroughput(activeProjectId!),
    enabled: Boolean(activeProjectId),
  });

  const { data: riskAlerts = [] } = useQuery({
    queryKey: ["risk-alerts", activeProjectId],
    queryFn: () => fetchRiskAlerts(activeProjectId!),
    enabled: Boolean(activeProjectId),
  });

  const latestThroughput = throughput[0];
  const openAlerts = riskAlerts.filter((a) => a.status === "open" || a.status === "acknowledged");
  const qualityDriftAlerts = openAlerts.filter((a) => a.alert_type === "quality_drift");

  const throughputChart = useMemo(
    () =>
      [...throughput]
        .reverse()
        .slice(-8)
        .map((t) => ({
          date: t.snapshot_date,
          units: t.units_completed,
        })),
    [throughput],
  );

  const send = (q: string) => {
    setMessages((m) => [
      ...m,
      { role: "user" as const, text: q },
      {
        role: "ai" as const,
        text: "Delivery agent NL queries are coming in Phase 2. Use the Quality page for live drift analysis.",
      },
    ]);
    setInput("");
  };

  return (
    <div className="grid grid-cols-1 gap-5 lg:grid-cols-10">
      <div className="space-y-5 lg:col-span-7">
        <Card>
          <div className="flex flex-wrap items-center gap-2">
            <label className="text-xs text-muted-foreground">Project</label>
            <select
              className="rounded border border-border bg-card px-2 py-1.5 text-xs"
              value={activeProjectId ?? ""}
              onChange={(e) => setProjectId(e.target.value)}
            >
              {projects.map((p) => (
                <option key={p.id} value={p.id}>
                  {p.name}
                </option>
              ))}
            </select>
          </div>
        </Card>

        <div className="grid grid-cols-2 gap-4 lg:grid-cols-4">
          <KpiCard
            label="7-Day Throughput"
            value={latestThroughput?.rolling_7day_units != null ? `${latestThroughput.rolling_7day_units}/wk` : "—"}
            tone="success"
          />
          <KpiCard
            label="Latest Daily Units"
            value={latestThroughput ? String(latestThroughput.units_completed) : "—"}
            tone="warning"
          />
          <KpiCard
            label="Quality Drift Alerts"
            value={String(qualityDriftAlerts.length)}
            tone={qualityDriftAlerts.length > 0 ? "danger" : "success"}
          />
          <KpiCard
            label="Open Risk Alerts"
            value={String(openAlerts.length)}
            tone={openAlerts.length > 2 ? "danger" : openAlerts.length > 0 ? "warning" : "success"}
          />
        </div>

        <Card>
          <SectionHeader title="Throughput Trend" sub="Last 8 snapshots" />
          {throughputChart.length > 0 ? (
            <ResponsiveContainer width="100%" height={220}>
              <LineChart data={throughputChart}>
                <CartesianGrid stroke="#2a2d3a" strokeDasharray="3 3" />
                <XAxis dataKey="date" {...axis} />
                <YAxis {...axis} />
                <Tooltip contentStyle={tip} />
                <Line dataKey="units" stroke="#0D1240" strokeWidth={2} name="Units completed" />
              </LineChart>
            </ResponsiveContainer>
          ) : (
            <p className="text-xs text-muted-foreground">No throughput snapshots for this project.</p>
          )}
        </Card>

        <Card>
          <SectionHeader title="Risk Alerts" sub="Quality drift and delivery risks (live)" />
          <ul className="space-y-2">
            {openAlerts.length === 0 && (
              <li className="text-xs text-muted-foreground">No open risk alerts for this project.</li>
            )}
            {openAlerts.map((alert) => (
              <li key={alert.id} className="rounded-md border border-border bg-elevated p-3 text-xs">
                <div className="flex items-center gap-2">
                  <StatusPill status={alert.risk_tier === "critical" ? "Critical" : "Warning"} />
                  <span className="font-medium">{alert.title}</span>
                  <span className="rounded-full border border-border px-1.5 py-0.5 text-[10px] text-muted-foreground">
                    {alert.alert_type}
                  </span>
                </div>
                <div className="mt-1 text-muted-foreground">{alert.detail}</div>
                {alert.source_table && (
                  <div className="mt-1 text-[10px] text-muted-foreground">
                    Source: {alert.source_table}
                  </div>
                )}
              </li>
            ))}
          </ul>
        </Card>

        <Card>
          <SectionHeader
            title="Root Cause Analysis"
            sub="Illustrative — delivery agent RCA in Phase 2"
            right={<AiBadge confidence={87} />}
          />
          <div className="space-y-2.5">
            {rootCauses.map((c) => (
              <div key={c.cause}>
                <div className="mb-1 flex items-center justify-between text-xs">
                  <span>{c.cause}</span>
                  <span className="text-muted-foreground">{c.impact}%</span>
                </div>
                <div className="h-2 overflow-hidden rounded bg-elevated">
                  <div className="h-full rounded bg-[color:var(--brand)]" style={{ width: `${c.impact * 2}%` }} />
                </div>
              </div>
            ))}
          </div>
        </Card>

        <Card>
          <SectionHeader title="Mitigation Recommendations" right={<EvidenceBadge />} />
          <div className="space-y-2">
            {recommendations.slice(0, 3).map((r) => (
              <div key={r.title} className="rounded-md border border-border bg-elevated p-3">
                <div className="flex items-center gap-2">
                  <StatusPill status={r.priority} />
                  <AiBadge confidence={r.confidence} />
                </div>
                <div className="mt-1.5 text-sm">{r.title}</div>
              </div>
            ))}
          </div>
        </Card>

        <Card>
          <SectionHeader
            title="Confidence Trend & 4-Week Forecast"
            sub="Forecast model not yet active — illustrative data"
          />
          <ResponsiveContainer width="100%" height={240}>
            <LineChart data={confidenceForecast}>
              <CartesianGrid stroke="#2a2d3a" strokeDasharray="3 3" />
              <XAxis dataKey="week" {...axis} />
              <YAxis {...axis} domain={[50, 100]} />
              <Tooltip contentStyle={tip} />
              <Line dataKey="confidence" stroke="#0D1240" strokeWidth={2} dot={false} name="Confidence" />
              <Line dataKey="forecast" stroke="#0D1240" strokeWidth={2} strokeDasharray="5 5" dot={false} name="Forecast" />
            </LineChart>
          </ResponsiveContainer>
        </Card>

        <Card>
          <SectionHeader title="All Projects" />
          <div className="overflow-x-auto">
            <table className="w-full text-xs">
              <thead className="text-left text-muted-foreground">
                <tr className="border-b border-border">
                  <th className="py-2 pr-3 font-medium">Project</th>
                  <th className="py-2 pr-3 font-medium">Status</th>
                  <th className="py-2 pr-3 font-medium">Vertical</th>
                </tr>
              </thead>
              <tbody>
                {projects.map((p) => (
                  <tr key={p.id} className="border-b border-border/50">
                    <td className="py-2.5 pr-3 font-medium">{p.name}</td>
                    <td className="py-2.5 pr-3 capitalize">{p.status.replace("_", " ")}</td>
                    <td className="py-2.5 pr-3">{p.vertical}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </Card>
      </div>

      <div className="lg:col-span-3">
        <Card className="sticky top-20">
          <SectionHeader title="Ask Delivery Agent" sub="Phase 2 — evidence-backed answers" right={<AiBadge />} />
          <div className="mb-3 flex flex-wrap gap-1.5">
            {["Which projects are at risk?", "Why did throughput decline?"].map((s) => (
              <button
                key={s}
                onClick={() => send(s)}
                className="rounded-full border border-border bg-elevated px-2.5 py-1 text-[11px] hover:bg-card"
              >
                {s}
              </button>
            ))}
          </div>
          <div className="mb-3 max-h-[420px] space-y-2 overflow-y-auto">
            {messages.map((m, i) => (
              <div
                key={i}
                className={
                  m.role === "ai"
                    ? "rounded-md border border-border bg-elevated p-2.5 text-xs"
                    : "rounded-md bg-[color:var(--brand)]/10 p-2.5 text-xs"
                }
              >
                <div className="mb-1 text-[10px] font-semibold uppercase tracking-wider text-muted-foreground">
                  {m.role === "ai" ? "Delivery Agent" : "You"}
                </div>
                <div>{m.text}</div>
              </div>
            ))}
          </div>
          <form
            onSubmit={(e) => {
              e.preventDefault();
              if (input.trim()) send(input);
            }}
            className="flex gap-2"
          >
            <input
              value={input}
              onChange={(e) => setInput(e.target.value)}
              placeholder="Ask about delivery…"
              className="flex-1 rounded border border-border bg-card px-2.5 py-1.5 text-xs outline-none focus:border-[color:var(--brand)]"
            />
            <button
              type="submit"
              className="rounded bg-[color:var(--brand)] px-3 py-1.5 text-xs font-medium text-[color:var(--brand-foreground)]"
            >
              Send
            </button>
          </form>
        </Card>
      </div>
    </div>
  );
}
