import { Card, SectionHeader } from "@/components/bsg/widgets";
import { ManageToggleButton } from "@/components/bsg/workforce/ManageToggleButton";
import { SkillMatrixRowView } from "@/components/bsg/workforce/SkillMatrixRowView";
import { WorkforcePlaceholder } from "@/components/bsg/workforce/WorkforcePlaceholder";
import { SkillRequirementsManager } from "@/components/bsg/WorkforceManagement";
import { SITE_LABELS } from "@/lib/workforceLabels";
import type { DeliverySite, SkillMatrixRow } from "@/types/workforce";

export function SkillCoverageMatrixSection({
  canReadInternalWorkforce,
  canManageWorkforce,
  resolvedProjectId,
  skillMatrixRows,
  filteredSkillMatrixRows,
  skillMatrixLoading,
  skillMatrixError,
  skillMatrixConfidencePct,
  visibleSites,
  showSkillRequirementsManager,
  onToggleSkillRequirementsManager,
}: {
  canReadInternalWorkforce: boolean;
  canManageWorkforce: boolean;
  resolvedProjectId: string | null;
  skillMatrixRows: SkillMatrixRow[];
  filteredSkillMatrixRows: SkillMatrixRow[];
  skillMatrixLoading: boolean;
  skillMatrixError: string | null;
  skillMatrixConfidencePct: number;
  visibleSites: DeliverySite[];
  showSkillRequirementsManager: boolean;
  onToggleSkillRequirementsManager: () => void;
}) {
  return (
    <Card>
      <SectionHeader
        title="Skill Coverage Matrix"
        sub="Required skills vs available project coverage"
        right={
          canReadInternalWorkforce ? (
            <div className="flex flex-wrap items-center gap-2">
              {skillMatrixRows.length > 0 ? (
                <span
                  className="inline-flex items-center gap-1.5 rounded-full border border-border bg-secondary px-2 py-0.5 text-[10px] font-medium text-muted-foreground"
                  title="Share of required skills currently at full (high) coverage"
                >
                  <span className="h-1.5 w-1.5 rounded-full bg-[color:var(--success)]" />
                  {skillMatrixConfidencePct}% fully covered
                </span>
              ) : null}
              {resolvedProjectId ? (
                <ManageToggleButton
                  active={showSkillRequirementsManager}
                  onClick={onToggleSkillRequirementsManager}
                  label={canManageWorkforce ? "Manage" : "Details"}
                />
              ) : null}
            </div>
          ) : undefined
        }
      />
      {!canReadInternalWorkforce ? (
        <WorkforcePlaceholder
          title="Skill coverage restricted"
          reason="Internal workforce skill coverage is not available to client users."
        />
      ) : skillMatrixLoading ? (
        <div className="space-y-2">
          <div className="h-10 animate-pulse rounded-md bg-elevated" />
          <div className="h-10 animate-pulse rounded-md bg-elevated" />
          <div className="h-10 animate-pulse rounded-md bg-elevated" />
        </div>
      ) : skillMatrixError ? (
        <p className="text-sm text-[color:var(--danger)]">{skillMatrixError}</p>
      ) : skillMatrixRows.length === 0 ? (
        <WorkforcePlaceholder
          title="No skill requirements yet"
          reason="Add project skill requirements to populate this matrix."
          actionLabel={
            canManageWorkforce && resolvedProjectId && !showSkillRequirementsManager
              ? "Add skill requirements"
              : undefined
          }
          onAction={
            canManageWorkforce && resolvedProjectId ? onToggleSkillRequirementsManager : undefined
          }
        />
      ) : filteredSkillMatrixRows.length === 0 ? (
        <WorkforcePlaceholder
          title="No skills match the current filters"
          reason="Change the site, domain, or skill category filter to expand the matrix."
        />
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full text-xs">
            <thead className="text-left text-muted-foreground">
              <tr className="border-b border-border">
                <th className="py-2 pr-3 font-medium">Skill</th>
                <th className="py-2 pr-3 font-medium">Proficiency</th>
                <th className="py-2 pr-3 font-medium">Headcount</th>
                <th className="py-2 pr-3 font-medium">SMEs</th>
                <th className="py-2 pr-3 font-medium">Status</th>
                {visibleSites.map((site) => (
                  <th key={site} className="py-2 pr-3 text-center font-medium">
                    {SITE_LABELS[site]}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {filteredSkillMatrixRows.map((row) => (
                <SkillMatrixRowView key={row.skill_id} row={row} visibleSites={visibleSites} />
              ))}
            </tbody>
          </table>
        </div>
      )}
      {canReadInternalWorkforce && resolvedProjectId && showSkillRequirementsManager ? (
        <SkillRequirementsManager projectId={resolvedProjectId} canManage={canManageWorkforce} />
      ) : null}
    </Card>
  );
}
