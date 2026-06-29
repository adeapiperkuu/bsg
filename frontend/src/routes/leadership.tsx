import { createFileRoute } from "@tanstack/react-router";
import { useQuery } from "@tanstack/react-query";
import { BarChart, Bar, LineChart, Line, ResponsiveContainer, XAxis, YAxis, CartesianGrid, Tooltip, Legend } from "recharts";
import { Card, SectionHeader, KpiCard, AiBadge } from "@/components/bsg/widgets";
import { healthDistribution } from "@/lib/bsg/data";
import { fetchQualityPortfolio } from "@/lib/api";

export const Route = createFileRoute("/leadership")({ component: Leadership });
const axis = { tick: { fill: "#8b92a5", fontSize: 11 }, axisLine: { stroke: "#2a2d3a" }, tickLine: { stroke: "#2a2d3a" } };
const tip = { backgroundColor: "#20242f", border: "1px solid #2a2d3a", borderRadius: 8, fontSize: 12, color: "#f0f2f7" };

const revenue = Array.from({ length: 12 }, (_, i) => ({ month: `M${i + 1}`, revenue: 1800 + i * 120 + Math.round(Math.sin(i) * 80), margin: 22 + Math.round(Math.sin(i) * 3) }));
const sites = [
  { site: "India · Bangalore", projects: 14, util: 87, revenue: 6200 },
  { site: "India · Pune", projects: 8, util: 82, revenue: 3800 },
  { site: "Kosovo · Pristina", projects: 10, util: 84, revenue: 4400 },
  { site: "Kosovo · Prizren", projects: 6, util: 79, revenue: 2400 },
];

function Leadership() {
  const { data: qualityPortfolio, isLoading: qualityLoading } = useQuery({
    queryKey: ["quality-portfolio"],
    queryFn: fetchQualityPortfolio,
  });

  return (
    <div className="space-y-5">
      <div className="grid grid-cols-2 gap-4 lg:grid-cols-4">
        <KpiCard label="Portfolio Health" value={`${healthDistribution[0].value}/${healthDistribution.reduce((a, b) => a + b.value, 0)} green`} tone="success" />
        <KpiCard label="Revenue MTD" value="$2.84M" delta="+8.2% YoY" tone="success" />
        <KpiCard label="Operating Margin" value="24.6%" delta="+1.1 pts" tone="success" />
        <KpiCard label="Early-Warning Risks" value="3" delta="2 critical" tone="danger" />
      </div>

      <Card>
        <SectionHeader
          title="Quality Portfolio"
          sub={qualityLoading ? "Loading…" : `Week ${qualityPortfolio?.portfolio_week ?? "—"} · live from Quality Intelligence`}
        />
        {qualityPortfolio ? (
          <>
            <div className="mb-4 grid grid-cols-2 gap-3 md:grid-cols-4 text-xs">
              <div className="rounded border border-border bg-elevated p-3">
                <div className="text-[10px] uppercase text-muted-foreground">Projects</div>
                <div className="mt-1 text-xl font-semibold">{qualityPortfolio.projects_total}</div>
              </div>
              <div className="rounded border border-border bg-elevated p-3">
                <div className="text-[10px] uppercase text-muted-foreground">With Drift</div>
                <div className="mt-1 text-xl font-semibold text-[color:var(--danger)]">
                  {qualityPortfolio.projects_with_drift}
                </div>
              </div>
              <div className="rounded border border-border bg-elevated p-3">
                <div className="text-[10px] uppercase text-muted-foreground">Blended Gold Acc</div>
                <div className="mt-1 text-xl font-semibold">
                  {qualityPortfolio.blended_gold_accuracy != null
                    ? `${qualityPortfolio.blended_gold_accuracy}%`
                    : "—"}
                </div>
              </div>
              <div className="rounded border border-border bg-elevated p-3">
                <div className="text-[10px] uppercase text-muted-foreground">Blended Rework</div>
                <div className="mt-1 text-xl font-semibold">
                  {qualityPortfolio.blended_rework_rate != null
                    ? `${qualityPortfolio.blended_rework_rate}%`
                    : "—"}
                </div>
              </div>
            </div>
            <div className="overflow-x-auto">
              <table className="w-full text-xs">
                <thead className="text-left text-muted-foreground">
                  <tr className="border-b border-border">
                    <th className="py-2 pr-3 font-medium">Project</th>
                    <th className="py-2 pr-3 font-medium">Org</th>
                    <th className="py-2 pr-3 font-medium">Status</th>
                    <th className="py-2 pr-3 font-medium">Gold Acc</th>
                    <th className="py-2 pr-3 font-medium">Drift</th>
                  </tr>
                </thead>
                <tbody>
                  {qualityPortfolio.per_project.map((p) => (
                    <tr key={p.project_id} className="border-b border-border/50">
                      <td className="py-2 pr-3 font-medium">{p.name}</td>
                      <td className="py-2 pr-3">{p.org_name}</td>
                      <td className="py-2 pr-3 capitalize">{p.status.replace("_", " ")}</td>
                      <td className="py-2 pr-3">{p.latest_gold_accuracy != null ? `${p.latest_gold_accuracy}%` : "—"}</td>
                      <td className="py-2 pr-3">
                        {p.active_drift_alerts > 0 ? (
                          <span className="rounded-full bg-destructive/15 px-2 py-0.5 text-destructive">
                            {p.active_drift_alerts}
                          </span>
                        ) : (
                          "0"
                        )}
                        {p.data_gap && (
                          <span className="ml-1 rounded-full bg-amber-500/15 px-1.5 py-0.5 text-amber-600">gap</span>
                        )}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </>
        ) : (
          !qualityLoading && (
            <p className="text-xs text-muted-foreground">Quality portfolio data unavailable.</p>
          )
        )}
      </Card>

      <div className="grid grid-cols-1 gap-5 lg:grid-cols-2">
        <Card>
          <SectionHeader title="Revenue & Margin" sub="Trailing 12 months" />
          <ResponsiveContainer width="100%" height={240}>
            <LineChart data={revenue}><CartesianGrid stroke="#2a2d3a" strokeDasharray="3 3" /><XAxis dataKey="month" {...axis} /><YAxis yAxisId="l" {...axis} /><YAxis yAxisId="r" orientation="right" {...axis} /><Tooltip contentStyle={tip} /><Legend wrapperStyle={{ fontSize: 11 }} /><Line yAxisId="l" dataKey="revenue" stroke="#0D1240" strokeWidth={2} name="Revenue ($K)" /><Line yAxisId="r" dataKey="margin" stroke="#3b82f6" strokeWidth={2} name="Margin %" /></LineChart>
          </ResponsiveContainer>
        </Card>

        <Card>
          <SectionHeader title="Cross-Site Performance" sub="India vs Kosovo" />
          <ResponsiveContainer width="100%" height={240}>
            <BarChart data={sites}><CartesianGrid stroke="#2a2d3a" strokeDasharray="3 3" /><XAxis dataKey="site" {...axis} interval={0} angle={-10} textAnchor="end" height={60} /><YAxis {...axis} /><Tooltip contentStyle={tip} /><Bar dataKey="revenue" fill="#0D1240" radius={[4, 4, 0, 0]} name="Revenue ($K)" /></BarChart>
          </ResponsiveContainer>
        </Card>
      </div>

      <Card>
        <SectionHeader title="Early-Warning Risk Calculator" right={<AiBadge confidence={86} />} />
        <ul className="space-y-2 text-xs">
          {[
            { r: "Capacity shortfall — India · NLP (Q3 forecast)", s: "Critical", impact: "$420K at risk" },
            { r: "Client concentration — Top 3 clients = 48% rev", s: "High", impact: "Strategic" },
            { r: "FX exposure — EUR/USD shift", s: "Medium", impact: "$80K margin sensitivity" },
          ].map((x) => (
            <li key={x.r} className="flex items-center justify-between rounded border border-border bg-elevated px-3 py-2"><span><div className="font-medium">{x.r}</div><div className="text-[10px] text-muted-foreground">{x.impact}</div></span><span className={`rounded-full border px-2 py-0.5 text-[10px] font-medium ${x.s === "Critical" ? "border-[color:var(--danger)]/30 bg-[color:var(--danger)]/15 text-[color:var(--danger)]" : x.s === "High" ? "border-[color:var(--warning)]/30 bg-[color:var(--warning)]/15 text-[color:var(--warning)]" : "border-border bg-card text-muted-foreground"}`}>{x.s}</span></li>
          ))}
        </ul>
      </Card>

      <Card>
        <SectionHeader title="Portfolio Health Overview" />
        <div className="grid grid-cols-2 gap-3 md:grid-cols-4 text-xs">
          {sites.map((s) => (
            <div key={s.site} className="rounded border border-border bg-elevated p-3"><div className="text-[10px] uppercase text-muted-foreground">{s.site}</div><div className="mt-2 text-base font-semibold">{s.projects} projects</div><div className="text-[11px] text-muted-foreground">{s.util}% util · ${s.revenue}K rev</div></div>
          ))}
        </div>
      </Card>
    </div>
  );
}
