import { createFileRoute } from "@tanstack/react-router";
import {
  LineChart,
  Line,
  BarChart,
  Bar,
  ResponsiveContainer,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  Legend,
} from "recharts";
import {
  Card,
  SectionHeader,
  KpiCard,
  AiBadge,
  EvidenceBadge,
  StatusPill,
} from "@/components/bsg/widgets";
import { qualityTrend, errorCategories, teamScorecard } from "@/lib/bsg/data";

export const Route = createFileRoute("/quality")({ component: QualityPage });
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

function QualityPage() {
  return (
    <div className="space-y-5">
      <div className="grid grid-cols-2 gap-4 lg:grid-cols-4">
        <KpiCard label="Gold-Set Accuracy" value="94.2%" delta="+0.3 WoW" tone="success" />
        <KpiCard label="IAA (Krippendorff α)" value="0.87" delta="−0.02" tone="warning" />
        <KpiCard label="Rework Rate" value="6.4%" delta="+0.8%" tone="warning" />
        <KpiCard label="Active Drift Alerts" value="2" delta="Radiology · NLP" tone="danger" />
      </div>

      <Card>
        <SectionHeader
          title="Quality Trend"
          sub="Gold accuracy & IAA · 12 weeks"
          right={
            <div className="flex gap-1.5">
              <button className="rounded border border-border px-2 py-0.5 text-[11px]">
                All teams
              </button>
              <button className="rounded border border-border bg-elevated px-2 py-0.5 text-[11px]">
                Radiology
              </button>
            </div>
          }
        />
        <ResponsiveContainer width="100%" height={260}>
          <LineChart data={qualityTrend}>
            <CartesianGrid stroke="#2a2d3a" strokeDasharray="3 3" />
            <XAxis dataKey="week" {...axis} />
            <YAxis yAxisId="l" {...axis} domain={[80, 100]} />
            <YAxis yAxisId="r" orientation="right" {...axis} domain={[0.75, 0.95]} />
            <Tooltip contentStyle={tip} />
            <Legend wrapperStyle={{ fontSize: 11, color: "#8b92a5" }} />
            <Line
              yAxisId="l"
              dataKey="goldAccuracy"
              stroke="#0D1240"
              strokeWidth={2}
              name="Gold Accuracy %"
            />
            <Line yAxisId="r" dataKey="iaa" stroke="#3b82f6" strokeWidth={2} name="IAA" />
          </LineChart>
        </ResponsiveContainer>
      </Card>

      <div className="grid grid-cols-1 gap-5 lg:grid-cols-2">
        <Card>
          <SectionHeader title="Error Category Breakdown" sub="Top error types · WoW deltas" />
          <ResponsiveContainer width="100%" height={240}>
            <BarChart data={errorCategories} layout="vertical" margin={{ left: 20 }}>
              <CartesianGrid stroke="#2a2d3a" strokeDasharray="3 3" horizontal={false} />
              <XAxis type="number" {...axis} />
              <YAxis dataKey="cat" type="category" {...axis} width={140} />
              <Tooltip contentStyle={tip} />
              <Bar dataKey="count" fill="#0D1240" radius={[0, 4, 4, 0]} />
            </BarChart>
          </ResponsiveContainer>
          <div className="mt-2 flex flex-wrap gap-2 text-[11px]">
            {errorCategories.map((e) => (
              <span key={e.cat} className="rounded border border-border bg-elevated px-2 py-0.5">
                {e.cat}{" "}
                <span
                  className={
                    e.delta.startsWith("+")
                      ? "text-[color:var(--danger)]"
                      : "text-[color:var(--success)]"
                  }
                >
                  {e.delta}
                </span>
              </span>
            ))}
          </div>
        </Card>

        <Card>
          <SectionHeader
            title="Drift Alerts"
            sub="Linked AI actions"
            right={<AiBadge confidence={89} />}
          />
          <ul className="space-y-2">
            <li className="rounded-md border border-border bg-elevated p-3 text-xs">
              <div className="flex items-center gap-2">
                <StatusPill status="Critical" />{" "}
                <span className="font-medium">Pulse Medical · Radiology subset</span>
              </div>
              <div className="mt-1 text-muted-foreground">
                IAA dropped to 0.81 (threshold 0.85). Recommended: schedule reviewer calibration
                session.
              </div>
              <button className="mt-2 rounded bg-[color:var(--brand)] px-2.5 py-1 text-[11px] font-medium text-[color:var(--brand-foreground)]">
                Schedule calibration
              </button>
            </li>
            <li className="rounded-md border border-border bg-elevated p-3 text-xs">
              <div className="flex items-center gap-2">
                <StatusPill status="Warning" />{" "}
                <span className="font-medium">Nimbus NLP · Guideline v3</span>
              </div>
              <div className="mt-1 text-muted-foreground">
                Class confusion up 8% — guideline ambiguity suspected. Recommended: workshop with
                SMEs.
              </div>
              <button className="mt-2 rounded bg-[color:var(--brand)] px-2.5 py-1 text-[11px] font-medium text-[color:var(--brand-foreground)]">
                Open workshop draft
              </button>
            </li>
          </ul>
        </Card>
      </div>

      <Card>
        <SectionHeader title="Team Quality Scorecard" />
        <div className="overflow-x-auto">
          <table className="w-full text-xs">
            <thead className="text-left text-muted-foreground">
              <tr className="border-b border-border">
                <th className="py-2 pr-3 font-medium">Team</th>
                <th className="py-2 pr-3 font-medium">Annotators</th>
                <th className="py-2 pr-3 font-medium">Gold Acc</th>
                <th className="py-2 pr-3 font-medium">IAA</th>
                <th className="py-2 pr-3 font-medium">Rework</th>
                <th className="py-2 pr-3 font-medium">Trend</th>
                <th className="py-2 pr-3 font-medium">Status</th>
              </tr>
            </thead>
            <tbody>
              {teamScorecard.map((t) => (
                <tr key={t.team} className="border-b border-border/50">
                  <td className="py-2.5 pr-3 font-medium">{t.team}</td>
                  <td className="py-2.5 pr-3">{t.annotators}</td>
                  <td className="py-2.5 pr-3">{t.gold}%</td>
                  <td className="py-2.5 pr-3">{t.iaa}</td>
                  <td className="py-2.5 pr-3">{t.rework}%</td>
                  <td className="py-2.5 pr-3">
                    <svg width="60" height="16" viewBox="0 0 60 16">
                      <polyline
                        points="0,12 10,9 20,11 30,7 40,8 50,5 60,6"
                        fill="none"
                        stroke="#0D1240"
                        strokeWidth="1.5"
                      />
                    </svg>
                  </td>
                  <td className="py-2.5 pr-3">
                    <StatusPill status={t.status} />
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Card>

      <Card>
        <SectionHeader
          title="AI Quality Narrative"
          sub="Auto-generated · Week 24"
          right={
            <div className="flex gap-2">
              <AiBadge confidence={90} />
              <EvidenceBadge />
            </div>
          }
        />
        <p className="text-sm leading-6 text-foreground/90">
          Overall quality posture remains strong with gold-set accuracy at 94.2% across the
          portfolio. The Radiology Pod B team has shown a sustained 3-week IAA decline, now sitting
          at 0.81 — below the 0.85 operating threshold. Root cause analysis indicates boundary
          precision errors on lesion contouring, correlated with the introduction of the new
          pediatric subset in W22. NLP Curation drift appears guideline-driven; a v3 calibration
          workshop is recommended within 5 business days.
        </p>
        <div className="mt-2 flex flex-wrap gap-1.5">
          <span className="rounded border border-border bg-elevated px-2 py-0.5 text-[10px]">
            📎 iaa-pod-b-w22.csv
          </span>
          <span className="rounded border border-border bg-elevated px-2 py-0.5 text-[10px]">
            📎 boundary-errors.json
          </span>
          <span className="rounded border border-border bg-elevated px-2 py-0.5 text-[10px]">
            📎 guideline-v3-diff.md
          </span>
        </div>
      </Card>
    </div>
  );
}
