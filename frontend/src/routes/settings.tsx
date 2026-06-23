import { createFileRoute } from "@tanstack/react-router";
import { useState } from "react";
import { Card, SectionHeader } from "@/components/bsg/widgets";
import { roleLabel } from "@/lib/roleLabels";
import { cn } from "@/lib/utils";
import { useAuthStore } from "@/stores/useAuthStore";

export const Route = createFileRoute("/settings")({ component: SettingsPage });

const tabs = ["Profile", "Notifications", "Layout", "Integrations"] as const;

const inputClass = "mt-1 w-full rounded border border-border bg-elevated px-2.5 py-1.5";

function SettingsPage() {
  const [tab, setTab] = useState<(typeof tabs)[number]>("Profile");
  const user = useAuthStore((s) => s.user);

  if (!user) {
    return (
      <div className="text-sm text-muted-foreground">Loading profile…</div>
    );
  }

  return (
    <div className="space-y-5">
      <div className="flex gap-1 rounded-md border border-border bg-card p-1 text-xs">
        {tabs.map((t) => <button key={t} onClick={() => setTab(t)} className={cn("rounded px-3 py-1.5", tab === t ? "bg-elevated font-medium" : "text-muted-foreground hover:bg-elevated")}>{t}</button>)}
      </div>

      {tab === "Profile" && (
        <Card>
          <SectionHeader title="User Profile" />
          <div className="grid grid-cols-1 gap-3 md:grid-cols-2 text-xs">
            <label>
              <span className="text-muted-foreground">Full name</span>
              <input readOnly value={user.full_name ?? ""} className={inputClass} />
            </label>
            <label>
              <span className="text-muted-foreground">Email</span>
              <input readOnly value={user.email} className={inputClass} />
            </label>
            <label>
              <span className="text-muted-foreground">Role</span>
              <input disabled value={roleLabel(user.role)} className={cn(inputClass, "text-muted-foreground")} />
            </label>
            {user.organisation && (
              <label>
                <span className="text-muted-foreground">Organisation</span>
                <input readOnly value={user.organisation.name} className={inputClass} />
              </label>
            )}
          </div>
        </Card>
      )}

      {tab === "Notifications" && (
        <Card>
          <SectionHeader title="Notification Thresholds" />
          <ul className="space-y-2 text-xs">
            {[
              ["Critical alerts (immediate)", true],
              ["Quality drift", true],
              ["Schedule confidence drops", true],
              ["Governance items due", false],
              ["AI draft approvals", true],
            ].map(([l, v]) => (
              <li key={l as string} className="flex items-center justify-between rounded border border-border bg-elevated px-3 py-2"><span>{l as string}</span><input type="checkbox" defaultChecked={v as boolean} className="accent-[color:var(--brand)]" /></li>
            ))}
          </ul>
        </Card>
      )}

      {tab === "Layout" && (
        <Card>
          <SectionHeader title="Layout Density" />
          <div className="grid grid-cols-2 gap-3">
            <label className="cursor-pointer rounded border border-border bg-elevated p-4 text-xs"><input type="radio" name="d" defaultChecked className="mr-2 accent-[color:var(--brand)]" />Comfortable — more padding, easier scanning</label>
            <label className="cursor-pointer rounded border border-border bg-elevated p-4 text-xs"><input type="radio" name="d" className="mr-2 accent-[color:var(--brand)]" />Compact — denser tables, more on screen</label>
          </div>
        </Card>
      )}

      {tab === "Integrations" && (
        <Card>
          <SectionHeader title="Data Integrations" />
          <ul className="space-y-2 text-xs">
            {[
              ["Snowflake — Warehouse", "Connected", true],
              ["Slack — Alerts channel", "Connected", true],
              ["Jira — Action tracking", "Connected", true],
              ["Power BI — Export", "Not connected", false],
              ["Email SMTP — Reports", "Connected", true],
            ].map(([n, s, c]) => (
              <li key={n as string} className="flex items-center justify-between rounded border border-border bg-elevated px-3 py-2"><span className="font-medium">{n as string}</span><span className="flex items-center gap-2 text-[11px]"><span className={(c as boolean) ? "text-[color:var(--success)]" : "text-muted-foreground"}>{s as string}</span><button className="rounded border border-border px-2 py-0.5 text-[10px]">{c ? "Manage" : "Connect"}</button></span></li>
            ))}
          </ul>
        </Card>
      )}
    </div>
  );
}
