import { AiBadge, Card, SectionHeader, StatusPill } from "@/components/bsg/widgets";
import type { QualityDashboard as QualityDashboardData } from "@/lib/api";

type Props = {
  alerts: QualityDashboardData["drift_alerts"];
  resolvingId: string | null;
  onResolve: (alertId: string) => void;
};

export function DriftAlertsCard({ alerts, resolvingId, onResolve }: Props) {
  const openCount = alerts.filter((a) => a.status === "open" || a.status === "acknowledged").length;

  return (
    <Card id="drift-alerts">
      <SectionHeader
        title="Drift Alerts"
        sub={openCount > 0 ? `${openCount} open · linked AI actions` : "Linked AI actions"}
        right={<AiBadge confidence={89} />}
      />
      <ul className="space-y-2">
        {alerts.length === 0 && (
          <li className="text-xs text-muted-foreground">No active drift alerts.</li>
        )}
        {alerts.map((alert) => (
          <li key={alert.id} className="rounded-md border border-border bg-elevated p-3 text-xs">
            <div className="flex items-center justify-between gap-2">
              <div className="flex items-center gap-2">
                <StatusPill status={alert.risk_tier === "critical" ? "Critical" : "Warning"} />
                <span className="font-medium">{alert.title}</span>
              </div>
              {(alert.status === "open" || alert.status === "acknowledged") && (
                <button
                  type="button"
                  onClick={() => onResolve(alert.id)}
                  disabled={resolvingId === alert.id}
                  className="rounded border border-border px-2 py-0.5 text-[10px] hover:bg-card disabled:cursor-not-allowed disabled:opacity-50"
                >
                  {resolvingId === alert.id ? "Resolving…" : "Resolve"}
                </button>
              )}
            </div>
            <div className="mt-1 text-muted-foreground">{alert.detail}</div>
          </li>
        ))}
      </ul>
    </Card>
  );
}
