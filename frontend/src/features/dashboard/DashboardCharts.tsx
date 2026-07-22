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

import { KpiTrendChart } from "@/components/bsg/time-series";
import { Card, SectionHeader, StatusPill } from "@/components/bsg/widgets";
import {
  CHART_AXIS_STYLE,
  CHART_GRID_STROKE,
  CHART_LEGEND_STYLE,
  CHART_TOOLTIP_STYLE,
} from "@/lib/charts/theme";
import { useKpiSeriesQuery } from "@/lib/queries/time-series";
import type { TowerActivity, TowerHealth, TowerPulse } from "@/lib/api";

export interface DashboardChartsProps {
  riskTrend: TowerPulse["riskTrend"];
  qualityTrend: TowerPulse["qualityTrend"];
  utilization: TowerActivity["utilization"];
  healthDistribution: TowerHealth["healthDistribution"];
  totalProjects: number;
  atRiskCount: number;
  iaaTrendingDown: boolean;
}

function TowerQualityTrendAdapter({
  qualityTrend,
  iaaTrendingDown,
}: {
  qualityTrend: TowerPulse["qualityTrend"];
  iaaTrendingDown: boolean;
}) {
  const goldSeries = useKpiSeriesQuery("quality.gold_set_accuracy", { interval: "week" });
  const iaaSeries = useKpiSeriesQuery("quality.iaa", { interval: "week" });
  const persistedEnough =
    (goldSeries.data?.points.length ?? 0) >= 2 || (iaaSeries.data?.points.length ?? 0) >= 2;

  const fallback = qualityTrend.map((row) => ({
    label: row.week,
    goldAccuracy: row.goldAccuracy != null ? Number(row.goldAccuracy) : null,
    iaa: row.iaa != null ? Number(row.iaa) : null,
  }));

  let data = fallback;
  if (persistedEnough) {
    const byLabel = new Map<
      string,
      { label: string; goldAccuracy: number | null; iaa: number | null }
    >();
    for (const point of goldSeries.data?.points ?? []) {
      const label = point.bucket_start.slice(0, 10);
      byLabel.set(label, {
        label,
        goldAccuracy: point.numeric_value == null ? null : Number(point.numeric_value),
        iaa: null,
      });
    }
    for (const point of iaaSeries.data?.points ?? []) {
      const label = point.bucket_start.slice(0, 10);
      const existing = byLabel.get(label) ?? { label, goldAccuracy: null, iaa: null };
      existing.iaa = point.numeric_value == null ? null : Number(point.numeric_value);
      byLabel.set(label, existing);
    }
    data = [...byLabel.values()].sort((a, b) => a.label.localeCompare(b.label));
  }

  return (
    <div>
      <KpiTrendChart
        title="Quality Trend"
        sub={
          persistedEnough
            ? "Gold-set & IAA · persisted time-series"
            : "Gold-set & IAA · 12 weeks (tower fallback)"
        }
        data={data}
        series={[
          { dataKey: "goldAccuracy", name: "Gold Acc %", yAxisId: "l" },
          { dataKey: "iaa", name: "IAA", yAxisId: "r", color: "#3b82f6" },
        ]}
        height={200}
        leftDomain={[80, 100]}
        rightDomain={[0.75, 0.95]}
        loading={
          (goldSeries.isLoading || iaaSeries.isLoading) && !persistedEnough && fallback.length === 0
        }
        error={goldSeries.error ?? iaaSeries.error}
      />
      {iaaTrendingDown && (
        <div className="mt-2 text-xs">
          <span className="rounded bg-[color:var(--danger)]/15 px-1.5 py-0.5 text-[10px] font-medium text-[color:var(--danger)]">
            Drift Alert
          </span>{" "}
          Inter-annotator agreement trending down
        </div>
      )}
    </div>
  );
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
            <CartesianGrid stroke={CHART_GRID_STROKE} strokeDasharray="3 3" />
            <XAxis dataKey="week" {...CHART_AXIS_STYLE} />
            <YAxis {...CHART_AXIS_STYLE} />
            <Tooltip contentStyle={CHART_TOOLTIP_STYLE} />
            <Legend wrapperStyle={CHART_LEGEND_STYLE} />
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
              <Tooltip contentStyle={CHART_TOOLTIP_STYLE} />
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

      <TowerQualityTrendAdapter qualityTrend={qualityTrend} iaaTrendingDown={iaaTrendingDown} />

      <Card className="lg:col-span-2">
        <SectionHeader title="Resource Utilization" sub="By team · threshold 85%" />
        <ResponsiveContainer width="100%" height={220}>
          <BarChart data={utilization} layout="vertical" margin={{ left: 20 }}>
            <CartesianGrid stroke={CHART_GRID_STROKE} strokeDasharray="3 3" horizontal={false} />
            <XAxis type="number" {...CHART_AXIS_STYLE} domain={[0, 100]} />
            <YAxis dataKey="team" type="category" {...CHART_AXIS_STYLE} width={110} />
            <Tooltip contentStyle={CHART_TOOLTIP_STYLE} />
            <ReferenceLine x={85} stroke="#ef4444" strokeDasharray="4 4" />
            <Bar dataKey="value" fill="#0D1240" radius={[0, 4, 4, 0]} />
          </BarChart>
        </ResponsiveContainer>
      </Card>
    </div>
  );
}
