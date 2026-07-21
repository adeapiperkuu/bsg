import { Card, SectionHeader } from "@/components/bsg/widgets";
import { TeamsManager } from "@/components/bsg/WorkforceManagement";
import { ManageToggleButton } from "@/components/bsg/workforce/ManageToggleButton";
import { TeamSummaryRow } from "@/components/bsg/workforce/TeamSummaryRow";
import type { AnnotatorRead, TeamRead } from "@/types/workforce";

export function TeamSummarySection({
  workforceLoading,
  hasTeams,
  canReadInternalWorkforce,
  canManageWorkforce,
  resolvedProjectId,
  teams,
  annotatorsByTeam,
  filteredTeams,
  expandedTeams,
  showTeamsManager,
  onToggleTeamsManager,
  onToggleTeam,
  onSelectAnnotator,
  embedded = false,
}: {
  workforceLoading: boolean;
  hasTeams: boolean;
  canReadInternalWorkforce: boolean;
  canManageWorkforce: boolean;
  resolvedProjectId: string | null;
  teams: TeamRead[];
  annotatorsByTeam: Map<string, AnnotatorRead[]>;
  filteredTeams: TeamRead[];
  expandedTeams: Set<string>;
  showTeamsManager: boolean;
  onToggleTeamsManager: () => void;
  onToggleTeam: (teamId: string) => void;
  onSelectAnnotator: (annotator: AnnotatorRead) => void;
  embedded?: boolean;
}) {
  const manageToggle =
    canManageWorkforce && resolvedProjectId ? (
      <ManageToggleButton
        active={showTeamsManager}
        onClick={onToggleTeamsManager}
        label="Manage"
      />
    ) : null;

  const body = (
    <>
      {embedded && manageToggle ? <div className="mb-3 flex justify-end">{manageToggle}</div> : null}
      {workforceLoading ? (
        <div className="space-y-2">
          <div className="h-10 animate-pulse rounded-md bg-elevated" />
          <div className="h-10 animate-pulse rounded-md bg-elevated" />
        </div>
      ) : !hasTeams ? (
        <p className="text-sm text-muted-foreground">
          No teams are configured for this project yet.
        </p>
      ) : filteredTeams.length === 0 ? (
        <p className="text-sm text-muted-foreground">No teams match the current filters.</p>
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full text-xs">
            <thead className="text-left text-muted-foreground">
              <tr className="border-b border-border">
                <th className="py-2 pr-3 font-medium">Team</th>
                <th className="py-2 pr-3 font-medium">Site</th>
                <th className="py-2 pr-3 font-medium">Domain</th>
                <th className="py-2 pr-3 font-medium">Annotators</th>
                <th className="py-2 pr-3 font-medium">SMEs</th>
                <th className="py-2 pr-3 font-medium">Status</th>
              </tr>
            </thead>
            <tbody>
              {filteredTeams.map((team) => {
                const teamAnnotators = canReadInternalWorkforce
                  ? (annotatorsByTeam.get(team.id) ?? [])
                  : null;
                const activeAnnotators = teamAnnotators
                  ? teamAnnotators.filter((annotator) => annotator.is_active)
                  : null;
                return (
                  <TeamSummaryRow
                    key={team.id}
                    team={team}
                    annotators={teamAnnotators}
                    annotatorCount={activeAnnotators ? activeAnnotators.length : null}
                    smeCount={
                      activeAnnotators
                        ? activeAnnotators.filter((annotator) => annotator.is_sme_certified).length
                        : null
                    }
                    expanded={expandedTeams.has(team.id)}
                    canManageWorkforce={canManageWorkforce}
                    showTeamsManager={showTeamsManager}
                    projectId={resolvedProjectId}
                    onToggle={() => onToggleTeam(team.id)}
                    onSelectAnnotator={onSelectAnnotator}
                  />
                );
              })}
            </tbody>
          </table>
        </div>
      )}
      {canManageWorkforce && resolvedProjectId && showTeamsManager ? (
        <TeamsManager projectId={resolvedProjectId} teams={teams} canManage={canManageWorkforce} />
      ) : null}
    </>
  );

  if (embedded) return body;

  return (
    <Card>
      <SectionHeader
        title="Team Summary"
        sub={
          canReadInternalWorkforce
            ? "Expand a team to open an employee profile"
            : "Team structure (annotator details restricted)"
        }
        right={manageToggle ?? undefined}
      />
      {body}
    </Card>
  );
}
