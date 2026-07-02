import { createFileRoute } from "@tanstack/react-router";
import { useState } from "react";
import { Card, SectionHeader } from "@/components/bsg/widgets";
import { cn } from "@/lib/utils";

export const Route = createFileRoute("/settings")({ component: SettingsPage });

const tabs = ["Profile", "Notifications", "Layout", "Integrations"] as const;

function SettingsPage() {
  const [tab, setTab] = useState<(typeof tabs)[number]>("Profile");
  return (
    <div className="space-y-5">
      <div className="flex gap-1 rounded-md border border-border bg-card p-1 text-xs">
        {tabs.map((t) => (
          <button
            key={t}
            onClick={() => setTab(t)}
            className={cn(
              "rounded px-3 py-1.5",
              tab === t ? "bg-elevated font-medium" : "text-muted-foreground hover:bg-elevated",
            )}
          >
            {t}
          </button>
        ))}
      </div>

      {tab === "Profile" && (
        <Card>
          <SectionHeader title="User Profile" />
          <div className="grid grid-cols-1 gap-3 md:grid-cols-2 text-xs">
            <label>
              <span className="text-muted-foreground">Full name</span>
              <input
                defaultValue="Maya Chen"
                className="mt-1 w-full rounded border border-border bg-elevated px-2.5 py-1.5"
              />
            </label>
            <label>
              <span className="text-muted-foreground">Email</span>
              <input
                defaultValue="maya@bsg.com"
                className="mt-1 w-full rounded border border-border bg-elevated px-2.5 py-1.5"
              />
            </label>
            <label>
              <span className="text-muted-foreground">Role</span>
              <input
                disabled
                defaultValue="Delivery PM"
                className="mt-1 w-full rounded border border-border bg-elevated px-2.5 py-1.5 text-muted-foreground"
              />
            </label>
            <label>
              <span className="text-muted-foreground">Time zone</span>
              <select className="mt-1 w-full rounded border border-border bg-elevated px-2.5 py-1.5">
                <option>GMT</option>
                <option>IST</option>
                <option>CET</option>
              </select>
            </label>
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
              <li
                key={l as string}
                className="flex items-center justify-between rounded border border-border bg-elevated px-3 py-2"
              >
                <span>{l as string}</span>
                <input
                  type="checkbox"
                  defaultChecked={v as boolean}
                  className="accent-[color:var(--brand)]"
                />
              </li>
            ))}
          </ul>
        </Card>
      )}

      {tab === "Layout" && (
        <Card>
          <SectionHeader title="Layout Density" />
          <div className="grid grid-cols-2 gap-3">
            <label className="cursor-pointer rounded border border-border bg-elevated p-4 text-xs">
              <input
                type="radio"
                name="d"
                defaultChecked
                className="mr-2 accent-[color:var(--brand)]"
              />
              Comfortable — more padding, easier scanning
            </label>
            <label className="cursor-pointer rounded border border-border bg-elevated p-4 text-xs">
              <input type="radio" name="d" className="mr-2 accent-[color:var(--brand)]" />
              Compact — denser tables, more on screen
            </label>
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
              <li
                key={n as string}
                className="flex items-center justify-between rounded border border-border bg-elevated px-3 py-2"
              >
                <span className="font-medium">{n as string}</span>
                <span className="flex items-center gap-2 text-[11px]">
                  <span
                    className={
                      (c as boolean) ? "text-[color:var(--success)]" : "text-muted-foreground"
                    }
                  >
                    {s as string}
                  </span>
                  <button className="rounded border border-border px-2 py-0.5 text-[10px]">
                    {c ? "Manage" : "Connect"}
                  </button>
                </span>
              </li>
            ))}
          </ul>
        </Card>
      )}
    </div>
  );
}
