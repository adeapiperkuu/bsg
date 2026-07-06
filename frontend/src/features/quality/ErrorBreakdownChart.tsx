import { Bar, BarChart, CartesianGrid, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { Card, SectionHeader } from "@/components/bsg/widgets";
import { CHART_AXIS_STYLE, CHART_TOOLTIP_STYLE } from "./format";
import { ERROR_CATEGORY_LABELS, type QualityDashboard as QualityDashboardData } from "@/lib/api";

export function ErrorBreakdownChart({
  breakdown,
}: {
  breakdown: QualityDashboardData["error_breakdown"];
}) {
  const data = breakdown.map((e) => ({
    cat: ERROR_CATEGORY_LABELS[e.error_category] ?? e.error_category,
    count: Number(e.share_pct),
  }));

  return (
    <Card>
      <SectionHeader title="Error Category Breakdown" sub="Current week share %" />
      {data.length > 0 ? (
        <ResponsiveContainer width="100%" height={240}>
          <BarChart data={data} layout="vertical" margin={{ left: 20 }}>
            <CartesianGrid stroke="#2a2d3a" strokeDasharray="3 3" horizontal={false} />
            <XAxis type="number" {...CHART_AXIS_STYLE} />
            <YAxis dataKey="cat" type="category" {...CHART_AXIS_STYLE} width={140} />
            <Tooltip contentStyle={CHART_TOOLTIP_STYLE} />
            <Bar dataKey="count" fill="#0D1240" radius={[0, 4, 4, 0]} />
          </BarChart>
        </ResponsiveContainer>
      ) : (
        <p className="text-xs text-muted-foreground">
          No error taxonomy data for the current week.
        </p>
      )}
    </Card>
  );
}
