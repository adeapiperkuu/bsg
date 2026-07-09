import { createFileRoute } from "@tanstack/react-router";
import {
  LineChart,
  Line,
  ResponsiveContainer,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
} from "recharts";
import { Card, SectionHeader, KpiCard, StatusPill } from "@/components/bsg/widgets";

export const Route = createFileRoute("/client/status")({ component: Status });
const axis = {
  tick: { fill: "#8b92a5", fontSize: 11 },
  axisLine: { stroke: "#2a2d3a" },
  tickLine: { stroke: "#2a2d3a" },
};
const tip = {
  backgroundColor: "#20242f",
  border: "1px solid #2a2d3a",
  borderRadius: 8,
  fontSize: 12,
  color: "#f0f2f7",
};

const trend = Array.from({ length: 12 }, (_, i) => ({
  week: `W${i + 13}`,
  confidence: 86 + Math.round(Math.sin(i / 2) * 4),
}));

function Status() {
  return (
    <div className="space-y-5">
      <div className="grid grid-cols-2 gap-4 md:grid-cols-4">
        <KpiCard label="Delivery Confidence" value="92%" tone="success" />
        <KpiCard label="Milestones On Track" value="6 / 7" tone="success" />
        <KpiCard label="Quality Score" value="96.2%" tone="success" />
        <KpiCard label="Open Questions" value="2" tone="warning" />
      </div>

      <Card>
        <SectionHeader title="Confidence Trend" sub="12 weeks" />
        <ResponsiveContainer width="100%" height={220}>
          <LineChart data={trend}>
            <CartesianGrid stroke="#2a2d3a" strokeDasharray="3 3" />
            <XAxis dataKey="week" {...axis} />
            <YAxis {...axis} domain={[70, 100]} />
            <Tooltip contentStyle={tip} />
            <Line dataKey="confidence" stroke="#0D1240" strokeWidth={2} />
          </LineChart>
        </ResponsiveContainer>
      </Card>

      <Card>
        <SectionHeader title="Milestones" />
        <table className="w-full text-xs">
          <thead className="text-left text-muted-foreground">
            <tr className="border-b border-border">
              <th className="py-2 pr-3 font-medium">Milestone</th>
              <th className="py-2 pr-3 font-medium">Due</th>
              <th className="py-2 pr-3 font-medium">Confidence</th>
              <th className="py-2 pr-3 font-medium">Status</th>
            </tr>
          </thead>
          <tbody>
            {[
              ["Batch 14 QA", "Jun 24", 94, "On Track"],
              ["Schema v3 review", "Jul 02", 88, "On Track"],
              ["Mid-quarter delivery", "Jul 15", 91, "On Track"],
              ["Capacity ramp Q3", "Jul 22", 82, "At Risk"],
            ].map((r) => (
              <tr key={r[0] as string} className="border-b border-border/50">
                <td className="py-2.5 pr-3 font-medium">{r[0]}</td>
                <td className="py-2.5 pr-3">{r[1]}</td>
                <td className="py-2.5 pr-3">{r[2]}%</td>
                <td className="py-2.5 pr-3">
                  <StatusPill status={r[3] as string} />
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </Card>
    </div>
  );
}
