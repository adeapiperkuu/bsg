import { createFileRoute } from "@tanstack/react-router";
import { Card, SectionHeader, AiBadge } from "@/components/bsg/widgets";

export const Route = createFileRoute("/client/")({ component: ClientHome });

function ClientHome() {
  return (
    <div className="space-y-5">
      <Card>
        <SectionHeader title="Welcome, Aurora Health" sub="Your delivery snapshot · Week 24" />
        <div className="grid grid-cols-1 gap-4 md:grid-cols-3">
          <div className="rounded-md border border-[color:var(--brand)]/30 bg-[color:var(--brand)]/5 p-6 md:col-span-1">
            <div className="text-xs uppercase tracking-wider text-muted-foreground">Delivery Confidence</div>
            <div className="mt-2 text-5xl font-semibold text-[color:var(--brand)]">92%</div>
            <div className="mt-1 text-xs text-muted-foreground">+2 pts vs last week</div>
          </div>
          <div className="md:col-span-2">
            <div className="mb-3 text-[10px] font-semibold uppercase tracking-wider text-muted-foreground">Upcoming Milestones</div>
            <ol className="relative border-l border-border pl-4 text-xs">
              {[
                { m: "Batch 14 QA sign-off", d: "Jun 24", s: "On Track" },
                { m: "Schema v3 review", d: "Jul 02", s: "On Track" },
                { m: "Mid-quarter delivery", d: "Jul 15", s: "On Track" },
              ].map((m) => (
                <li key={m.m} className="mb-4"><span className="absolute -left-1.5 h-3 w-3 rounded-full bg-[color:var(--brand)]" /><div className="font-medium">{m.m}</div><div className="text-[10px] text-muted-foreground">Due {m.d} · {m.s}</div></li>
              ))}
            </ol>
          </div>
        </div>
      </Card>

      <div className="grid grid-cols-1 gap-5 lg:grid-cols-2">
        <Card>
          <SectionHeader title="Latest Updates" sub="Pre-approved status summaries" right={<AiBadge confidence={94} />} />
          <ul className="space-y-2 text-xs">
            {[
              { t: "Batch 13 delivered ahead of schedule", d: "Jun 17" },
              { t: "3 new SMEs onboarded to your project", d: "Jun 15" },
              { t: "Quality benchmark held at 96.2%", d: "Jun 14" },
            ].map((u) => (<li key={u.t} className="rounded border border-border bg-elevated px-3 py-2"><div className="font-medium">{u.t}</div><div className="text-[10px] text-muted-foreground">{u.d}</div></li>))}
          </ul>
        </Card>

        <Card>
          <SectionHeader title="Have a question?" sub="We'll get back within 1 business day" />
          <form className="space-y-2">
            <textarea rows={4} placeholder="Ask about your project, delivery timeline, or quality…" className="w-full rounded border border-border bg-elevated px-3 py-2 text-xs outline-none focus:border-[color:var(--brand)]" />
            <div className="flex justify-end"><button className="rounded bg-[color:var(--brand)] px-3 py-1.5 text-xs font-medium text-[color:var(--brand-foreground)]">Submit Question</button></div>
          </form>
        </Card>
      </div>
    </div>
  );
}
