import { Card, SectionHeader, StatusPill } from "@/components/bsg/widgets";
import { RegionalSiteBadge } from "@/components/bsg/workforce/RegionalSiteBadge";
import { WorkforcePlaceholder } from "@/components/bsg/workforce/WorkforcePlaceholder";
import type { ProjectWorkforceSummary } from "@/lib/queries/workforce";
import { SITE_LABELS, siteSummaryFor, WORKFORCE_EMPTY_VALUE } from "@/lib/workforceLabels";
import { cn } from "@/lib/utils";
import type { DeliverySite, SkillMatrixRow, TeamRead } from "@/types/workforce";

export function RegionalOverviewSection({
  view,
  onViewChange,
  workforceLoading,
  hasTeams,
  filteredTeams,
  summary,
  canReadInternalWorkforce,
  filteredSiteUtilization,
  visibleSites,
  skillMatrixLoading,
  skillMatrixError,
  skillMatrixRows,
  filteredSkillMatrixRows,
}: {
  view: "geo" | "matrix";
  onViewChange: (view: "geo" | "matrix") => void;
  workforceLoading: boolean;
  hasTeams: boolean;
  filteredTeams: TeamRead[];
  summary: ProjectWorkforceSummary;
  canReadInternalWorkforce: boolean;
  filteredSiteUtilization: Record<DeliverySite, number | null>;
  visibleSites: DeliverySite[];
  skillMatrixLoading: boolean;
  skillMatrixError: string | null;
  skillMatrixRows: SkillMatrixRow[];
  filteredSkillMatrixRows: SkillMatrixRow[];
}) {
  const sitesWithTeams = visibleSites.filter((site) =>
    filteredTeams.some((team) => team.site === site),
  );
  const emptySites = visibleSites.filter((site) => !sitesWithTeams.includes(site));

  return (
    <Card>
      <SectionHeader
        title="By Region"
        sub="India / Kosovo"
        right={
          <div className="flex items-center gap-1 rounded-md border border-border bg-elevated p-0.5 text-[11px]">
            <button
              type="button"
              onClick={() => onViewChange("geo")}
              className={cn("rounded px-2 py-0.5", view === "geo" && "bg-card")}
            >
              Geographical
            </button>
            <button
              type="button"
              onClick={() => onViewChange("matrix")}
              className={cn("rounded px-2 py-0.5", view === "matrix" && "bg-card")}
            >
              Matrix
            </button>
          </div>
        }
      />
      {workforceLoading ? (
        <div className="grid grid-cols-2 gap-3">
          <div className="h-28 animate-pulse rounded-md bg-elevated" />
          <div className="h-28 animate-pulse rounded-md bg-elevated" />
        </div>
      ) : !hasTeams ? (
        <p className="text-sm text-muted-foreground">No teams to group by site yet.</p>
      ) : filteredTeams.length === 0 ? (
        <p className="text-sm text-muted-foreground">
          No regional data matches the current filters.
        </p>
      ) : (
        <div className="space-y-3">
          <div
            className={cn(
              "grid gap-3",
              sitesWithTeams.length > 1 ? "grid-cols-1 sm:grid-cols-2" : "grid-cols-1",
            )}
          >
            {sitesWithTeams.map((site) => {
              const siteTeams = filteredTeams.filter((team) => team.site === site);
              const siteAnnotators = siteTeams
                .flatMap((team) => summary.annotatorsByTeam.get(team.id) ?? [])
                .filter((annotator) => annotator.is_active);
              const stats = {
                teams: siteTeams.length,
                activeTeams: siteTeams.filter((team) => team.is_active).length,
                annotators: siteAnnotators.length,
                smes: siteAnnotators.filter((annotator) => annotator.is_sme_certified).length,
              };
              return (
                <div key={site} className="rounded-md border border-border bg-elevated p-3">
                  <div className="flex items-center justify-between">
                    <div className="text-sm font-semibold">{SITE_LABELS[site]}</div>
                    <StatusPill status="On Track" />
                  </div>
                  <dl className="mt-2 grid grid-cols-2 gap-x-3 gap-y-1 text-[11px]">
                    <div className="flex justify-between gap-2">
                      <dt className="text-muted-foreground">Teams</dt>
                      <dd className="font-medium">{stats.teams}</dd>
                    </div>
                    <div className="flex justify-between gap-2">
                      <dt className="text-muted-foreground">Active</dt>
                      <dd className="font-medium">{stats.activeTeams}</dd>
                    </div>
                    <div className="flex justify-between gap-2">
                      <dt className="text-muted-foreground">Annotators</dt>
                      <dd className="font-medium">
                        {canReadInternalWorkforce ? stats.annotators : WORKFORCE_EMPTY_VALUE}
                      </dd>
                    </div>
                    <div className="flex justify-between gap-2">
                      <dt className="text-muted-foreground">SMEs</dt>
                      <dd className="font-medium">
                        {canReadInternalWorkforce ? stats.smes : WORKFORCE_EMPTY_VALUE}
                      </dd>
                    </div>
                    <div className="col-span-2 flex justify-between gap-2">
                      <dt className="text-muted-foreground">Utilization</dt>
                      <dd className="font-medium">
                        {!canReadInternalWorkforce
                          ? WORKFORCE_EMPTY_VALUE
                          : filteredSiteUtilization[site] !== null
                            ? `${filteredSiteUtilization[site]}%`
                            : "No data"}
                      </dd>
                    </div>
                  </dl>
                </div>
              );
            })}
          </div>
          {emptySites.length > 0 ? (
            <p className="rounded-md border border-dashed border-border/80 bg-elevated/40 px-3 py-2 text-[11px] text-muted-foreground">
              No teams in {emptySites.map((site) => SITE_LABELS[site]).join(" or ")} for this
              project yet.
            </p>
          ) : null}
        </div>
      )}
      {view === "matrix" && (
        <div className="mt-4">
          {!canReadInternalWorkforce ? (
            <WorkforcePlaceholder
              title="Regional skill matrix restricted"
              reason="Internal workforce skill coverage is not available to client users."
            />
          ) : skillMatrixLoading ? (
            <div className="h-24 animate-pulse rounded-md bg-elevated" />
          ) : skillMatrixError ? (
            <p className="text-sm text-[color:var(--danger)]">{skillMatrixError}</p>
          ) : skillMatrixRows.length === 0 ? (
            <WorkforcePlaceholder
              title="No regional skill matrix data"
              reason="Add project skill requirements to compare India and Kosovo coverage."
            />
          ) : filteredSkillMatrixRows.length === 0 ? (
            <WorkforcePlaceholder
              title="No regional skill matrix matches the current filters"
              reason="Change the site, domain, or skill category filter to compare coverage."
            />
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full text-xs">
                <thead className="text-left text-muted-foreground">
                  <tr className="border-b border-border">
                    <th className="py-2 pr-3 font-medium">Skill</th>
                    {visibleSites.map((site) => (
                      <th key={site} className="py-2 pr-3 text-center font-medium">
                        {SITE_LABELS[site]}
                      </th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {filteredSkillMatrixRows.map((row) => {
                    return (
                      <tr key={row.skill_id} className="border-b border-border/50">
                        <td className="py-2.5 pr-3 font-medium">{row.skill_name}</td>
                        {visibleSites.map((site) => {
                          const siteSummary = siteSummaryFor(row, site);
                          return (
                            <td key={site} className="py-2.5 pr-3 text-center">
                              {siteSummary ? (
                                <RegionalSiteBadge
                                  summary={siteSummary}
                                  required={row.required_headcount}
                                />
                              ) : (
                                WORKFORCE_EMPTY_VALUE
                              )}
                            </td>
                          );
                        })}
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          )}
        </div>
      )}
    </Card>
  );
}
