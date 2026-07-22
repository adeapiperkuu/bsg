import {
  Area,
  CartesianGrid,
  ComposedChart,
  Legend,
  Line,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { Card, SectionHeader } from "@/components/bsg/widgets";
import { TimeSeriesState } from "@/components/bsg/time-series/TimeSeriesState";
import {
  CHART_AXIS_STYLE,
  CHART_FORECAST_STROKE,
  CHART_GRID_STROKE,
  CHART_LEGEND_STYLE,
  CHART_PRIMARY_STROKE,
  CHART_TOOLTIP_STYLE,
} from "@/lib/charts/theme";
import type { KpiForecast, KpiSeriesPoint } from "@/types/time-series";

export function KpiForecastChart({
  title = "KPI Forecast",
  history = [],
  forecast,
  loading,
  error,
  height = 260,
}: {
  title?: string;
  history?: KpiSeriesPoint[];
  forecast: KpiForecast | null | undefined;
  loading?: boolean;
  error?: unknown;
  height?: number;
}) {
  const historyRows = history.map((p) => ({
    label: p.bucket_start.slice(0, 10),
    actual: p.numeric_value == null ? null : Number(p.numeric_value),
    forecast: null as number | null,
    lower: null as number | null,
    upper: null as number | null,
  }));
  const forecastRows = (forecast?.points ?? []).map((p) => ({
    label: p.forecast_at.slice(0, 10),
    actual: null as number | null,
    forecast: Number(p.value),
    lower: p.lower_bound == null ? null : Number(p.lower_bound),
    upper: p.upper_bound == null ? null : Number(p.upper_bound),
  }));
  const data = [...historyRows, ...forecastRows];
  const insufficient = forecast?.status === "insufficient_data";

  return (
    <Card>
      <SectionHeader
        title={title}
        sub={
          forecast?.status === "ok"
            ? `${forecast.method ?? "forecast"} · horizon ${forecast.horizon ?? "—"}`
            : forecast?.message ?? undefined
        }
      />
      <TimeSeriesState
        loading={loading}
        error={error}
        empty={!loading && !error && (insufficient || data.length === 0)}
        emptyMessage={
          forecast?.message ?? "Insufficient numeric history for a deterministic forecast."
        }
      >
        <ResponsiveContainer width="100%" height={height}>
          <ComposedChart data={data} accessibilityLayer>
            <CartesianGrid stroke={CHART_GRID_STROKE} strokeDasharray="3 3" />
            <XAxis dataKey="label" {...CHART_AXIS_STYLE} />
            <YAxis {...CHART_AXIS_STYLE} />
            <Tooltip contentStyle={CHART_TOOLTIP_STYLE} />
            <Legend wrapperStyle={CHART_LEGEND_STYLE} />
            <Area
              type="monotone"
              dataKey="upper"
              stroke="transparent"
              fill={CHART_FORECAST_STROKE}
              fillOpacity={0.15}
              name="Upper bound"
              connectNulls
            />
            <Area
              type="monotone"
              dataKey="lower"
              stroke="transparent"
              fill="#111827"
              fillOpacity={0.4}
              name="Lower bound"
              connectNulls
            />
            <Line
              type="monotone"
              dataKey="actual"
              name="Actual"
              stroke={CHART_PRIMARY_STROKE}
              strokeWidth={2}
              dot={false}
              connectNulls
            />
            <Line
              type="monotone"
              dataKey="forecast"
              name="Forecast"
              stroke={CHART_FORECAST_STROKE}
              strokeWidth={2}
              strokeDasharray="4 4"
              dot={false}
              connectNulls
            />
          </ComposedChart>
        </ResponsiveContainer>
      </TimeSeriesState>
    </Card>
  );
}
