import {
  CartesianGrid,
  Legend,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { Card, SectionHeader } from "@/components/bsg/widgets";
import { TimeSeriesState } from "@/components/bsg/time-series/TimeSeriesState";
import {
  CHART_AXIS_STYLE,
  CHART_GRID_STROKE,
  CHART_LEGEND_STYLE,
  CHART_TOOLTIP_STYLE,
} from "@/lib/charts/theme";
import type { KpiCompare } from "@/types/time-series";

const PALETTE = ["#0D1240", "#3b82f6", "#22c55e", "#f59e0b", "#a78bfa", "#ef4444"];

export function KpiComparisonChart({
  title = "KPI Comparison",
  compare,
  loading,
  error,
  height = 260,
}: {
  title?: string;
  compare: KpiCompare | null | undefined;
  loading?: boolean;
  error?: unknown;
  height?: number;
}) {
  const labels = new Set<string>();
  for (const series of compare?.series ?? []) {
    for (const point of series.points) {
      labels.add(point.bucket_start.slice(0, 10));
    }
  }
  const ordered = [...labels].sort();
  const data = ordered.map((label) => {
    const row: Record<string, string | number | null> = { label };
    for (const series of compare?.series ?? []) {
      const point = series.points.find((p) => p.bucket_start.slice(0, 10) === label);
      row[series.scope_key] =
        point?.numeric_value == null ? null : Number(point.numeric_value);
    }
    return row;
  });

  return (
    <Card>
      <SectionHeader
        title={title}
        sub={compare ? `${compare.mode} · ${compare.interval}` : undefined}
      />
      <TimeSeriesState
        loading={loading}
        error={error}
        empty={!loading && !error && data.length === 0}
        emptyMessage="Insufficient history for comparison."
      >
        <ResponsiveContainer width="100%" height={height}>
          <LineChart data={data} accessibilityLayer>
            <CartesianGrid stroke={CHART_GRID_STROKE} strokeDasharray="3 3" />
            <XAxis dataKey="label" {...CHART_AXIS_STYLE} />
            <YAxis {...CHART_AXIS_STYLE} />
            <Tooltip contentStyle={CHART_TOOLTIP_STYLE} />
            <Legend wrapperStyle={CHART_LEGEND_STYLE} />
            {(compare?.series ?? []).map((series, idx) => (
              <Line
                key={series.scope_key}
                type="monotone"
                dataKey={series.scope_key}
                name={series.label}
                stroke={PALETTE[idx % PALETTE.length]}
                strokeWidth={2}
                dot={false}
                connectNulls
              />
            ))}
          </LineChart>
        </ResponsiveContainer>
      </TimeSeriesState>
    </Card>
  );
}
