import { useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { ChevronDown } from "lucide-react";
import { AiBadge, Card, SectionHeader, StatusPill } from "@/components/bsg/widgets";
import {
  generateProjectOperationalBriefing,
  type OperationalBriefing,
} from "@/lib/api";
import { useProjectOperationalBriefingQuery } from "@/lib/queries/delivery";
import { queryKeys } from "@/lib/queries/keys";
import { useAuthStore } from "@/stores/useAuthStore";
import { cn } from "@/lib/utils";

type Props = {
  projectId: string | null;
  projectName?: string;
};

const TRAFFIC_LABEL: Record<string, string> = {
  green: "Green",
  yellow: "Amber",
  amber: "Amber",
  red: "Red",
};

/** Joins list items into one flowing sentence-per-item paragraph. */
function toProse(items: string[], max = 8): string {
  const shown = items.slice(0, max).map((item) => {
    const trimmed = item.trim().replace(/[.;]+$/, "");
    return trimmed.charAt(0).toUpperCase() + trimmed.slice(1);
  });
  let text = shown.join(". ");
  if (text) text += ".";
  if (items.length > max) text += ` Plus ${items.length - max} more.`;
  return text;
}

function BriefingParagraph({ label, text }: { label: string; text: string }) {
  if (!text) return null;
  return (
    <p className="text-sm leading-relaxed text-foreground/90">
      <span className="font-semibold text-foreground">{label}. </span>
      {text}
    </p>
  );
}

function confidenceProse(briefing: OperationalBriefing): string {
  const move = briefing.confidence_movement;
  let text = `Delivery confidence is at ${move.current.toFixed(0)}%`;
  if (move.previous != null && move.delta != null && move.delta !== 0) {
    text += `, ${move.delta > 0 ? "up" : "down"} ${Math.abs(move.delta).toFixed(1)} points from ${move.previous.toFixed(0)}%`;
  } else if (move.previous == null) {
    text += " with no prior score to compare against";
  }
  text += ".";
  const drivers = toProse(move.drivers, 3);
  return drivers ? `${text} ${drivers}` : text;
}

function pmActionsProse(briefing: OperationalBriefing): string {
  return briefing.recommended_pm_actions
    .map(
      (action) =>
        `${action.title.trim().replace(/[.;]+$/, "")} (${action.urgency}, ~${Math.round(
          action.estimated_impact_points,
        )} pts impact)`,
    )
    .join(". ")
    .concat(briefing.recommended_pm_actions.length ? "." : "");
}

export function OperationalBriefingPanel({ projectId, projectName }: Props) {
  const queryClient = useQueryClient();
  const role = useAuthStore((s) => s.user?.role);
  const canView = role !== "client";
  const canOperate = role === "delivery_manager" || role === "super_admin";
  const query = useProjectOperationalBriefingQuery(projectId, canView);
  const [expanded, setExpanded] = useState(true);

  const refreshMutation = useMutation({
    mutationFn: () => generateProjectOperationalBriefing(projectId!, { with_ai: true }),
    onSuccess: (data) => {
      queryClient.setQueryData(queryKeys.projectOperationalBriefing(projectId!), data);
    },
  });

  if (!canView) return null;

  const briefing = query.data;

  return (
    <Card>
      <SectionHeader
        title="Daily Operational Briefing"
        sub={
          projectName
            ? `Grounded morning brief for ${projectName}`
            : "Overnight changes, confidence drivers, and PM priorities"
        }
        right={
          <div className="flex items-center gap-2">
            <AiBadge
              label={briefing?.ai_generated ? "AI narrative" : "Deterministic"}
              source={briefing?.ai_generated ? "model" : "formula"}
            />
            {canOperate ? (
              <button
                type="button"
                className="rounded border border-border px-2 py-1 text-xs text-muted-foreground hover:bg-elevated"
                disabled={!projectId || refreshMutation.isPending}
                onClick={() => refreshMutation.mutate()}
              >
                {refreshMutation.isPending ? "Generating…" : "Refresh with AI"}
              </button>
            ) : null}
          </div>
        }
      />

      <div className="mb-3 flex border-b border-border">
        <button
          type="button"
          aria-expanded={expanded}
          onClick={() => setExpanded((v) => !v)}
          className={cn(
            "flex items-center gap-1.5 border-b-2 px-3 py-1.5 text-xs font-medium transition-colors",
            expanded
              ? "border-[color:var(--brand)] text-foreground"
              : "border-transparent text-muted-foreground hover:text-foreground",
          )}
        >
          Briefing
          <ChevronDown
            className={cn("h-3.5 w-3.5 transition-transform", expanded ? "" : "-rotate-90")}
          />
        </button>
      </div>

      {!expanded ? null : query.isLoading ? (
        <div className="space-y-2">
          <div className="h-16 animate-pulse rounded bg-elevated" />
          <div className="h-24 animate-pulse rounded bg-elevated" />
        </div>
      ) : query.isError ? (
        <p className="text-sm text-muted-foreground">
          Could not load operational briefing
          {query.error instanceof Error ? `: ${query.error.message}` : "."}
        </p>
      ) : !briefing ? (
        <p className="text-sm text-muted-foreground">No briefing available for this project.</p>
      ) : (
        <div className="space-y-3">
          <div className="flex flex-wrap items-center gap-2.5">
            <StatusPill
              status={TRAFFIC_LABEL[briefing.traffic_light] ?? briefing.traffic_light}
            />
            <p className="text-sm font-semibold text-foreground">{briefing.headline}</p>
            <span className="text-[11px] text-muted-foreground">as of {briefing.as_of}</span>
          </div>

          <div className="space-y-3 rounded-md border border-border bg-background/60 p-4">
            {briefing.narrative && briefing.ai_generated ? (
              <p className="whitespace-pre-wrap text-sm leading-relaxed text-foreground/90">
                {briefing.narrative}
              </p>
            ) : null}
            {confidenceProse(briefing) ? (
              <BriefingParagraph label="Confidence movement" text={confidenceProse(briefing)} />
            ) : null}
            <BriefingParagraph
              label="Overnight changes"
              text={toProse(briefing.overnight_changes)}
            />
            <BriefingParagraph label="New risks" text={toProse(briefing.new_risks)} />
            <BriefingParagraph
              label="Milestones due soon"
              text={toProse(briefing.milestones_due_soon)}
            />
            <BriefingParagraph label="Top priorities" text={toProse(briefing.top_priorities)} />
            <BriefingParagraph
              label="Recommended PM actions"
              text={pmActionsProse(briefing)}
            />
            {(briefing.knowledge_evidence?.length ?? 0) > 0 ? (
              <p className="text-sm leading-relaxed text-foreground/90">
                <span className="font-semibold text-foreground">Knowledge evidence. </span>
                {briefing.knowledge_evidence!.slice(0, 5).map((item, index) => (
                  <span key={`${item.document_id}-${item.chunk_id ?? item.title}`}>
                    {index > 0 ? ", " : ""}
                    <a
                      href={`/knowledge?documentId=${encodeURIComponent(item.document_id)}`}
                      className="font-medium text-foreground hover:underline"
                    >
                      {item.title}
                    </a>
                    {item.source_type ? (
                      <span className="text-muted-foreground"> ({item.source_type})</span>
                    ) : null}
                  </span>
                ))}
                .
              </p>
            ) : null}
          </div>
        </div>
      )}
    </Card>
  );
}
