import type { ReactNode } from "react";
import { cn } from "@/lib/utils";

export function Card({ className, children }: { className?: string; children: ReactNode }) {
  return (
    <div className={cn("rounded-lg border border-border bg-card p-5", className)}>{children}</div>
  );
}

export function SectionHeader({ title, sub, right }: { title: string; sub?: string; right?: ReactNode }) {
  return (
    <div className="mb-4 flex items-start justify-between gap-3">
      <div className="min-w-0">
        <h3 className="text-sm font-semibold tracking-tight text-foreground">{title}</h3>
        {sub && <p className="mt-0.5 text-xs text-muted-foreground">{sub}</p>}
      </div>
      {right}
    </div>
  );
}

export function KpiCard({
  label,
  value,
  delta,
  tone = "default",
}: {
  label: string;
  value: string | number;
  delta?: string;
  tone?: "default" | "success" | "warning" | "danger";
}) {
  const toneColor =
    tone === "success" ? "text-[color:var(--success)]" :
    tone === "warning" ? "text-[color:var(--warning)]" :
    tone === "danger" ? "text-[color:var(--danger)]" : "text-muted-foreground";
  return (
    <Card>
      <div className="text-xs font-medium uppercase tracking-wider text-muted-foreground">{label}</div>
      <div className="mt-2 text-2xl font-semibold text-foreground">{value}</div>
      {delta && <div className={cn("mt-1 text-xs font-medium", toneColor)}>{delta}</div>}
    </Card>
  );
}

export function AiBadge({ confidence, label = "AI" }: { confidence?: number; label?: string }) {
  return (
    <span className="inline-flex items-center gap-1 rounded-full border border-[color:var(--brand)]/30 bg-[color:var(--brand)]/10 px-2 py-0.5 text-[10px] font-medium text-[color:var(--brand)]">
      <span className="h-1.5 w-1.5 rounded-full bg-[color:var(--brand)]" />
      {label}{confidence !== undefined ? ` · ${confidence}%` : ""}
    </span>
  );
}

export function EvidenceBadge() {
  return (
    <span className="inline-flex items-center gap-1 rounded-full border border-border bg-secondary px-2 py-0.5 text-[10px] font-medium text-muted-foreground">
      Evidence-backed
    </span>
  );
}

export function StatusPill({ status }: { status: string }) {
  const map: Record<string, string> = {
    "On Track": "bg-[color:var(--success)]/15 text-[color:var(--success)] border-[color:var(--success)]/30",
    Green: "bg-[color:var(--success)]/15 text-[color:var(--success)] border-[color:var(--success)]/30",
    Resolved: "bg-[color:var(--success)]/15 text-[color:var(--success)] border-[color:var(--success)]/30",
    Low: "bg-[color:var(--success)]/15 text-[color:var(--success)] border-[color:var(--success)]/30",
    "At Risk": "bg-[color:var(--warning)]/15 text-[color:var(--warning)] border-[color:var(--warning)]/30",
    Amber: "bg-[color:var(--warning)]/15 text-[color:var(--warning)] border-[color:var(--warning)]/30",
    Medium: "bg-[color:var(--warning)]/15 text-[color:var(--warning)] border-[color:var(--warning)]/30",
    Warning: "bg-[color:var(--warning)]/15 text-[color:var(--warning)] border-[color:var(--warning)]/30",
    "In Progress": "bg-[color:var(--info)]/15 text-[color:var(--info)] border-[color:var(--info)]/30",
    Info: "bg-[color:var(--info)]/15 text-[color:var(--info)] border-[color:var(--info)]/30",
    Success: "bg-[color:var(--success)]/15 text-[color:var(--success)] border-[color:var(--success)]/30",
    Critical: "bg-[color:var(--danger)]/15 text-[color:var(--danger)] border-[color:var(--danger)]/30",
    High: "bg-[color:var(--danger)]/15 text-[color:var(--danger)] border-[color:var(--danger)]/30",
    Red: "bg-[color:var(--danger)]/15 text-[color:var(--danger)] border-[color:var(--danger)]/30",
    Blocking: "bg-[color:var(--danger)]/15 text-[color:var(--danger)] border-[color:var(--danger)]/30",
    Open: "bg-[color:var(--danger)]/15 text-[color:var(--danger)] border-[color:var(--danger)]/30",
  };
  return (
    <span className={cn("inline-flex items-center rounded-full border px-2 py-0.5 text-[10px] font-medium", map[status] ?? "bg-secondary text-muted-foreground border-border")}>
      {status}
    </span>
  );
}
