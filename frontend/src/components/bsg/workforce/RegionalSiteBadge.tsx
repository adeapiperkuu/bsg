import { coverageStatusClass } from "@/lib/workforceLabels";
import { cn } from "@/lib/utils";
import type { SkillCoverageStatus } from "@/types/workforce";

export function RegionalSiteBadge({
  summary,
  required,
}: {
  summary: { available_headcount: number; coverage_status: SkillCoverageStatus };
  required: number;
}) {
  return (
    <span
      className={cn(
        "inline-block rounded px-2.5 py-1 text-[11px] font-medium",
        coverageStatusClass(summary.coverage_status),
      )}
      title={`${summary.available_headcount} available / ${required} required`}
    >
      {summary.available_headcount}/{required}
    </span>
  );
}
