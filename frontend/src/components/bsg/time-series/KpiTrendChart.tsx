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
  CHART_PRIMARY_STROKE,
  CHART_SECONDARY_STROKE,
  CHART_TOOLTIP_STYLE,
} from "@/lib/charts/theme";
import type { KpiSeriesPoint } from "@/types/time-series";

export type KpiTrendChartSeries = {
  dataKey: string;
  name: string;
  color?: string;
  yAxisId?: "l" | "r";
};

export type KpiTrendChartPoint = Record<string, string | number | null | undefined>;

function toNumber(value: number | string | null | undefined): number | null {
  if (value == null || value === "") return null;
  const n = Number(value);
  return Number.isFinite(n) ? n : null;
}

export function seriesPointsToChartData(
  points: KpiSeriesPoint[],
  valueKey = "value",
): KpiTrendChartPoint[] {
  return points.map((p) => ({
    label: p.bucket_start.slice(0, 10),
    [valueKey]: toNumber(p.numeric_value),
  }));
}

export function KpiTrendChart({
  title,
  sub,
  data,
  series,
  loading,
  error,
  height = 260,
  leftDomain,
  rightDomain,
  emptyMessage,
}: {
  title: string;
  sub?: string;
  data: KpiTrendChartPoint[];
  series: KpiTrendChartSeries[];
  loading?: boolean;
  error?: unknown;
  height?: number;
  leftDomain?: [number, number] | ["auto", "auto"];
  rightDomain?: [number, number] | ["auto", "auto"];
  emptyMessage?: string;
}) {
  const hasRight = series.some((s) => s.yAxisId === "r");
  return (
    <Card>
      <SectionHeader title={title} sub={sub} />
      <TimeSeriesState
        loading={loading}
        error={error}
        empty={!loading && !error && data.length === 0}
        emptyMessage={emptyMessage ?? "Insufficient history for this KPI trend."}
      >
        <ResponsiveContainer width="100%" height={height}>
          <LineChart data={data} accessibilityLayer>
            <CartesianGrid stroke={CHART_GRID_STROKE} strokeDasharray="3 3" />
            <XAxis dataKey="label" {...CHART_AXIS_STYLE} />
            <YAxis yAxisId="l" {...CHART_AXIS_STYLE} domain={leftDomain} />
            {hasRight ? (
              <YAxis yAxisId="r" orientation="right" {...CHART_AXIS_STYLE} domain={rightDomain} />
            ) : null}
            <Tooltip contentStyle={CHART_TOOLTIP_STYLE} />
            <Legend wrapperStyle={CHART_LEGEND_STYLE} />
            {series.map((s, idx) => (
              <Line
                key={s.dataKey}
                yAxisId={s.yAxisId ?? "l"}
                type="monotone"
                dataKey={s.dataKey}
                name={s.name}
                stroke={
                  s.color ?? (idx === 0 ? CHART_PRIMARY_STROKE : CHART_SECONDARY_STROKE)
                }
                strokeWidth={2}
                connectNulls
                dot={false}
              />
            ))}
          </LineChart>
        </ResponsiveContainer>
      </TimeSeriesState>
    </Card>
  );
}
