import { createFileRoute } from "@tanstack/react-router";
import { Card, SectionHeader, AiBadge, StatusPill } from "@/components/bsg/widgets";

export const Route = createFileRoute("/pm-console")({ component: PmConsole });

function PmConsole() {
  return (
    <div className="grid grid-cols-1 gap-5 lg:grid-cols-3">
      <Card className="lg:col-span-2">
        <SectionHeader title="My Projects" sub="6 active assignments" />
        <ul className="space-y-2 text-xs">
          {["Aurora Vision Labeling", "Pulse Medical Imaging", "Helios Doc Extraction", "Vertex Finance Docs", "Lumen Retail Catalog", "Falcon Voice Transcription"].map((p, i) => (
            <li key={p} className="flex items-center justify-between rounded border border-border bg-elevated px-3 py-2">
              <span className="font-medium">{p}</span>
              <div className="flex items-center gap-2"><StatusPill status={["On Track", "At Risk", "At Risk", "On Track", "On Track", "At Risk"][i]} /><button className="rounded border border-border px-2 py-0.5 text-[10px]">Open</button></div>
            </li>
          ))}
        </ul>
      </Card>

      <Card>
        <SectionHeader title="Pending Actions" sub="Queue · sorted by priority" />
        <ul className="space-y-2 text-xs">
          {[
            { t: "Approve calibration plan — Pulse", sev: "Critical" },
            { t: "Sign off Helios schema v2", sev: "High" },
            { t: "Review 4 W23 governance items", sev: "Medium" },
            { t: "Confirm SME re-allocation", sev: "Medium" },
          ].map((a) => (
            <li key={a.t} className="rounded border border-border bg-elevated p-2">
              <div className="flex items-center justify-between"><span>{a.t}</span><StatusPill status={a.sev} /></div>
            </li>
          ))}
        </ul>
      </Card>

      <Card className="lg:col-span-2">
        <SectionHeader title="AI Drafts to Review" right={<AiBadge confidence={88} />} />
        <ul className="space-y-2 text-xs">
          {["Weekly status — Aurora Health", "Mid-month quality note — Pulse", "Capacity proposal — Nimbus", "Q3 forecast — Vertex"].map((d) => (
            <li key={d} className="flex items-center justify-between rounded border border-border bg-elevated p-2.5">
              <span>{d}</span>
              <div className="flex gap-1"><button className="rounded border border-border px-2 py-0.5 text-[10px]">Preview</button><button className="rounded bg-[color:var(--brand)] px-2 py-0.5 text-[10px] font-medium text-[color:var(--brand-foreground)]">Approve</button></div>
            </li>
          ))}
        </ul>
      </Card>

      <Card>
        <SectionHeader title="Quick Ask" sub="Mini PM agent" right={<AiBadge />} />
        <div className="space-y-2">
          {["Summarize my day", "What's blocking Pulse?", "Draft client update for Aurora"].map((q) => (
            <button key={q} className="block w-full rounded border border-border bg-elevated px-2.5 py-1.5 text-left text-xs hover:bg-card">{q}</button>
          ))}
          <form className="mt-2 flex gap-2"><input placeholder="Ask anything…" className="flex-1 rounded border border-border bg-card px-2.5 py-1.5 text-xs outline-none" /><button className="rounded bg-[color:var(--brand)] px-3 py-1.5 text-xs font-medium text-[color:var(--brand-foreground)]">Ask</button></form>
        </div>
      </Card>
    </div>
  );
}
