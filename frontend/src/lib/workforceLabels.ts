import type {
  CapabilityGapSeverity,
  CapabilityGapStatus,
  CapabilityGapType,
  DeliverySite,
  SkillCoverageStatus,
  SkillMatrixRow,
  TrainingGapType,
} from "@/types/workforce";

export const WORKFORCE_EMPTY_VALUE = "-";

export const SITE_LABELS: Record<DeliverySite, string> = {
  india: "India",
  kosovo: "Kosovo",
};

const TRAINING_GAP_TYPE_LABELS: Record<TrainingGapType, string> = {
  mandatory_training_incomplete: "Mandatory incomplete",
  expired_or_failed_training: "Expired/failed training",
  expired_certification: "Expired certification",
  pending_certification_review: "Pending certification review",
};

export const trainingGapTypeLabel = (gapType: TrainingGapType) => TRAINING_GAP_TYPE_LABELS[gapType];

const CAPABILITY_GAP_TYPE_LABELS: Record<CapabilityGapType, string> = {
  skill_shortage: "Skill shortage",
  sme_shortage: "SME shortage",
  certification_gap: "Certification gap",
  training_gap: "Training gap",
  utilization_overload: "Utilization overload",
  utilization_underload: "Utilization underload",
};

export const capabilityGapTypeLabel = (gapType: CapabilityGapType) =>
  CAPABILITY_GAP_TYPE_LABELS[gapType];

export const capabilityGapSeverityClass = (severity: CapabilityGapSeverity) => {
  if (severity === "critical" || severity === "high") {
    return "bg-[color:var(--danger)]/15 text-[color:var(--danger)] border-[color:var(--danger)]/30";
  }
  if (severity === "medium") {
    return "bg-[color:var(--warning)]/15 text-[color:var(--warning)] border-[color:var(--warning)]/30";
  }
  return "bg-[color:var(--success)]/15 text-[color:var(--success)] border-[color:var(--success)]/30";
};

export const capabilityGapSeverityLabel = (severity: CapabilityGapSeverity) =>
  severity.charAt(0).toUpperCase() + severity.slice(1);

export const capabilityGapStatusClass = (status: CapabilityGapStatus) => {
  if (status === "open") {
    return "bg-[color:var(--warning)]/15 text-[color:var(--warning)] border-[color:var(--warning)]/30";
  }
  if (status === "acknowledged") {
    return "bg-secondary text-muted-foreground border-border";
  }
  if (status === "resolved") {
    return "bg-[color:var(--success)]/15 text-[color:var(--success)] border-[color:var(--success)]/30";
  }
  return "bg-muted text-muted-foreground border-border";
};

export const capabilityGapStatusLabel = (status: CapabilityGapStatus) =>
  status.charAt(0).toUpperCase() + status.slice(1);

export function formatDetectedAt(iso: string): string {
  try {
    return new Date(iso).toLocaleDateString(undefined, {
      month: "short",
      day: "numeric",
      year: "numeric",
    });
  } catch {
    return iso;
  }
}

export const coverageStatusClass = (status: SkillCoverageStatus) =>
  status === "high"
    ? "bg-[color:var(--success)]/20 text-[color:var(--success)]"
    : status === "medium"
      ? "bg-[color:var(--warning)]/20 text-[color:var(--warning)]"
      : "bg-[color:var(--danger)]/20 text-[color:var(--danger)]";

export const coverageStatusLabel = (status: SkillCoverageStatus) =>
  status.charAt(0).toUpperCase() + status.slice(1);

export const formatProficiency = (level: string) => level.charAt(0).toUpperCase() + level.slice(1);

export const siteSummaryFor = (row: SkillMatrixRow, site: DeliverySite) =>
  row.by_site.find((entry) => entry.site === site);
