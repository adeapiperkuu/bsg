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
import { CHART_AXIS_STYLE, CHART_TOOLTIP_STYLE } from "./format";
import type { QualityDashboard as QualityDashboardData } from "@/lib/api";

export function QualityTrendChart({ trend }: { trend: QualityDashboardData["trend"] }) {
  const data = trend.map((t) => ({
    week: `W${t.iso_week}`,
    goldAccuracy: t.gold_set_accuracy_pct != null ? Number(t.gold_set_accuracy_pct) : null,
    iaa: t.iaa_krippendorff_alpha != null ? Number(t.iaa_krippendorff_alpha) : null,
  }));

  return (
    <Card>
      <SectionHeader title="Quality Trend" sub="Gold accuracy & IAA · up to 6 weeks" />
      <ResponsiveContainer width="100%" height={260}>
        <LineChart data={data}>
          <CartesianGrid stroke="#2a2d3a" strokeDasharray="3 3" />
          <XAxis dataKey="week" {...CHART_AXIS_STYLE} />
          <YAxis yAxisId="l" {...CHART_AXIS_STYLE} domain={[80, 100]} />
          <YAxis yAxisId="r" orientation="right" {...CHART_AXIS_STYLE} domain={[0.75, 0.95]} />
          <Tooltip contentStyle={CHART_TOOLTIP_STYLE} />
          <Legend wrapperStyle={{ fontSize: 11, color: "#8b92a5" }} />
          <Line
            yAxisId="l"
            dataKey="goldAccuracy"
            stroke="#0D1240"
            strokeWidth={2}
            name="Gold Accuracy %"
            connectNulls
          />
          <Line
            yAxisId="r"
            dataKey="iaa"
            stroke="#3b82f6"
            strokeWidth={2}
            name="IAA"
            connectNulls
          />
        </LineChart>
      </ResponsiveContainer>
    </Card>
  );
}
