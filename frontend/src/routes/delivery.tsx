import { createFileRoute } from "@tanstack/react-router";
import { LineChart, Line, BarChart, Bar, ResponsiveContainer, XAxis, YAxis, CartesianGrid, Tooltip } from "recharts";
import { useState } from "react";
import { Card, SectionHeader, KpiCard, AiBadge, EvidenceBadge, StatusPill } from "@/components/bsg/widgets";
import { projects, rootCauses, recommendations, confidenceForecast } from "@/lib/bsg/data";

export const Route = createFileRoute("/delivery")({ component: DeliveryPage });

const axis = { tick: { fill: "#8b92a5", fontSize: 11 }, axisLine: { stroke: "#2a2d3a" }, tickLine: { stroke: "#2a2d3a" } };
const tip = { backgroundColor: "#20242f", border: "1px solid #2a2d3a", borderRadius: 8, fontSize: 12, color: "#f0f2f7" };

function DeliveryPage() {
  type Msg = { role: "ai" | "user"; text: string };
  const [messages, setMessages] = useState<Msg[]>([
    { role: "ai", text: "I'm tracking 3 projects at risk this week. Pulse Medical Imaging has the highest risk score (61% confidence) due to IAA drift in radiology." },
  ]);
  const [input, setInput] = useState("");

  const send = (q: string) => {
    setMessages((m) => [
      ...m,
      { role: "user" as const, text: q },
      { role: "ai" as const, text: `Based on 4 evidence sources, ${q.toLowerCase().includes("risk") ? "Nimbus, Pulse and Helios are flagged. Primary drivers: capacity shortfall and IAA drift." : "throughput declined 8% on Pulse this week due to a 12% absenteeism spike in the radiology pod."}` },
    ]);
    setInput("");
  };

  return (
    <div className="grid grid-cols-1 gap-5 lg:grid-cols-10">
      <div className="space-y-5 lg:col-span-7">
        <div className="grid grid-cols-2 gap-4 lg:grid-cols-4">
          <KpiCard label="Throughput" value="1,420/d" delta="+3.4% WoW" tone="success" />
          <KpiCard label="Schedule Confidence" value="87%" delta="−1.2 pts" tone="warning" />
          <KpiCard label="At-Risk Projects" value="3" delta="+1 this week" tone="danger" />
          <KpiCard label="Milestone Hit Rate" value="92%" delta="+0.5%" tone="success" />
        </div>

        <Card>
          <SectionHeader title="Root Cause Analysis" sub="Why is Pulse Medical Imaging at risk?" right={<AiBadge confidence={87} />} />
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
          <div className="mt-3 flex flex-wrap gap-1.5 text-[10px]">
            <span className="rounded border border-border bg-elevated px-2 py-0.5 text-muted-foreground">📎 attendance-log-W24.csv</span>
            <span className="rounded border border-border bg-elevated px-2 py-0.5 text-muted-foreground">📎 rework-batch-22.json</span>
            <span className="rounded border border-border bg-elevated px-2 py-0.5 text-muted-foreground">📎 sla-review-W24.pdf</span>
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
                <div className="mt-2 flex items-center justify-between gap-2">
                  <select className="rounded border border-border bg-card px-2 py-1 text-[11px]">
                    <option>Owner: Maya Chen</option>
                    <option>Owner: Priya R.</option>
                    <option>Owner: Arben K.</option>
                  </select>
                  <div className="flex gap-1.5">
                    <button className="rounded bg-[color:var(--brand)] px-2.5 py-1 text-[11px] font-medium text-[color:var(--brand-foreground)]">Accept</button>
                    <button className="rounded border border-border px-2.5 py-1 text-[11px]">Reject</button>
                  </div>
                </div>
              </div>
            ))}
          </div>
        </Card>

        <Card>
          <SectionHeader title="Confidence Trend & 4-Week Forecast" sub="Schedule confidence · 16 weeks + forecast" />
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
          <SectionHeader title="Project Performance" />
          <div className="overflow-x-auto">
            <table className="w-full text-xs">
              <thead className="text-left text-muted-foreground">
                <tr className="border-b border-border">
                  <th className="py-2 pr-3 font-medium">Project</th>
                  <th className="py-2 pr-3 font-medium">Client</th>
                  <th className="py-2 pr-3 font-medium">Throughput</th>
                  <th className="py-2 pr-3 font-medium">Confidence</th>
                  <th className="py-2 pr-3 font-medium">Risk</th>
                  <th className="py-2 pr-3 font-medium">Updated</th>
                  <th className="py-2 pr-3 font-medium"></th>
                </tr>
              </thead>
              <tbody>
                {projects.map((p) => (
                  <tr key={p.id} className="border-b border-border/50">
                    <td className="py-2.5 pr-3 font-medium">{p.name}</td>
                    <td className="py-2.5 pr-3 text-muted-foreground">{p.client}</td>
                    <td className="py-2.5 pr-3">{p.throughput}/d</td>
                    <td className="py-2.5 pr-3">{p.confidence}%</td>
                    <td className="py-2.5 pr-3"><StatusPill status={p.risk} /></td>
                    <td className="py-2.5 pr-3 text-muted-foreground">{p.lastUpdated}</td>
                    <td className="py-2.5 pr-3"><button className="rounded border border-border px-2 py-0.5 text-[11px]">Open</button></td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </Card>
      </div>

      <div className="lg:col-span-3">
        <Card className="sticky top-20">
          <SectionHeader title="Ask Delivery Agent" sub="Evidence-backed answers" right={<AiBadge />} />
          <div className="mb-3 flex flex-wrap gap-1.5">
            {["Which projects are at risk?", "Why did throughput decline?", "What's blocking Helios?"].map((s) => (
              <button key={s} onClick={() => send(s)} className="rounded-full border border-border bg-elevated px-2.5 py-1 text-[11px] hover:bg-card">{s}</button>
            ))}
          </div>
          <div className="mb-3 max-h-[420px] space-y-2 overflow-y-auto">
            {messages.map((m, i) => (
              <div key={i} className={m.role === "ai" ? "rounded-md border border-border bg-elevated p-2.5 text-xs" : "rounded-md bg-[color:var(--brand)]/10 p-2.5 text-xs"}>
                <div className="mb-1 text-[10px] font-semibold uppercase tracking-wider text-muted-foreground">{m.role === "ai" ? "Delivery Agent" : "You"}</div>
                <div>{m.text}</div>
                {m.role === "ai" && (
                  <div className="mt-2 flex flex-wrap gap-1">
                    <span className="rounded border border-border bg-card px-1.5 py-0.5 text-[9px]">📎 Source 1</span>
                    <span className="rounded border border-border bg-card px-1.5 py-0.5 text-[9px]">📎 Source 2</span>
                  </div>
                )}
              </div>
            ))}
          </div>
          <form onSubmit={(e) => { e.preventDefault(); if (input.trim()) send(input); }} className="flex gap-2">
            <input value={input} onChange={(e) => setInput(e.target.value)} placeholder="Ask about delivery…" className="flex-1 rounded border border-border bg-card px-2.5 py-1.5 text-xs outline-none focus:border-[color:var(--brand)]" />
            <button type="submit" className="rounded bg-[color:var(--brand)] px-3 py-1.5 text-xs font-medium text-[color:var(--brand-foreground)]">Send</button>
          </form>
        </Card>
      </div>
    </div>
  );
}
