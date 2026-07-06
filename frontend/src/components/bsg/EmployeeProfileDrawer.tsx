import { Sheet, SheetContent } from "@/components/ui/sheet";
import type { AnnotatorRead, TeamRead } from "@/types/workforce";

import { EmployeeCertificationsSection } from "./employee-profile/EmployeeCertificationsSection";
import { EmployeeProfileBasicsSection } from "./employee-profile/EmployeeProfileBasicsSection";
import { EmployeeProfileHeader } from "./employee-profile/EmployeeProfileHeader";
import { EmployeeSkillsSection } from "./employee-profile/EmployeeSkillsSection";
import { EmployeeTrainingSection } from "./employee-profile/EmployeeTrainingSection";
import { EmployeeUtilizationSection } from "./employee-profile/EmployeeUtilizationSection";

export function EmployeeProfileDrawer({
  open,
  onOpenChange,
  annotator,
  team,
  teams,
  projectId,
  canManage,
  canRead = true,
  onAnnotatorUpdated,
  onAnnotatorRemoved,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  annotator: AnnotatorRead | null;
  team: TeamRead | undefined;
  teams: TeamRead[];
  projectId: string | null;
  canManage: boolean;
  canRead?: boolean;
  onAnnotatorUpdated: (annotator: AnnotatorRead) => void;
  onAnnotatorRemoved: () => void;
}) {
  const queriesEnabled = open && Boolean(annotator) && canRead;

  return (
    <Sheet open={open} onOpenChange={onOpenChange}>
      <SheetContent side="right" className="w-full overflow-y-auto sm:max-w-lg">
        {open && annotator ? (
          <EmployeeProfileBody
            annotator={annotator}
            team={team}
            teams={teams}
            projectId={projectId}
            canManage={canManage}
            queriesEnabled={queriesEnabled}
            onAnnotatorUpdated={onAnnotatorUpdated}
            onAnnotatorRemoved={onAnnotatorRemoved}
          />
        ) : null}
      </SheetContent>
    </Sheet>
  );
}

function EmployeeProfileBody({
  annotator,
  team,
  teams,
  projectId,
  canManage,
  queriesEnabled,
  onAnnotatorUpdated,
  onAnnotatorRemoved,
}: {
  annotator: AnnotatorRead;
  team: TeamRead | undefined;
  teams: TeamRead[];
  projectId: string | null;
  canManage: boolean;
  queriesEnabled: boolean;
  onAnnotatorUpdated: (annotator: AnnotatorRead) => void;
  onAnnotatorRemoved: () => void;
}) {
  const showBasicsEditor = canManage && teams.length > 0 && projectId !== null;

  return (
    <div className="space-y-6 pr-2">
      <EmployeeProfileHeader annotator={annotator} team={team} hideDetails={showBasicsEditor} />

      {showBasicsEditor ? (
        <EmployeeProfileBasicsSection
          annotator={annotator}
          teams={teams}
          projectId={projectId}
          canManage={canManage}
          onAnnotatorUpdated={onAnnotatorUpdated}
          onAnnotatorRemoved={onAnnotatorRemoved}
        />
      ) : null}

      <EmployeeUtilizationSection
        annotatorId={annotator.id}
        projectId={projectId}
        queriesEnabled={queriesEnabled}
      />

      <EmployeeSkillsSection
        annotatorId={annotator.id}
        canManage={canManage}
        queriesEnabled={queriesEnabled}
      />
      <EmployeeCertificationsSection
        annotatorId={annotator.id}
        canManage={canManage}
        queriesEnabled={queriesEnabled}
      />
      <EmployeeTrainingSection
        annotatorId={annotator.id}
        canManage={canManage}
        queriesEnabled={queriesEnabled}
      />

      {!canManage ? (
        <p className="text-[11px] text-muted-foreground">
          You have read-only access to employee details.
        </p>
      ) : null}
    </div>
  );
}
