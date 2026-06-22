import { createFileRoute } from "@tanstack/react-router";
import { useState } from "react";
import { Card, SectionHeader, StatusPill } from "@/components/bsg/widgets";
import { cn } from "@/lib/utils";

export const Route = createFileRoute("/admin")({ component: AdminConsole });

const tabs = ["Users & Roles", "Client Tenants", "Metrics", "Pipeline Health", "Audit Log"] as const;

function AdminConsole() {
  const [tab, setTab] = useState<(typeof tabs)[number]>("Users & Roles");
  return (
    <div className="space-y-5">
      <div className="flex flex-wrap gap-1 rounded-md border border-border bg-card p-1 text-xs">
        {tabs.map((t) => (
          <button key={t} onClick={() => setTab(t)} className={cn("rounded px-3 py-1.5", tab === t ? "bg-elevated font-medium" : "text-muted-foreground hover:bg-elevated")}>{t}</button>
        ))}
      </div>

      {tab === "Users & Roles" && (
        <Card>
          <SectionHeader title="Users" sub="28 accounts · 4 roles" />
          <table className="w-full text-xs">
            <thead className="text-left text-muted-foreground"><tr className="border-b border-border"><th className="py-2 pr-3 font-medium">Name</th><th className="py-2 pr-3 font-medium">Email</th><th className="py-2 pr-3 font-medium">Role</th><th className="py-2 pr-3 font-medium">Last Active</th><th className="py-2 pr-3 font-medium">Status</th></tr></thead>
            <tbody>
              {[
                ["Maya Chen", "maya@bsg.com", "Delivery PM", "2m ago", "Active"],
                ["Arben K.", "arben@bsg.com", "QA Lead", "12m ago", "Active"],
                ["Priya R.", "priya@bsg.com", "Workforce Mgr", "1h ago", "Active"],
                ["Sara L.", "sara@bsg.com", "Governance", "3h ago", "Active"],
                ["External · Helios PM", "pm@helios.com", "Client", "2d ago", "Active"],
              ].map((r) => (
                <tr key={r[1]} className="border-b border-border/50">{r.map((c, i) => <td key={i} className={cn("py-2.5 pr-3", i === 0 && "font-medium")}>{c}</td>)}</tr>
              ))}
            </tbody>
          </table>
        </Card>
      )}

      {tab === "Client Tenants" && (
        <Card>
          <SectionHeader title="Client Tenants" sub="Tenant-isolated workspaces" />
          <div className="grid grid-cols-2 gap-3 md:grid-cols-3">
            {["Aurora Health", "Helios Bank", "Nimbus AI", "Orion Geo", "Pulse Diagnostics", "Vertex Capital"].map((c) => (
              <div key={c} className="rounded-md border border-border bg-elevated p-3 text-xs"><div className="font-medium">{c}</div><div className="mt-1 text-[10px] text-muted-foreground">Active · 2 projects · 4 users</div><button className="mt-2 rounded border border-border px-2 py-0.5 text-[10px]">Manage</button></div>
            ))}
          </div>
        </Card>
      )}

      {tab === "Metrics" && (
        <Card>
          <SectionHeader title="Metric Configuration" sub="Thresholds for AI agents" />
          <ul className="space-y-2 text-xs">
            {[
              { m: "IAA drift threshold (Krippendorff α)", v: "0.85" },
              { m: "Schedule confidence at-risk cutoff", v: "75%" },
              { m: "Utilization alert (per team)", v: "85%" },
              { m: "Rework rate warning", v: "8%" },
            ].map((r) => (
              <li key={r.m} className="flex items-center justify-between rounded border border-border bg-elevated px-3 py-2"><span>{r.m}</span><span className="flex items-center gap-2"><input defaultValue={r.v} className="w-20 rounded border border-border bg-card px-2 py-0.5 text-xs" /><label className="inline-flex items-center gap-1"><input type="checkbox" defaultChecked className="accent-[color:var(--brand)]" /><span className="text-[10px]">Enabled</span></label></span></li>
            ))}
          </ul>
        </Card>
      )}

      {tab === "Pipeline Health" && (
        <Card>
          <SectionHeader title="System Pipeline Health" />
          <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
            {[
              { p: "Ingestion", s: "On Track" },
              { p: "AI Inference", s: "On Track" },
              { p: "Quality Eval", s: "At Risk" },
              { p: "Report Generation", s: "On Track" },
              { p: "Webhook Delivery", s: "On Track" },
              { p: "Data Warehouse Sync", s: "On Track" },
              { p: "Audit Stream", s: "On Track" },
              { p: "Notification Bus", s: "On Track" },
            ].map((r) => (
              <div key={r.p} className="rounded border border-border bg-elevated p-3 text-xs"><div className="font-medium">{r.p}</div><div className="mt-1 flex items-center justify-between"><span className="text-[10px] text-muted-foreground">Last 24h</span><StatusPill status={r.s} /></div></div>
            ))}
          </div>
        </Card>
      )}

      {tab === "Audit Log" && (
        <Card>
          <SectionHeader title="Audit Log" sub="Last 50 events" />
          <ul className="space-y-1 text-xs">
            {Array.from({ length: 12 }).map((_, i) => (
              <li key={i} className="flex items-center justify-between rounded border border-border bg-elevated px-2.5 py-1.5"><span><span className="font-medium">maya@bsg.com</span> · approved AI draft · Aurora W{24 - i}</span><span className="text-[10px] text-muted-foreground">{i * 14}m ago</span></li>
            ))}
          </ul>
        </Card>
      )}
    </div>
  );
}
