import type { DeliverySite, ProficiencyLevel, SkillRequirementPriority } from "@/types/workforce";

export const PROFICIENCY_LEVELS: ProficiencyLevel[] = [
  "beginner",
  "intermediate",
  "advanced",
  "expert",
];

export const PRIORITIES: SkillRequirementPriority[] = ["low", "medium", "high", "critical"];

export const SITE_LABELS: Record<DeliverySite, string> = {
  india: "India",
  kosovo: "Kosovo",
};

export const selectClass =
  "rounded border border-border bg-card px-2 py-1 text-[11px] outline-none";
export const inputClass =
  "w-full rounded border border-border bg-card px-2 py-1 text-[11px] outline-none";
export const numberClass =
  "w-16 rounded border border-border bg-card px-2 py-1 text-[11px] outline-none";
export const addButtonClass =
  "rounded border border-[color:var(--brand)]/30 bg-[color:var(--brand)]/10 px-2.5 py-1 text-[11px] font-medium text-[color:var(--brand)] hover:bg-[color:var(--brand)]/20 disabled:opacity-50";
export const removeButtonClass =
  "rounded border border-border bg-elevated px-1.5 py-0.5 text-[10px] text-[color:var(--danger)] hover:bg-card disabled:opacity-50";

export function titleize(value: string): string {
  return value.charAt(0).toUpperCase() + value.slice(1);
}

export function todayIso(): string {
  return new Date().toISOString().slice(0, 10);
}
