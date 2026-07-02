import { StatusPill } from "@/components/bsg/widgets";
import { SheetDescription, SheetHeader, SheetTitle } from "@/components/ui/sheet";
import type { AnnotatorRead, TeamRead } from "@/types/workforce";

import { SITE_LABELS } from "./employeeProfileUtils";

type EmployeeProfileHeaderProps = {
  annotator: AnnotatorRead;
  team: TeamRead | undefined;
};

export function EmployeeProfileHeader({ annotator, team }: EmployeeProfileHeaderProps) {
  return (
    <>
      <SheetHeader className="space-y-1 text-left">
        <SheetTitle>{annotator.full_name}</SheetTitle>
        <SheetDescription>
          {team ? team.name : "Unassigned team"} / {SITE_LABELS[annotator.site]}
        </SheetDescription>
      </SheetHeader>

      <div className="flex flex-wrap gap-2">
        <StatusPill status={annotator.is_active ? "Active" : "Warning"} />
        <StatusPill status={annotator.is_sme_certified ? "Approved" : "Draft"} />
        {team?.domain ? (
          <span className="inline-flex items-center rounded-full border border-border bg-secondary px-2 py-0.5 text-[10px] font-medium text-muted-foreground">
            {team.domain}
          </span>
        ) : null}
      </div>

      <dl className="grid grid-cols-2 gap-x-4 gap-y-2 text-[11px]">
        <div className="flex flex-col">
          <dt className="text-muted-foreground">SME status</dt>
          <dd className="font-medium">
            {annotator.is_sme_certified ? "SME certified" : "Not SME certified"}
          </dd>
        </div>
        <div className="flex flex-col">
          <dt className="text-muted-foreground">Active status</dt>
          <dd className="font-medium">{annotator.is_active ? "Active" : "Inactive"}</dd>
        </div>
        <div className="flex flex-col">
          <dt className="text-muted-foreground">Site</dt>
          <dd className="font-medium">{SITE_LABELS[annotator.site]}</dd>
        </div>
        <div className="flex flex-col">
          <dt className="text-muted-foreground">Domain</dt>
          <dd className="font-medium">{team?.domain ?? "-"}</dd>
        </div>
      </dl>
    </>
  );
}
