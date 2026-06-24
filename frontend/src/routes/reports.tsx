import { createFileRoute } from "@tanstack/react-router";
import { useState } from "react";
import { Card, SectionHeader, StatusPill, AiBadge } from "@/components/bsg/widgets";

export const Route = createFileRoute("/reports")({ component: ReportsPage });

const reports = [
  { name: "Aurora Health — Weekly Status W24", state: "Approved", date: "Jun 17", client: "Aurora Health" },
  { name: "Helios Bank — Schema Progress", state: "Pending", date: "Jun 18", client: "Helios Bank" },
  { name: "Nimbus AI — Capacity Forecast", state: "Draft", date: "Jun 18", client: "Nimbus AI" },
  { name: "Orion Geo — Region 4 Delivery", state: "Approved", date: "Jun 16", client: "Orion Geo" },
  { name: "Pulse — Quality Note", state: "Pending", date: "Jun 18", client: "Pulse Diagnostics" },
  { name: "Vertex — Compliance Brief", state: "Draft", date: "Jun 18", client: "Vertex Capital" },
];

function ReportsPage() {
  const [modal, setModal] = useState(false);
  const [sel, setSel] = useState(reports[0]);
  return (
    <div className="grid grid-cols-1 gap-5 lg:grid-cols-3">
      <Card className="lg:col-span-1">
        <SectionHeader title="Reports" right={<button onClick={() => setModal(true)} className="rounded bg-[color:var(--brand)] px-2.5 py-1 text-[11px] font-medium text-[color:var(--brand-foreground)]">Generate Report</button>} />
        <div className="mb-3 flex gap-1 text-[11px]">
          {["All", "Draft", "Pending", "Approved"].map((s) => <button key={s} className="rounded border border-border bg-elevated px-2 py-0.5">{s}</button>)}
        </div>
        <ul className="space-y-1.5 text-xs">
          {reports.map((r) => (
            <li key={r.name}><button onClick={() => setSel(r)} className={`flex w-full items-center justify-between rounded border border-border px-2.5 py-2 text-left ${sel.name === r.name ? "bg-elevated" : ""}`}>
              <span className="min-w-0"><div className="truncate font-medium">{r.name}</div><div className="text-[10px] text-muted-foreground">{r.client} · {r.date}</div></span>
              <StatusPill status={r.state === "Approved" ? "On Track" : r.state === "Pending" ? "Warning" : "In Progress"} />
            </button></li>
          ))}
        </ul>
      </Card>

      <Card className="lg:col-span-2">
        <SectionHeader title={sel.name} sub={`${sel.client} · ${sel.date}`} right={<div className="flex gap-2"><AiBadge confidence={91} /><button className="rounded border border-[color:var(--info)]/30 bg-[color:var(--info)]/15 px-2.5 py-1 text-[11px] font-medium text-[color:var(--info)]">Edit</button><button className="rounded bg-[color:var(--brand)] px-2.5 py-1 text-[11px] font-medium text-[color:var(--brand-foreground)]">Approve & Send</button></div>} />
        <div className="prose-invert max-w-none space-y-3 rounded-md border border-border bg-elevated p-5 text-sm leading-6">
          <h3 className="text-base font-semibold">Executive Summary</h3>
          <p>This week {sel.client} maintained healthy operational momentum across all active engagements. Schedule confidence improved by 1.4 points over the prior week, and gold-set accuracy held at 94.2%.</p>
          <h3 className="text-base font-semibold">Delivery Highlights</h3>
          <ul className="ml-5 list-disc"><li>Batch 14 completed 2 days ahead of schedule</li><li>3 new SMEs onboarded to the radiology pod</li><li>Schema v2 review underway with client team</li></ul>
          <h3 className="text-base font-semibold">Risks & Mitigations</h3>
          <p>One drift signal flagged in the radiology subset; calibration session scheduled for Jun 22. No client-facing impact expected.</p>
          <h3 className="text-base font-semibold">Next Week</h3>
          <p>Focus on schema v2 sign-off and capacity ramp for the upcoming Q3 batch.</p>
        </div>
      </Card>

      {modal && (
        <div className="fixed inset-0 z-40 grid place-items-center bg-background/70 backdrop-blur-sm" onClick={() => setModal(false)}>
          <div className="w-full max-w-md rounded-lg border border-border bg-card p-5" onClick={(e) => e.stopPropagation()}>
            <h3 className="text-sm font-semibold">Generate Report</h3>
            <div className="mt-3 space-y-3 text-xs">
              <label className="block"><span className="text-muted-foreground">Client</span><select className="mt-1 w-full rounded border border-border bg-elevated px-2 py-1.5">{reports.map((r) => <option key={r.client}>{r.client}</option>)}</select></label>
              <label className="block"><span className="text-muted-foreground">Template</span><select className="mt-1 w-full rounded border border-border bg-elevated px-2 py-1.5"><option>Weekly Status</option><option>Quality Note</option><option>Capacity Forecast</option></select></label>
              <label className="block"><span className="text-muted-foreground">Time period</span><select className="mt-1 w-full rounded border border-border bg-elevated px-2 py-1.5"><option>Week 24</option><option>Week 23</option><option>Month — June</option></select></label>
            </div>
            <div className="mt-4 flex justify-end gap-2"><button onClick={() => setModal(false)} className="rounded border border-border px-3 py-1.5 text-xs">Cancel</button><button onClick={() => setModal(false)} className="rounded bg-[color:var(--brand)] px-3 py-1.5 text-xs font-medium text-[color:var(--brand-foreground)]">Generate</button></div>
          </div>
        </div>
      )}
    </div>
  );
}
