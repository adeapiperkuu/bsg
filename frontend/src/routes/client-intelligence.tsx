import { createFileRoute } from "@tanstack/react-router";
import { useState } from "react";
import { Card, SectionHeader, KpiCard, AiBadge, StatusPill } from "@/components/bsg/widgets";
import { clients } from "@/lib/bsg/data";
import { Star } from "lucide-react";

export const Route = createFileRoute("/client-intelligence")({ component: ClientIntelPage });

function Sparkline() {
  return <svg width="64" height="18" viewBox="0 0 64 18"><polyline points="0,12 10,9 20,11 30,7 40,8 50,5 60,6" fill="none" stroke="#0D1240" strokeWidth="1.5" /></svg>;
}

function ClientIntelPage() {
  const [sel, setSel] = useState<string | null>(null);
  const selected = clients.find((c) => c.name === sel);

  return (
    <div className="space-y-5">
      <div className="grid grid-cols-2 gap-4 lg:grid-cols-4">
        <Card>
          <div className="text-xs uppercase tracking-wider text-muted-foreground">Delivery Confidence</div>
          <div className="mt-2 flex items-center justify-between">
            <div className="text-2xl font-semibold">87%</div>
            <Sparkline />
          </div>
        </Card>
        <Card>
          <div className="text-xs uppercase tracking-wider text-muted-foreground">Reports Drafted vs Approved</div>
          <div className="mt-2 text-sm">12 drafted · 9 approved</div>
          <div className="mt-2 h-2 overflow-hidden rounded bg-elevated"><div className="h-full bg-[color:var(--brand)]" style={{ width: "75%" }} /></div>
        </Card>
        <KpiCard label="Avg Query Response" value="3.4 h" delta="−18% WoW" tone="success" />
        <Card>
          <div className="text-xs uppercase tracking-wider text-muted-foreground">Avg CSAT</div>
          <div className="mt-2 flex gap-0.5">
            {[1,2,3,4,5].map((s) => <Star key={s} className={s <= 4 ? "h-5 w-5 fill-[color:var(--warning)] text-[color:var(--warning)]" : "h-5 w-5 text-muted-foreground/40"} />)}
          </div>
          <div className="mt-1 text-[11px] text-muted-foreground">4.5 / 5 across 8 clients</div>
        </Card>
      </div>

      <div className="grid grid-cols-1 gap-5 lg:grid-cols-5">
        <Card className="lg:col-span-3">
          <SectionHeader title="Client Master" />
          <div className="overflow-x-auto">
            <table className="w-full text-xs">
              <thead className="text-left text-muted-foreground"><tr className="border-b border-border">
                <th className="py-2 pr-3 font-medium">Client</th>
                <th className="py-2 pr-3 font-medium">Projects</th>
                <th className="py-2 pr-3 font-medium">Health</th>
                <th className="py-2 pr-3 font-medium">Confidence</th>
                <th className="py-2 pr-3 font-medium">Last Report</th>
                <th className="py-2 pr-3 font-medium">Next</th>
                <th className="py-2 pr-3 font-medium">CSAT</th>
                <th className="py-2 pr-3 font-medium"></th>
              </tr></thead>
              <tbody>
                {clients.map((c) => (
                  <tr key={c.name} className={`cursor-pointer border-b border-border/50 hover:bg-elevated ${sel === c.name ? "bg-elevated" : ""}`} onClick={() => setSel(c.name)}>
                    <td className="py-2.5 pr-3 font-medium">{c.name}</td>
                    <td className="py-2.5 pr-3">{c.projects}</td>
                    <td className="py-2.5 pr-3"><StatusPill status={c.health} /></td>
                    <td className="py-2.5 pr-3">{c.confidence}%</td>
                    <td className="py-2.5 pr-3 text-muted-foreground">{c.lastReport}</td>
                    <td className="py-2.5 pr-3">{c.nextMilestone}</td>
                    <td className="py-2.5 pr-3">{c.csat}/5</td>
                    <td className="py-2.5 pr-3"><div className="flex gap-1"><button className="rounded border border-border px-2 py-0.5 text-[10px]">View</button><button className="rounded bg-[color:var(--brand)] px-2 py-0.5 text-[10px] font-medium text-[color:var(--brand-foreground)]">Draft</button></div></td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </Card>

        <Card className="lg:col-span-2">
          <SectionHeader title={selected ? `${selected.name} · Detail` : "Client Detail"} sub={selected ? "Narrative · drafts · Q&A" : "Select a client row"} right={selected ? <AiBadge confidence={89} /> : null} />
          {!selected && <div className="rounded-md border border-dashed border-border p-6 text-center text-xs text-muted-foreground">Pick any client from the table to view AI-curated narrative, draft reports queue, and Q&A log.</div>}
          {selected && (
            <div className="space-y-4">
              <div className="rounded-md border border-border bg-elevated p-3 text-xs leading-5">
                <div className="mb-1 text-[10px] font-semibold uppercase tracking-wider text-muted-foreground">Delivery narrative</div>
                {selected.name} is currently tracking at {selected.confidence}% schedule confidence across {selected.projects} active project{selected.projects > 1 ? "s" : ""}. {selected.health === "Critical" ? "Immediate intervention required — see escalations." : selected.health === "At Risk" ? "Mitigation in progress; expected recovery within 2 weeks." : "All milestones aligned to plan."}
              </div>
              <div>
                <div className="mb-2 text-[10px] font-semibold uppercase tracking-wider text-muted-foreground">AI-drafted reports queue</div>
                <ul className="space-y-1.5 text-xs">
                  {["Weekly Status W24", "Mid-month Quality Note", "Capacity Forecast Q3"].map((r) => (
                    <li key={r} className="flex items-center justify-between rounded border border-border bg-elevated px-2.5 py-1.5">
                      <span>{r}</span>
                      <div className="flex gap-1"><button className="rounded border border-border px-1.5 py-0.5 text-[10px]">Preview</button><button className="rounded border border-border px-1.5 py-0.5 text-[10px]">Edit</button><button className="rounded bg-[color:var(--brand)] px-1.5 py-0.5 text-[10px] text-[color:var(--brand-foreground)]">Approve</button><button className="rounded border border-border px-1.5 py-0.5 text-[10px]">Reject</button></div>
                    </li>
                  ))}
                </ul>
              </div>
              <div>
                <div className="mb-2 text-[10px] font-semibold uppercase tracking-wider text-muted-foreground">Client Q&A log</div>
                <ul className="space-y-2 text-xs">
                  <li className="rounded border border-border bg-elevated p-2"><div className="font-medium">Q: What's the projected delivery date for batch 14?</div><div className="mt-1 text-muted-foreground">A (AI draft): Estimated Jun 24, 94% confidence. <span className="ml-1 text-[10px] text-[color:var(--brand)]">Approve →</span></div></li>
                  <li className="rounded border border-border bg-elevated p-2"><div className="font-medium">Q: Can we expand to a 4th annotator pod?</div><div className="mt-1 text-muted-foreground">A (AI draft): Capacity available in Kosovo from Jul 8. Pending PM review.</div></li>
                </ul>
              </div>
            </div>
          )}
        </Card>
      </div>
    </div>
  );
}
