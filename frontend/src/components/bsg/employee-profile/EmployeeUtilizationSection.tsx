import { useMemo } from "react";

import { normalizeUtilizationPct, useProjectUtilizationQuery } from "@/lib/queries/workforce";

import { formatDate } from "./employeeProfileUtils";
import { SectionLabel } from "./EmployeeProfileShared";

type EmployeeUtilizationSectionProps = {
  annotatorId: string;
  projectId: string | null;
  queriesEnabled: boolean;
};

export function EmployeeUtilizationSection({
  annotatorId,
  projectId,
  queriesEnabled,
}: EmployeeUtilizationSectionProps) {
  const query = useProjectUtilizationQuery(projectId, queriesEnabled, {
    annotator_id: annotatorId,
    limit: 5,
  });
  const latest = useMemo(() => {
    const rows = query.data ?? [];
    if (rows.length === 0) return null;
    return [...rows].sort((left, right) =>
      right.snapshot_date.localeCompare(left.snapshot_date),
    )[0];
  }, [query.data]);

  return (
    <div>
      <SectionLabel title="Latest utilization" />
      {query.isLoading ? (
        <div className="h-6 w-32 animate-pulse rounded bg-elevated" />
      ) : latest ? (
        <p className="text-xs text-foreground">
          {Math.round(normalizeUtilizationPct(latest.utilization_pct))}% on{" "}
          {formatDate(latest.snapshot_date)}
        </p>
      ) : (
        <p className="text-xs text-muted-foreground">No utilization snapshots for this employee.</p>
      )}
    </div>
  );
}
