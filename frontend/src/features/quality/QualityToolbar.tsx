import { Loader2 } from "lucide-react";
import type { ProjectRead } from "@/lib/api";

type Props = {
  projects: ProjectRead[];
  activeProjectId: string | undefined;
  onSelectProject: (projectId: string) => void;
  isUpdating: boolean;
  disabled: boolean;
};

export function QualityToolbar({
  projects,
  activeProjectId,
  onSelectProject,
  isUpdating,
  disabled,
}: Props) {
  return (
    <div className="flex flex-wrap items-center justify-between gap-3">
      <p className="text-xs text-muted-foreground">
        Drift, calibration, and reviewer quality for the selected project.
      </p>
      <div className="flex items-center gap-2">
        {isUpdating && (
          <span
            className="flex items-center gap-1.5 text-xs text-muted-foreground"
            aria-live="polite"
          >
            <Loader2 className="h-3.5 w-3.5 animate-spin" aria-hidden />
            Updating…
          </span>
        )}
        <label className="text-xs text-muted-foreground" htmlFor="quality-project-select">
          Project
        </label>
        <select
          id="quality-project-select"
          className="rounded border border-border bg-card px-2.5 py-1.5 text-xs outline-none disabled:cursor-not-allowed disabled:opacity-60"
          value={activeProjectId ?? ""}
          disabled={disabled}
          onChange={(e) => onSelectProject(e.target.value)}
        >
          {projects.map((p) => (
            <option key={p.id} value={p.id}>
              {p.name}
            </option>
          ))}
        </select>
      </div>
    </div>
  );
}
