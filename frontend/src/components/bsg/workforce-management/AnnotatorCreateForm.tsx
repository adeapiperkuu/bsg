import { useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";

import { createTeamAnnotator } from "@/lib/api";
import { queryKeys } from "@/lib/queries/keys";
import { cn } from "@/lib/utils";
import type { DeliverySite } from "@/types/workforce";

import { ErrorText } from "./WorkforceManagementShared";
import { addButtonClass, inputClass, selectClass, SITE_LABELS } from "./workforceManagementUtils";

const DELIVERY_SITES: DeliverySite[] = ["india", "kosovo"];

type AnnotatorCreateFormProps = {
  projectId: string;
  teamId: string;
  defaultSite: DeliverySite;
  canManage: boolean;
};

export function AnnotatorCreateForm({
  projectId,
  teamId,
  defaultSite,
  canManage,
}: AnnotatorCreateFormProps) {
  const queryClient = useQueryClient();
  const [fullName, setFullName] = useState("");
  const [site, setSite] = useState<DeliverySite>(defaultSite);
  const [isSmeCertified, setIsSmeCertified] = useState(false);
  const [isActive, setIsActive] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const invalidate = () => {
    void queryClient.invalidateQueries({
      queryKey: queryKeys.projectWorkforceSummary(projectId),
    });
    void queryClient.invalidateQueries({
      queryKey: queryKeys.teamAnnotators(teamId),
    });
  };

  const addMutation = useMutation({
    mutationFn: () =>
      createTeamAnnotator(teamId, {
        full_name: fullName.trim(),
        site,
        is_sme_certified: isSmeCertified,
        is_active: isActive,
      }),
    onSuccess: () => {
      setError(null);
      setFullName("");
      setSite(defaultSite);
      setIsSmeCertified(false);
      setIsActive(true);
      invalidate();
    },
    onError: (err: Error) => setError(err.message),
  });

  if (!canManage) {
    return null;
  }

  const busy = addMutation.isPending;
  const canSubmit = fullName.trim().length > 0;

  return (
    <div className="mt-2 space-y-3 rounded border border-border/60 bg-card/50 p-3">
      <p className="text-[10px] font-medium uppercase tracking-wider text-muted-foreground">
        Add annotator
      </p>

      <label className="flex flex-col gap-1 text-[10px] text-muted-foreground">
        Full name
        <input
          type="text"
          value={fullName}
          disabled={busy}
          onChange={(event) => setFullName(event.target.value)}
          className={cn(inputClass, "h-9 px-2.5 text-xs")}
          placeholder="e.g. Jane Doe"
        />
      </label>

      <div className="grid grid-cols-3 gap-2">
        <label className="flex min-w-0 flex-col gap-1 text-[10px] text-muted-foreground">
          Site
          <select
            value={site}
            disabled={busy}
            onChange={(event) => setSite(event.target.value as DeliverySite)}
            className={cn(selectClass, "h-9 w-full px-2 text-xs")}
          >
            {DELIVERY_SITES.map((value) => (
              <option key={value} value={value}>
                {SITE_LABELS[value]}
              </option>
            ))}
          </select>
        </label>
        <label className="flex min-w-0 flex-col gap-1 text-[10px] text-muted-foreground">
          SME
          <select
            value={isSmeCertified ? "yes" : "no"}
            disabled={busy}
            onChange={(event) => setIsSmeCertified(event.target.value === "yes")}
            className={cn(selectClass, "h-9 w-full px-2 text-xs")}
          >
            <option value="no">Not SME</option>
            <option value="yes">SME certified</option>
          </select>
        </label>
        <label className="flex min-w-0 flex-col gap-1 text-[10px] text-muted-foreground">
          Status
          <select
            value={isActive ? "active" : "inactive"}
            disabled={busy}
            onChange={(event) => setIsActive(event.target.value === "active")}
            className={cn(selectClass, "h-9 w-full px-2 text-xs")}
          >
            <option value="active">Active</option>
            <option value="inactive">Inactive</option>
          </select>
        </label>
      </div>

      <button
        type="button"
        disabled={busy || !canSubmit}
        onClick={() => addMutation.mutate()}
        className={cn(
          addButtonClass,
          "h-9 w-full border-[color:var(--brand)] bg-[color:var(--brand)] px-3 text-xs font-medium text-[color:var(--brand-foreground)] hover:bg-[color:var(--brand)]/90",
        )}
      >
        {addMutation.isPending ? "Adding..." : "Add annotator"}
      </button>
      <ErrorText message={error} />
    </div>
  );
}
