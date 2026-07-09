import {
  CartesianGrid,
  Line,
  LineChart,
  ReferenceLine,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";

import type { UtilizationTrendPoint } from "@/hooks/useWorkforceDashboardFilters";

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

export function UtilizationTrendChart({
  data,
  yAxisMax,
  capacityThreshold,
}: {
  data: UtilizationTrendPoint[];
  yAxisMax: number;
  capacityThreshold: number;
}) {
  return (
    <ResponsiveContainer width="100%" height={180}>
      <LineChart data={data}>
        <CartesianGrid stroke="#2a2d3a" strokeDasharray="3 3" />
        <XAxis dataKey="date" {...axis} />
        <YAxis {...axis} domain={[0, yAxisMax]} />
        <Tooltip contentStyle={tip} />
        <ReferenceLine y={capacityThreshold} stroke="#ef4444" strokeDasharray="4 4" />
        <Line type="monotone" dataKey="value" stroke="#0D1240" strokeWidth={2} dot={{ r: 3 }} />
      </LineChart>
    </ResponsiveContainer>
  );
}
