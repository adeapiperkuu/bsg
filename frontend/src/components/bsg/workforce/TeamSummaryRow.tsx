import { StatusPill } from "@/components/bsg/widgets";
import { SITE_LABELS, WORKFORCE_EMPTY_VALUE } from "@/lib/workforceLabels";
import { cn } from "@/lib/utils";
import type { AnnotatorRead, TeamRead } from "@/types/workforce";

export function TeamSummaryRow({
  team,
  annotators,
  annotatorCount,
  smeCount,
  expanded,
  onToggle,
  onSelectAnnotator,
}: {
  team: TeamRead;
  annotators: AnnotatorRead[] | null;
  annotatorCount: number | null;
  smeCount: number | null;
  expanded: boolean;
  onToggle: () => void;
  onSelectAnnotator: (annotator: AnnotatorRead) => void;
}) {
  const canExpand = annotators !== null;
  const sortedAnnotators = canExpand
    ? [...annotators].sort((left, right) => left.full_name.localeCompare(right.full_name))
    : [];

  return (
    <>
      <tr className="border-b border-border/50">
        <td className="py-2.5 pr-3 font-medium">
          {canExpand ? (
            <button
              type="button"
              onClick={onToggle}
              className="flex items-center gap-1.5 text-left hover:text-[color:var(--brand)]"
              aria-expanded={expanded}
            >
              <span className="inline-block w-2 text-muted-foreground">{expanded ? "v" : ">"}</span>
              {team.name}
            </button>
          ) : (
            team.name
          )}
        </td>
        <td className="py-2.5 pr-3 text-muted-foreground">{SITE_LABELS[team.site]}</td>
        <td className="py-2.5 pr-3 text-muted-foreground">{team.domain}</td>
        <td className="py-2.5 pr-3">{annotatorCount ?? WORKFORCE_EMPTY_VALUE}</td>
        <td className="py-2.5 pr-3">{smeCount ?? WORKFORCE_EMPTY_VALUE}</td>
        <td className="py-2.5 pr-3">
          <StatusPill status={team.is_active ? "On Track" : "Warning"} />
        </td>
      </tr>
      {canExpand && expanded ? (
        <tr className="border-b border-border/50 bg-elevated/30">
          <td colSpan={6} className="px-3 py-2">
            {sortedAnnotators.length === 0 ? (
              <p className="text-[11px] text-muted-foreground">No annotators on this team yet.</p>
            ) : (
              <div className="flex flex-wrap gap-1.5">
                {sortedAnnotators.map((annotator) => (
                  <button
                    key={annotator.id}
                    type="button"
                    onClick={() => onSelectAnnotator(annotator)}
                    className={cn(
                      "rounded border px-2 py-1 text-[11px] hover:bg-card",
                      annotator.is_active
                        ? "border-border bg-elevated text-foreground"
                        : "border-border bg-elevated text-muted-foreground",
                    )}
                  >
                    {annotator.full_name}
                    {annotator.is_sme_certified ? " (SME)" : ""}
                  </button>
                ))}
              </div>
            )}
          </td>
        </tr>
      ) : null}
    </>
  );
}
