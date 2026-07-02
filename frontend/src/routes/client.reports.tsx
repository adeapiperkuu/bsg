import { createFileRoute } from "@tanstack/react-router";
import { Card, SectionHeader, StatusPill } from "@/components/bsg/widgets";

export const Route = createFileRoute("/client/reports")({ component: ClientReports });

function ClientReports() {
  return (
    <Card>
      <SectionHeader title="Reports" sub="Read-only access to approved client reports" />
      <ul className="space-y-2 text-xs">
        {[
          { n: "Weekly Status — W24", d: "Jun 17", s: "Approved" },
          { n: "Weekly Status — W23", d: "Jun 10", s: "Approved" },
          { n: "Monthly Review — May 2026", d: "Jun 02", s: "Approved" },
          { n: "Weekly Status — W22", d: "Jun 03", s: "Approved" },
        ].map((r) => (
          <li
            key={r.n}
            className="flex items-center justify-between rounded border border-border bg-elevated px-3 py-2"
          >
            <span>
              <div className="font-medium">{r.n}</div>
              <div className="text-[10px] text-muted-foreground">{r.d}</div>
            </span>
            <span className="flex items-center gap-2">
              <StatusPill status="On Track" />
              <button className="rounded border border-border px-2 py-0.5 text-[10px]">
                Download
              </button>
              <button className="rounded bg-[color:var(--brand)] px-2 py-0.5 text-[10px] font-medium text-[color:var(--brand-foreground)]">
                View
              </button>
            </span>
          </li>
        ))}
      </ul>
    </Card>
  );
}
