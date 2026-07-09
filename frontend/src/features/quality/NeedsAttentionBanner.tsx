import { AlertTriangle, CheckCircle2 } from "lucide-react";
import type {
  CalibrationBrief,
  QualityDashboard as QualityDashboardData,
  SopAmbiguityFlag,
} from "@/lib/api";

type Tone = "danger" | "warning" | "info";

type Props = {
  dashboard: QualityDashboardData;
  calibrationBrief: CalibrationBrief | undefined;
  sopFlags: SopAmbiguityFlag[];
};

function scrollToId(id: string) {
  document.getElementById(id)?.scrollIntoView({ behavior: "smooth", block: "start" });
}

const TONE_CLASSES: Record<Tone, string> = {
  danger: "border-[color:var(--danger)]/40 bg-[color:var(--danger)]/10 text-[color:var(--danger)]",
  warning:
    "border-[color:var(--warning)]/40 bg-[color:var(--warning)]/10 text-[color:var(--warning)]",
  info: "border-[color:var(--info)]/40 bg-[color:var(--info)]/10 text-[color:var(--info)]",
};

function Chip({ tone, label, onClick }: { tone: Tone; label: string; onClick: () => void }) {
  return (
    <button
      type="button"
      onClick={onClick}
      className={`rounded-full border px-3 py-1 text-left text-xs font-medium transition-opacity hover:opacity-80 ${TONE_CLASSES[tone]}`}
    >
      {label}
    </button>
  );
}

export function NeedsAttentionBanner({ dashboard, calibrationBrief, sopFlags }: Props) {
  const openAlerts = dashboard.drift_alerts.filter(
    (a) => a.status === "open" || a.status === "acknowledged",
  );
  const criticalAlerts = openAlerts.filter((a) => a.risk_tier === "critical");
  const otherAlerts = openAlerts.filter((a) => a.risk_tier !== "critical");
  const candidates = calibrationBrief?.candidates ?? [];
  const immediateCalibration = candidates.filter((c) => c.priority === "immediate");
  const dataGapCount = dashboard.data_gap_teams.length;

  const chips: Array<{ key: string; tone: Tone; label: string; target: string }> = [];

  if (criticalAlerts.length > 0) {
    chips.push({
      key: "critical-alerts",
      tone: "danger",
      label: `${criticalAlerts.length} critical drift alert${criticalAlerts.length === 1 ? "" : "s"}`,
      target: "drift-alerts",
    });
  }
  if (otherAlerts.length > 0) {
    chips.push({
      key: "other-alerts",
      tone: "warning",
      label: `${otherAlerts.length} drift alert${otherAlerts.length === 1 ? "" : "s"} to review`,
      target: "drift-alerts",
    });
  }
  if (candidates.length > 0) {
    chips.push({
      key: "calibration",
      tone: immediateCalibration.length > 0 ? "danger" : "warning",
      label: `${candidates.length} reviewer${candidates.length === 1 ? "" : "s"} flagged for calibration`,
      target: "calibration-brief",
    });
  }
  if (sopFlags.length > 0) {
    chips.push({
      key: "sop",
      tone: "warning",
      label: `${sopFlags.length} SOP ambiguity flag${sopFlags.length === 1 ? "" : "s"}`,
      target: "sop-ambiguity",
    });
  }
  if (dataGapCount > 0) {
    chips.push({
      key: "data-gap",
      tone: "info",
      label: `${dataGapCount} team${dataGapCount === 1 ? "" : "s"} below sample size`,
      target: "team-scorecard",
    });
  }

  if (chips.length === 0) {
    return (
      <div className="flex items-center gap-2 rounded-md border border-[color:var(--success)]/30 bg-[color:var(--success)]/10 px-3 py-2.5 text-xs text-[color:var(--success)]">
        <CheckCircle2 className="h-3.5 w-3.5 shrink-0" aria-hidden />
        No open quality issues — all metrics within target this week.
      </div>
    );
  }

  return (
    <div className="flex flex-wrap items-center gap-2 rounded-md border border-border bg-elevated px-3 py-2.5">
      <span className="flex items-center gap-1.5 text-xs font-medium text-muted-foreground">
        <AlertTriangle className="h-3.5 w-3.5" aria-hidden />
        Needs attention:
      </span>
      {chips.map((chip) => (
        <Chip
          key={chip.key}
          tone={chip.tone}
          label={chip.label}
          onClick={() => scrollToId(chip.target)}
        />
      ))}
    </div>
  );
}
