import { Card, SectionHeader } from "@/components/bsg/widgets";
import { TeamSummaryRow } from "@/components/bsg/workforce/TeamSummaryRow";
import type { AnnotatorRead, TeamRead } from "@/types/workforce";

export function TeamSummarySection({
  workforceLoading,
  hasTeams,
  canReadInternalWorkforce,
  annotatorsByTeam,
  filteredTeams,
  expandedTeams,
  onToggleTeam,
  onSelectAnnotator,
}: {
  workforceLoading: boolean;
  hasTeams: boolean;
  canReadInternalWorkforce: boolean;
  annotatorsByTeam: Map<string, AnnotatorRead[]>;
  filteredTeams: TeamRead[];
  expandedTeams: Set<string>;
  onToggleTeam: (teamId: string) => void;
  onSelectAnnotator: (annotator: AnnotatorRead) => void;
}) {
  return (
    <Card>
      <SectionHeader
        title="Team Summary"
        sub={
          canReadInternalWorkforce
            ? "Expand a team to open an employee profile"
            : "Team structure (annotator details restricted)"
        }
      />
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
                    onToggle={() => onToggleTeam(team.id)}
                    onSelectAnnotator={onSelectAnnotator}
                  />
                );
              })}
            </tbody>
          </table>
        </div>
      )}
    </Card>
  );
}
