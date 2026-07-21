import { useMutation, useQueryClient } from "@tanstack/react-query";
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

const URGENCY_LABEL: Record<string, string> = {
  critical: "Critical",
  high: "High",
  medium: "Medium",
  low: "Low",
};

/** Bordered sub-panel so every briefing section has the same visual weight. */
function SectionCard({
  title,
  className,
  children,
}: {
  title: string;
  className?: string;
  children: React.ReactNode;
}) {
  return (
    <div className={cn("rounded-md border border-border bg-elevated/30 p-3.5", className)}>
      <p className="mb-2 text-[11px] font-semibold uppercase tracking-wider text-muted-foreground">
        {title}
      </p>
      {children}
    </div>
  );
}

function BulletList({ items, max = 8 }: { items: string[]; max?: number }) {
  return (
    <ul className="space-y-1.5">
      {items.slice(0, max).map((item) => (
        <li key={item} className="flex gap-2 text-xs leading-snug text-foreground/85">
          <span className="mt-[5px] h-1 w-1 shrink-0 rounded-full bg-muted-foreground/60" />
          <span>{item}</span>
        </li>
      ))}
      {items.length > max ? (
        <li className="text-[11px] text-muted-foreground">+{items.length - max} more</li>
      ) : null}
    </ul>
  );
}

function ConfidenceMovementCard({ briefing }: { briefing: OperationalBriefing }) {
  const move = briefing.confidence_movement;
  const deltaTone =
    move.delta == null || move.delta === 0
      ? "text-muted-foreground"
      : move.delta > 0
        ? "text-[color:var(--success)]"
        : "text-[color:var(--danger)]";
  const arrow = move.delta == null || move.delta === 0 ? "→" : move.delta > 0 ? "▲" : "▼";
  return (
    <SectionCard title="Confidence movement">
      <div className="flex items-baseline gap-2">
        <span className="text-2xl font-semibold tabular-nums text-foreground">
          {move.current.toFixed(0)}%
        </span>
        {move.delta != null ? (
          <span className={cn("text-sm font-medium tabular-nums", deltaTone)}>
            {arrow} {move.delta > 0 ? "+" : ""}
            {move.delta.toFixed(1)} pts
          </span>
        ) : (
          <span className="text-xs text-muted-foreground">no prior score</span>
        )}
      </div>
      {move.previous != null ? (
        <p className="mt-1 text-[11px] text-muted-foreground">
          Previous {move.previous.toFixed(0)}% → current {move.current.toFixed(0)}%
        </p>
      ) : null}
      {move.drivers.length > 0 ? (
        <div className="mt-2.5 border-t border-border/60 pt-2.5">
          <BulletList items={move.drivers} max={3} />
        </div>
      ) : null}
    </SectionCard>
  );
}

function PmActionsCard({ briefing }: { briefing: OperationalBriefing }) {
  if (briefing.recommended_pm_actions.length === 0) return null;
  return (
    <SectionCard title="Recommended PM actions">
      <ol className="space-y-2">
        {briefing.recommended_pm_actions.map((action) => (
          <li key={`${action.rank}-${action.title}`} className="flex items-start gap-2.5">
            <span className="mt-0.5 flex h-5 w-5 shrink-0 items-center justify-center rounded-full bg-elevated text-[10px] font-semibold text-muted-foreground">
              {action.rank}
            </span>
            <div className="min-w-0">
              <p className="text-xs font-medium leading-snug text-foreground">{action.title}</p>
              <div className="mt-0.5 flex flex-wrap items-center gap-1.5">
                <StatusPill status={URGENCY_LABEL[action.urgency] ?? action.urgency} />
                <span className="text-[10px] text-muted-foreground">
                  ~{Math.round(action.estimated_impact_points)} pts impact
                </span>
              </div>
            </div>
          </li>
        ))}
      </ol>
    </SectionCard>
  );
}

export function OperationalBriefingPanel({ projectId, projectName }: Props) {
  const queryClient = useQueryClient();
  const role = useAuthStore((s) => s.user?.role);
  const canView = role !== "client";
  const canOperate = role === "delivery_manager" || role === "super_admin";
  const query = useProjectOperationalBriefingQuery(projectId, canView);

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

      {query.isLoading ? (
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
        <div className="space-y-4">
          <div className="flex flex-wrap items-center gap-2.5">
            <StatusPill
              status={TRAFFIC_LABEL[briefing.traffic_light] ?? briefing.traffic_light}
            />
            <p className="text-sm font-semibold text-foreground">{briefing.headline}</p>
            <span className="text-[11px] text-muted-foreground">as of {briefing.as_of}</span>
          </div>

          {/* The deterministic narrative is a machine-built concatenation of the exact
              facts already shown in the section cards below, so rendering it just adds
              a wall of duplicated text. Only the AI-written narrative reads as prose
              worth surfacing. */}
          {briefing.narrative && briefing.ai_generated ? (
            <div className="rounded-md border border-[color:var(--brand)]/25 bg-[color:var(--brand)]/5 p-3.5">
              <p className="whitespace-pre-wrap text-sm leading-relaxed text-foreground/90">
                {briefing.narrative}
              </p>
            </div>
          ) : null}

          <div className="grid items-start gap-3 md:grid-cols-2">
            <div className="space-y-3">
              {briefing.overnight_changes.length > 0 ? (
                <SectionCard title="Overnight changes">
                  <BulletList items={briefing.overnight_changes} />
                </SectionCard>
              ) : null}
              {briefing.new_risks.length > 0 ? (
                <SectionCard title="New risks">
                  <BulletList items={briefing.new_risks} />
                </SectionCard>
              ) : null}
              {briefing.milestones_due_soon.length > 0 ? (
                <SectionCard title="Milestones due soon">
                  <BulletList items={briefing.milestones_due_soon} />
                </SectionCard>
              ) : null}
            </div>
            <div className="space-y-3">
              <ConfidenceMovementCard briefing={briefing} />
              {briefing.top_priorities.length > 0 ? (
                <SectionCard title="Top priorities">
                  <BulletList items={briefing.top_priorities} />
                </SectionCard>
              ) : null}
              <PmActionsCard briefing={briefing} />
            </div>
          </div>

          {(briefing.knowledge_evidence?.length ?? 0) > 0 ? (
            <SectionCard title="Knowledge evidence">
              <ul className="grid gap-3 md:grid-cols-2">
                {briefing.knowledge_evidence!.slice(0, 5).map((item) => (
                  <li key={`${item.document_id}-${item.chunk_id ?? item.title}`}>
                    <a
                      href={`/knowledge?documentId=${encodeURIComponent(item.document_id)}`}
                      className="text-xs font-medium text-foreground hover:underline"
                    >
                      {item.title}
                    </a>
                    {item.source_type ? (
                      <span className="text-[10px] text-muted-foreground">
                        {" "}
                        · {item.source_type}
                      </span>
                    ) : null}
                    {item.excerpt ? (
                      <p className="mt-0.5 line-clamp-2 text-[11px] text-muted-foreground">
                        {item.excerpt}
                      </p>
                    ) : null}
                  </li>
                ))}
              </ul>
            </SectionCard>
          ) : null}
        </div>
      )}
    </Card>
  );
}
