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

import { Card, SectionHeader, StatusPill } from "@/components/bsg/widgets";
import type { TowerActivity, TowerHealth, TowerPulse } from "@/lib/api";

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

export interface DashboardChartsProps {
  riskTrend: TowerPulse["riskTrend"];
  qualityTrend: TowerPulse["qualityTrend"];
  utilization: TowerActivity["utilization"];
  healthDistribution: TowerHealth["healthDistribution"];
  totalProjects: number;
  atRiskCount: number;
  iaaTrendingDown: boolean;
}

export default function DashboardCharts({
  riskTrend,
  qualityTrend,
  utilization,
  healthDistribution,
  totalProjects,
  atRiskCount,
  iaaTrendingDown,
}: DashboardChartsProps) {
  return (
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
  );
}
