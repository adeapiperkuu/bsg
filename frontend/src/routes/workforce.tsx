import { createFileRoute } from "@tanstack/react-router";
import { BarChart, Bar, ResponsiveContainer, XAxis, YAxis, CartesianGrid, Tooltip, ReferenceLine } from "recharts";
import { useState } from "react";
import { Card, SectionHeader, KpiCard, AiBadge, StatusPill } from "@/components/bsg/widgets";
import { utilization, skillMatrix, smeAllocation } from "@/lib/bsg/data";
import { cn } from "@/lib/utils";

export const Route = createFileRoute("/workforce")({ component: WorkforcePage });
const axis = { tick: { fill: "#8b92a5", fontSize: 11 }, axisLine: { stroke: "#2a2d3a" }, tickLine: { stroke: "#2a2d3a" } };
const tip = { backgroundColor: "#20242f", border: "1px solid #2a2d3a", borderRadius: 8, fontSize: 12, color: "#f0f2f7" };

const coverageColor = (v: string) =>
  v === "High" ? "bg-[color:var(--success)]/20 text-[color:var(--success)]" :
  v === "Medium" ? "bg-[color:var(--warning)]/20 text-[color:var(--warning)]" :
  "bg-[color:var(--danger)]/20 text-[color:var(--danger)]";

function WorkforcePage() {
  const [view, setView] = useState<"geo" | "matrix">("matrix");

  return (
    <div className="grid grid-cols-1 gap-5 lg:grid-cols-5">
      <div className="space-y-5 lg:col-span-3">
        <div className="grid grid-cols-2 gap-4 lg:grid-cols-4">
          <KpiCard label="Active Annotators" value="284" delta="+12 this month" tone="success" />
          <KpiCard label="SME Coverage" value="78%" delta="2 gaps" tone="warning" />
          <KpiCard label="Teams At Capacity" value="3 / 12" tone="warning" />
          <KpiCard label="Training Gaps" value="4 open" tone="danger" />
        </div>

        <Card>
          <SectionHeader title="Skill Coverage Matrix" sub="Domains × regions" right={<AiBadge confidence={85} />} />
          <div className="overflow-x-auto">
            <table className="w-full text-xs">
              <thead><tr className="text-muted-foreground"><th className="py-2 pr-3 text-left font-medium">Domain</th><th className="py-2 pr-3 text-center font-medium">India</th><th className="py-2 pr-3 text-center font-medium">Kosovo</th></tr></thead>
              <tbody>
                {skillMatrix.map((s) => (
                  <tr key={s.domain} className="border-t border-border/50">
                    <td className="py-2.5 pr-3 font-medium">{s.domain}</td>
                    <td className="py-2.5 pr-3 text-center"><span className={cn("inline-block rounded px-2.5 py-1 text-[11px] font-medium", coverageColor(s.India))} title={`India · ${s.India}`}>{s.India}</span></td>
                    <td className="py-2.5 pr-3 text-center"><span className={cn("inline-block rounded px-2.5 py-1 text-[11px] font-medium", coverageColor(s.Kosovo))} title={`Kosovo · ${s.Kosovo}`}>{s.Kosovo}</span></td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </Card>

        <Card>
          <SectionHeader title="Workforce Utilization" sub="By team · 85% capacity threshold" />
          <ResponsiveContainer width="100%" height={240}>
            <BarChart data={utilization}>
              <CartesianGrid stroke="#2a2d3a" strokeDasharray="3 3" />
              <XAxis dataKey="team" {...axis} />
              <YAxis {...axis} domain={[0, 100]} />
              <Tooltip contentStyle={tip} />
              <ReferenceLine y={85} stroke="#ef4444" strokeDasharray="4 4" />
              <Bar dataKey="value" fill="#00c9a7" radius={[4, 4, 0, 0]} />
            </BarChart>
          </ResponsiveContainer>
        </Card>

        <Card>
          <SectionHeader title="SME Allocation" />
          <div className="overflow-x-auto">
            <table className="w-full text-xs">
              <thead className="text-left text-muted-foreground"><tr className="border-b border-border">
                <th className="py-2 pr-3 font-medium">Name</th><th className="py-2 pr-3 font-medium">Domain</th><th className="py-2 pr-3 font-medium">Project</th><th className="py-2 pr-3 font-medium">Utilization</th><th className="py-2 pr-3 font-medium">Available</th>
              </tr></thead>
              <tbody>
                {smeAllocation.map((s) => (
                  <tr key={s.name} className="border-b border-border/50">
                    <td className="py-2.5 pr-3 font-medium">{s.name}</td>
                    <td className="py-2.5 pr-3 text-muted-foreground">{s.domain}</td>
                    <td className="py-2.5 pr-3">{s.project}</td>
                    <td className="py-2.5 pr-3"><span className={cn("font-medium", s.util > 90 ? "text-[color:var(--danger)]" : "text-foreground")}>{s.util}%</span></td>
                    <td className="py-2.5 pr-3 text-muted-foreground">{s.available}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </Card>
      </div>

      <div className="space-y-4 lg:col-span-2">
        <Card>
          <SectionHeader
            title="By Region"
            sub="India · Kosovo"
            right={
              <div className="flex items-center gap-1 rounded-md border border-border bg-elevated p-0.5 text-[11px]">
                <button onClick={() => setView("geo")} className={cn("rounded px-2 py-0.5", view === "geo" && "bg-card")}>Geographical</button>
                <button onClick={() => setView("matrix")} className={cn("rounded px-2 py-0.5", view === "matrix" && "bg-card")}>Matrix</button>
              </div>
            }
          />
          <div className="grid grid-cols-2 gap-3">
            {[
              { region: "India", headcount: 178, projects: 18, util: 87, gap: "Geospatial" },
              { region: "Kosovo", headcount: 106, projects: 12, util: 81, gap: "Medical Imaging" },
            ].map((r) => (
              <div key={r.region} className="rounded-md border border-border bg-elevated p-3">
                <div className="flex items-center justify-between">
                  <div className="text-sm font-semibold">{r.region}</div>
                  <StatusPill status={r.util > 85 ? "Warning" : "On Track"} />
                </div>
                <dl className="mt-2 space-y-1 text-[11px]">
                  <div className="flex justify-between"><dt className="text-muted-foreground">Headcount</dt><dd className="font-medium">{r.headcount}</dd></div>
                  <div className="flex justify-between"><dt className="text-muted-foreground">Active projects</dt><dd className="font-medium">{r.projects}</dd></div>
                  <div className="flex justify-between"><dt className="text-muted-foreground">Utilization</dt><dd className="font-medium">{r.util}%</dd></div>
                  <div className="flex justify-between"><dt className="text-muted-foreground">Top gap</dt><dd className="font-medium">{r.gap}</dd></div>
                </dl>
              </div>
            ))}
          </div>
          {view === "matrix" && (
            <div className="mt-4 overflow-x-auto">
              <table className="w-full text-[11px]">
                <thead><tr className="text-muted-foreground"><th className="py-1.5 text-left font-medium">Skill</th><th className="text-center font-medium">India</th><th className="text-center font-medium">Kosovo</th></tr></thead>
                <tbody>
                  {skillMatrix.map((s) => (
                    <tr key={s.domain} className="border-t border-border/40">
                      <td className="py-1.5">{s.domain}</td>
                      <td className="py-1.5 text-center"><span className={cn("rounded px-1.5 py-0.5", coverageColor(s.India))}>{s.India}</span></td>
                      <td className="py-1.5 text-center"><span className={cn("rounded px-1.5 py-0.5", coverageColor(s.Kosovo))}>{s.Kosovo}</span></td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </Card>

        <Card>
          <SectionHeader title="Training Gaps" />
          <ul className="space-y-2 text-xs">
            {["Radiology · pediatric subset (8 annotators)", "Geospatial · India (12 annotators)", "Voice · regional accents (5 annotators)", "Finance · KYC compliance (6 annotators)"].map((g) => (
              <li key={g} className="flex items-center justify-between rounded border border-border bg-elevated px-3 py-2">
                <span>{g}</span>
                <button className="rounded border border-border px-2 py-0.5 text-[10px]">Schedule</button>
              </li>
            ))}
          </ul>
        </Card>
      </div>
    </div>
  );
}
