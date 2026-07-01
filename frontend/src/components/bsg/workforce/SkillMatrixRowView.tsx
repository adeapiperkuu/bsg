import { RegionalSiteBadge } from "@/components/bsg/workforce/RegionalSiteBadge";
import {
  WORKFORCE_EMPTY_VALUE,
  coverageStatusClass,
  coverageStatusLabel,
  formatProficiency,
  siteSummaryFor,
} from "@/lib/workforceLabels";
import { cn } from "@/lib/utils";
import type { DeliverySite, SkillMatrixRow } from "@/types/workforce";

export function SkillMatrixRowView({
  row,
  visibleSites,
}: {
  row: SkillMatrixRow;
  visibleSites: DeliverySite[];
}) {
  const domainLabel = row.domain ?? row.category;

  return (
    <tr className="border-b border-border/50">
      <td className="py-2.5 pr-3">
        <div className="font-medium">{row.skill_name}</div>
        {domainLabel ? (
          <div className="text-[11px] text-muted-foreground">{domainLabel}</div>
        ) : null}
      </td>
      <td className="py-2.5 pr-3 text-muted-foreground">
        {formatProficiency(row.required_proficiency_level)}
      </td>
      <td className="py-2.5 pr-3">
        {row.available_headcount} / {row.required_headcount}
      </td>
      <td className="py-2.5 pr-3">
        {row.available_sme_count} / {row.required_sme_count}
      </td>
      <td className="py-2.5 pr-3">
        <span
          className={cn(
            "inline-block rounded px-2.5 py-1 text-[11px] font-medium",
            coverageStatusClass(row.coverage_status),
          )}
        >
          {coverageStatusLabel(row.coverage_status)}
        </span>
      </td>
      {visibleSites.map((site) => {
        const summary = siteSummaryFor(row, site);
        return (
          <td key={site} className="py-2.5 pr-3 text-center">
            {summary ? (
              <RegionalSiteBadge summary={summary} required={row.required_headcount} />
            ) : (
              WORKFORCE_EMPTY_VALUE
            )}
          </td>
        );
      })}
    </tr>
  );
}
