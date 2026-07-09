import type {
  CertificationStatus,
  DeliverySite,
  ProficiencyLevel,
  TrainingRecordStatus,
} from "@/types/workforce";

export const SITE_LABELS: Record<DeliverySite, string> = {
  india: "India",
  kosovo: "Kosovo",
};

export const PROFICIENCY_LEVELS: ProficiencyLevel[] = [
  "beginner",
  "intermediate",
  "advanced",
  "expert",
];

export const CERT_STATUSES: CertificationStatus[] = [
  "active",
  "expired",
  "pending_review",
  "revoked",
];

export const TRAINING_STATUSES: TrainingRecordStatus[] = [
  "not_started",
  "in_progress",
  "completed",
  "failed",
  "expired",
];

export const CERT_STATUS_PILL: Record<CertificationStatus, string> = {
  active: "Active",
  expired: "Expired",
  pending_review: "Pending",
  revoked: "Cancelled",
};

export const TRAINING_STATUS_PILL: Record<TrainingRecordStatus, string> = {
  not_started: "Draft",
  in_progress: "In Progress",
  completed: "Completed",
  failed: "High",
  expired: "Warning",
};

export function titleize(value: string): string {
  return value
    .split("_")
    .map((word) => word.charAt(0).toUpperCase() + word.slice(1))
    .join(" ");
}

export function formatDate(value: string | null): string {
  if (!value) return "-";
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) return value;
  return parsed.toLocaleDateString(undefined, {
    month: "short",
    day: "numeric",
    year: "numeric",
  });
}

export const selectClass =
  "rounded border border-border bg-card px-2 py-1 text-[11px] outline-none";
export const addButtonClass =
  "rounded border border-[color:var(--brand)]/30 bg-[color:var(--brand)]/10 px-2.5 py-1 text-[11px] font-medium text-[color:var(--brand)] hover:bg-[color:var(--brand)]/20 disabled:opacity-50";
export const removeButtonClass =
  "rounded border border-border bg-elevated px-1.5 py-0.5 text-[10px] text-[color:var(--danger)] hover:bg-card disabled:opacity-50";
