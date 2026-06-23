import { createFileRoute } from "@tanstack/react-router";
import { LineChart, Line, BarChart, Bar, ResponsiveContainer, XAxis, YAxis, CartesianGrid, Tooltip } from "recharts";
import { Card, SectionHeader, KpiCard } from "@/components/bsg/widgets";
import { confidenceForecast, clients } from "@/lib/bsg/data";
import { Download } from "lucide-react";

export const Route = createFileRoute("/analytics")({ component: AnalyticsPage });
const axis = { tick: { fill: "#8b92a5", fontSize: 11 }, axisLine: { stroke: "#2a2d3a" }, tickLine: { stroke: "#2a2d3a" } };
const tip = { backgroundColor: "#20242f", border: "1px solid #2a2d3a", borderRadius: 8, fontSize: 12, color: "#f0f2f7" };

const regionPerf = [
  { region: "India · Medical", units: 4200, quality: 95 },
  { region: "India · Finance", units: 3100, quality: 93 },
  { region: "India · NLP", units: 2400, quality: 91 },
  { region: "Kosovo · Geo", units: 5100, quality: 96 },
  { region: "Kosovo · Voice", units: 1800, quality: 90 },
  { region: "Kosovo · Docs", units: 3600, quality: 94 },
];

function AnalyticsPage() {
  return (
    <div className="space-y-5">
      <div className="grid grid-cols-2 gap-4 lg:grid-cols-4">
        <KpiCard label="Portfolio Confidence" value="87%" delta="+1.4 pts MTD" tone="success" />
        <KpiCard label="Reports Auto-Drafted" value="142" delta="MTD" />
        <KpiCard label="Hours Saved (Automation)" value="1,820" delta="MTD" tone="success" />
        <KpiCard label="Total Throughput" value="20.2k/d" delta="+5.6%" tone="success" />
      </div>

      <div className="grid grid-cols-1 gap-5 lg:grid-cols-2">
        <Card>
          <SectionHeader title="Confidence Trend (Portfolio)" right={<button className="inline-flex items-center gap-1 rounded border border-border px-2 py-0.5 text-[11px]"><Download className="h-3 w-3" />Export</button>} />
          <ResponsiveContainer width="100%" height={240}>
            <LineChart data={confidenceForecast}>
              <CartesianGrid stroke="#2a2d3a" strokeDasharray="3 3" />
              <XAxis dataKey="week" {...axis} /><YAxis {...axis} domain={[50, 100]} /><Tooltip contentStyle={tip} />
              <Line dataKey="confidence" stroke="#0D1240" strokeWidth={2} dot={false} />
            </LineChart>
          </ResponsiveContainer>
        </Card>

        <Card>
          <SectionHeader title="Cross-Site Performance" sub="India vs Kosovo · units delivered" />
          <ResponsiveContainer width="100%" height={240}>
            <BarChart data={regionPerf}>
              <CartesianGrid stroke="#2a2d3a" strokeDasharray="3 3" />
              <XAxis dataKey="region" {...axis} interval={0} angle={-15} textAnchor="end" height={60} />
              <YAxis {...axis} /><Tooltip contentStyle={tip} />
              <Bar dataKey="units" fill="#0D1240" radius={[4, 4, 0, 0]} />
            </BarChart>
          </ResponsiveContainer>
        </Card>
      </div>

      <Card>
        <SectionHeader title="Cross-Client Performance" right={<button className="inline-flex items-center gap-1 rounded border border-border px-2 py-0.5 text-[11px]"><Download className="h-3 w-3" />Export CSV</button>} />
        <table className="w-full text-xs">
          <thead className="text-left text-muted-foreground"><tr className="border-b border-border"><th className="py-2 pr-3 font-medium">Client</th><th className="py-2 pr-3 font-medium">Projects</th><th className="py-2 pr-3 font-medium">Confidence</th><th className="py-2 pr-3 font-medium">CSAT</th><th className="py-2 pr-3 font-medium">Last Report</th></tr></thead>
          <tbody>{clients.map((c) => (<tr key={c.name} className="border-b border-border/50"><td className="py-2.5 pr-3 font-medium">{c.name}</td><td className="py-2.5 pr-3">{c.projects}</td><td className="py-2.5 pr-3">{c.confidence}%</td><td className="py-2.5 pr-3">{c.csat}/5</td><td className="py-2.5 pr-3 text-muted-foreground">{c.lastReport}</td></tr>))}</tbody>
        </table>
      </Card>

      <Card>
        <SectionHeader title="Automation ROI" sub="Hours saved · reports compiled · agent actions" />
        <div className="grid grid-cols-2 gap-3 md:grid-cols-4 text-xs">
          {[
            { l: "Hours saved (MTD)", v: "1,820" },
            { l: "Reports compiled", v: "142" },
            { l: "Auto-resolved alerts", v: "67" },
            { l: "AI Q&A answered", v: "318" },
            { l: "Calibration triggered", v: "12" },
            { l: "Drafts approved", v: "104" },
            { l: "Escalations summarized", v: "23" },
            { l: "Governance packs", v: "8" },
          ].map((r) => (
            <div key={r.l} className="rounded border border-border bg-elevated p-3"><div className="text-[10px] uppercase tracking-wider text-muted-foreground">{r.l}</div><div className="mt-1 text-lg font-semibold">{r.v}</div></div>
          ))}
        </div>
      </Card>
    </div>
  );
}
