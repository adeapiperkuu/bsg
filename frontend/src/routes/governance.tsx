import { createFileRoute } from "@tanstack/react-router";
import { Card, SectionHeader, KpiCard, AiBadge, StatusPill } from "@/components/bsg/widgets";
import { dependencies, escalations } from "@/lib/bsg/data";

export const Route = createFileRoute("/governance")({ component: GovernancePage });

function GovernancePage() {
  return (
    <div className="space-y-5">
      <div className="grid grid-cols-1 gap-5 lg:grid-cols-3">
        <div className="space-y-5 lg:col-span-2">
          <div className="grid grid-cols-2 gap-4 lg:grid-cols-4">
            <KpiCard label="Open Actions" value="23" delta="6 due this week" tone="warning" />
            <KpiCard label="At-Risk Items" value="7" tone="danger" />
            <KpiCard label="Open Escalations" value="3" tone="danger" />
            <KpiCard label="SLA Adherence" value="94%" delta="+1.2%" tone="success" />
          </div>

          <Card>
            <SectionHeader title="Dependency Tracker" sub="Cross-project dependencies" />
            <div className="overflow-x-auto">
              <table className="w-full text-xs">
                <thead className="text-left text-muted-foreground">
                  <tr className="border-b border-border">
                    <th className="py-2 pr-3 font-medium">Dependency</th>
                    <th className="py-2 pr-3 font-medium">Type</th>
                    <th className="py-2 pr-3 font-medium">Blocking</th>
                    <th className="py-2 pr-3 font-medium">Owner</th>
                    <th className="py-2 pr-3 font-medium">Overdue</th>
                    <th className="py-2 pr-3 font-medium">Status</th>
                    <th className="py-2 pr-3 font-medium"></th>
                  </tr>
                </thead>
                <tbody>
                  {dependencies.map((d) => (
                    <tr key={d.name} className="border-b border-border/50">
                      <td className="py-2.5 pr-3 font-medium">{d.name}</td>
                      <td className="py-2.5 pr-3 text-muted-foreground">{d.type}</td>
                      <td className="py-2.5 pr-3">{d.project}</td>
                      <td className="py-2.5 pr-3 text-muted-foreground">{d.owner}</td>
                      <td className="py-2.5 pr-3">
                        {d.overdue > 0 ? (
                          <span className="text-[color:var(--danger)]">{d.overdue}d</span>
                        ) : (
                          "—"
                        )}
                      </td>
                      <td className="py-2.5 pr-3">
                        <StatusPill status={d.status} />
                      </td>
                      <td className="py-2.5 pr-3">
                        <button className="rounded border border-border px-2 py-0.5 text-[10px]">
                          Mark Resolved
                        </button>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </Card>

          <Card>
            <SectionHeader
              title="Governance Register"
              sub="Project · scope · dependencies · escalations"
            />
            <div className="overflow-x-auto">
              <table className="w-full text-xs">
                <thead className="text-left text-muted-foreground">
                  <tr className="border-b border-border">
                    <th className="py-2 pr-3 font-medium">Project</th>
                    <th className="py-2 pr-3 font-medium">Scope</th>
                    <th className="py-2 pr-3 font-medium">Dependencies</th>
                    <th className="py-2 pr-3 font-medium">Actions</th>
                    <th className="py-2 pr-3 font-medium">Escalations</th>
                  </tr>
                </thead>
                <tbody>
                  {[
                    { p: "Aurora Vision", scope: "Approved", deps: "0 open", actions: 3, esc: 0 },
                    {
                      p: "Helios Docs",
                      scope: "Pending v2",
                      deps: "1 blocking",
                      actions: 5,
                      esc: 1,
                    },
                    { p: "Nimbus NLP", scope: "Locked", deps: "1 blocking", actions: 8, esc: 1 },
                    { p: "Orion Geo", scope: "Approved", deps: "0 open", actions: 2, esc: 0 },
                    { p: "Pulse Medical", scope: "Approved", deps: "0 open", actions: 6, esc: 1 },
                    { p: "Vertex Finance", scope: "Approved", deps: "0 open", actions: 4, esc: 0 },
                  ].map((r) => (
                    <tr key={r.p} className="border-b border-border/50">
                      <td className="py-2.5 pr-3 font-medium">{r.p}</td>
                      <td className="py-2.5 pr-3">
                        <StatusPill
                          status={
                            r.scope === "Approved"
                              ? "On Track"
                              : r.scope === "Pending v2"
                                ? "At Risk"
                                : "In Progress"
                          }
                        />
                      </td>
                      <td className="py-2.5 pr-3 text-muted-foreground">{r.deps}</td>
                      <td className="py-2.5 pr-3">{r.actions}</td>
                      <td className="py-2.5 pr-3">
                        {r.esc > 0 ? (
                          <span className="text-[color:var(--danger)]">{r.esc}</span>
                        ) : (
                          "0"
                        )}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </Card>
        </div>

        <Card>
          <SectionHeader title="Governance This Week" right={<AiBadge confidence={91} />} />
          <div className="rounded-md border border-[color:var(--brand)]/30 bg-[color:var(--brand)]/5 p-3 text-xs">
            <div className="text-[10px] uppercase tracking-wider text-muted-foreground">
              Next governance call
            </div>
            <div className="mt-1 text-lg font-semibold">Fri, Jun 21 · 14:00 GMT</div>
            <div className="text-[11px] text-muted-foreground">in 2 days, 4 hours</div>
          </div>
          <div className="mt-4">
            <div className="mb-2 text-[10px] font-semibold uppercase tracking-wider text-muted-foreground">
              Due this week
            </div>
            <ul className="space-y-1.5 text-xs">
              {[
                { t: "Approve Helios schema v2", o: "Maya Chen" },
                { t: "Sign-off Pulse calibration plan", o: "Priya R." },
                { t: "Close 4 W23 action items", o: "Arben K." },
                { t: "Review Nimbus capacity proposal", o: "Sara L." },
              ].map((i) => (
                <li
                  key={i.t}
                  className="flex items-center justify-between rounded border border-border bg-elevated px-2.5 py-1.5"
                >
                  <span className="flex items-center gap-2">
                    <input type="checkbox" className="accent-[color:var(--brand)]" />
                    <span>{i.t}</span>
                  </span>
                  <span className="text-[10px] text-muted-foreground">{i.o}</span>
                </li>
              ))}
            </ul>
          </div>
          <div className="mt-4 rounded-md border border-border bg-elevated p-3 text-xs">
            <div className="mb-1 text-[10px] font-semibold uppercase tracking-wider text-muted-foreground">
              Auto-generated summary
            </div>
            <p className="leading-5 text-foreground/90">
              4 governance items pending; Helios schema is the critical-path blocker. Nimbus
              capacity proposal ready for review. Two escalations require client input on Friday's
              call.
            </p>
            <button className="mt-2 rounded bg-[color:var(--brand)] px-2.5 py-1 text-[11px] font-medium text-[color:var(--brand-foreground)]">
              Approve Summary
            </button>
          </div>
        </Card>
      </div>

      <Card>
        <SectionHeader title="Escalation Register" />
        <div className="overflow-x-auto">
          <table className="w-full text-xs">
            <thead className="text-left text-muted-foreground">
              <tr className="border-b border-border">
                <th className="py-2 pr-3 font-medium">Title</th>
                <th className="py-2 pr-3 font-medium">Project</th>
                <th className="py-2 pr-3 font-medium">Severity</th>
                <th className="py-2 pr-3 font-medium">Raised By</th>
                <th className="py-2 pr-3 font-medium">Date</th>
                <th className="py-2 pr-3 font-medium">Status</th>
                <th className="py-2 pr-3 font-medium">Assigned</th>
                <th className="py-2 pr-3 font-medium">Notes</th>
              </tr>
            </thead>
            <tbody>
              {escalations.map((e) => (
                <tr key={e.title} className="border-b border-border/50">
                  <td className="py-2.5 pr-3 font-medium">{e.title}</td>
                  <td className="py-2.5 pr-3">{e.project}</td>
                  <td className="py-2.5 pr-3">
                    <StatusPill status={e.severity} />
                  </td>
                  <td className="py-2.5 pr-3 text-muted-foreground">{e.raisedBy}</td>
                  <td className="py-2.5 pr-3 text-muted-foreground">{e.date}</td>
                  <td className="py-2.5 pr-3">
                    <StatusPill status={e.status} />
                  </td>
                  <td className="py-2.5 pr-3">{e.assigned}</td>
                  <td className="py-2.5 pr-3 max-w-[260px] text-muted-foreground">{e.notes}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Card>
    </div>
  );
}
