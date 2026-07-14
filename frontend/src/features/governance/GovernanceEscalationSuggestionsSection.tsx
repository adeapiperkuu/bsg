import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { toast } from "sonner";

import { Card, SectionHeader, StatusPill } from "@/components/bsg/widgets";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import {
  dismissGovernanceAIRecommendation,
  escalationSuggestionScansQueryOptions,
  escalationSuggestionsQueryOptions,
  scanEscalationSuggestions,
  snoozeEscalationSuggestion,
} from "@/lib/queries/governance";
import type { GovernanceAIRecommendation, GovernanceAISuggestedAction } from "@/types/governance";

type ConvertHandler = (draft: {
  target: "escalation";
  recommendation: GovernanceAIRecommendation;
  action: GovernanceAISuggestedAction;
  suggestedActionIndex: number;
}) => void;

function triggerLabel(trigger: string | null | undefined): string {
  if (!trigger) return "Escalation condition";
  return trigger.replaceAll("_", " ");
}

function prettyLabel(value: string): string {
  return value.replaceAll("_", " ");
}

function EscalationSuggestionCard({
  suggestion,
  busy,
  onConvert,
  onDismiss,
  onSnooze,
}: {
  suggestion: GovernanceAIRecommendation;
  busy: boolean;
  onConvert: ConvertHandler;
  onDismiss: (id: string) => void;
  onSnooze: (id: string) => void;
}) {
  const [showEvidence, setShowEvidence] = useState(false);
  const escalationAction = suggestion.suggested_actions.find(
    (action) => action.action_type === "consider_escalation",
  );
  const escalationIndex = suggestion.suggested_actions.findIndex(
    (action) => action.action_type === "consider_escalation",
  );
  const categories = suggestion.risk_categories ?? [];
  const providers = suggestion.signal_providers ?? [];
  const detectedAt =
    suggestion.latest_detected_at ?? suggestion.detected_at ?? suggestion.generated_at;

  return (
    <div className="rounded-md border border-border bg-elevated p-3">
      <div className="mb-1 flex flex-wrap items-center gap-2">
        <StatusPill status="Escalation Suggested" />
        <StatusPill status={suggestion.priority} />
        {suggestion.project_name ? (
          <span className="text-[11px] text-muted-foreground">{suggestion.project_name}</span>
        ) : null}
        {suggestion.trigger_type ? (
          <span className="text-[11px] text-muted-foreground capitalize">
            {triggerLabel(suggestion.trigger_type)}
          </span>
        ) : null}
        {providers.map((provider) => (
          <span
            key={provider}
            className="rounded-full border border-border px-2 py-0.5 text-[10px] capitalize text-muted-foreground"
          >
            {prettyLabel(provider)}
          </span>
        ))}
      </div>
      <p className="text-sm font-medium">{suggestion.title}</p>
      <p className="mt-1 text-xs text-muted-foreground">{suggestion.narrative}</p>
      {categories.length > 0 || suggestion.linked_milestone_id ? (
        <div className="mt-2 flex flex-wrap gap-2 text-[10px] text-muted-foreground">
          {categories.map((category) => (
            <span key={category} className="rounded-full bg-muted px-2 py-0.5 capitalize">
              {prettyLabel(category)}
            </span>
          ))}
          {suggestion.linked_milestone_id ? (
            <span className="rounded-full bg-muted px-2 py-0.5">Linked milestone</span>
          ) : null}
        </div>
      ) : null}
      <p className="mt-2 text-[10px] text-muted-foreground">
        Detected{" "}
        {new Date(detectedAt).toLocaleString()}
        {suggestion.severity_score != null
          ? ` · severity score ${Math.round(suggestion.severity_score)}`
          : ""}
        {suggestion.confidence != null
          ? ` · confidence ${Math.round(suggestion.confidence * 100)}%`
          : ""}
        {suggestion.repeated_detection_count && suggestion.repeated_detection_count > 1
          ? ` - seen ${suggestion.repeated_detection_count} times`
          : ""}
        {suggestion.snoozed_until
          ? ` - snoozed until ${new Date(suggestion.snoozed_until).toLocaleDateString()}`
          : ""}
      </p>

      {showEvidence && suggestion.evidence.length > 0 ? (
        <ul className="mt-3 space-y-1 border-t border-border pt-2 text-[11px] text-muted-foreground">
          {suggestion.evidence.map((item) => (
            <li key={item.evidence_id} className="truncate">
              {item.title}
              {item.summary ? ` — ${item.summary}` : ""}
            </li>
          ))}
        </ul>
      ) : null}

      <div className="mt-3 flex flex-wrap gap-2">
        <Button
          type="button"
          size="sm"
          variant="outline"
          className="shadow-none"
          disabled={busy}
          onClick={() => setShowEvidence((value) => !value)}
        >
          {showEvidence ? "Hide evidence" : "View evidence"}
        </Button>
        {escalationAction && escalationIndex >= 0 && suggestion.status === "active" ? (
          <Button
            type="button"
            size="sm"
            className="shadow-none"
            disabled={busy}
            onClick={() =>
              onConvert({
                target: "escalation",
                recommendation: suggestion,
                action: escalationAction,
                suggestedActionIndex: escalationIndex,
              })
            }
          >
            Create escalation
          </Button>
        ) : null}
        {suggestion.can_dismiss ? (
          <Button
            type="button"
            size="sm"
            variant="outline"
            className="shadow-none"
            disabled={busy}
            onClick={() => onDismiss(suggestion.id)}
          >
            Dismiss
          </Button>
        ) : null}
        {suggestion.can_snooze !== false && suggestion.status === "active" ? (
          <Button
            type="button"
            size="sm"
            variant="outline"
            className="shadow-none"
            disabled={busy}
            onClick={() => onSnooze(suggestion.id)}
          >
            Snooze
          </Button>
        ) : null}
      </div>
    </div>
  );
}

export function GovernanceEscalationSuggestionsSection({
  focusProjectId,
  canWrite,
  onConvert,
  embedded = false,
}: {
  focusProjectId?: string | null;
  canWrite: boolean;
  onConvert: ConvertHandler;
  embedded?: boolean;
}) {
  const queryClient = useQueryClient();
  const listParams = {
    project_id: focusProjectId || undefined,
    status: "active",
    limit: 10,
  };
  const listQuery = useQuery({
    ...escalationSuggestionsQueryOptions(listParams),
    enabled: true,
  });
  const scansQuery = useQuery({
    ...escalationSuggestionScansQueryOptions({
      project_id: focusProjectId || undefined,
      limit: 1,
    }),
    enabled: true,
  });

  const invalidate = async () => {
    await queryClient.invalidateQueries({ queryKey: ["governance", "escalation-suggestions"] });
    await queryClient.invalidateQueries({ queryKey: ["governance", "escalation-suggestion-scans"] });
    await queryClient.invalidateQueries({ queryKey: ["governance", "ai-recommendations"] });
  };

  const scanMutation = useMutation({
    mutationFn: () =>
      scanEscalationSuggestions({
        project_id: focusProjectId || undefined,
        force: false,
      }),
    onSuccess: async (result) => {
      if (!result.enabled) {
        toast.message("Escalation suggestions are disabled.");
        return;
      }
      toast.success(
        result.suggestions_created
          ? `Scan complete: ${result.suggestions_created} new suggestion(s).`
          : result.candidates_detected === 0
            ? "No escalation-worthy risks found."
            : `Scan complete: ${result.suggestions_reused} existing suggestion(s) reused.`,
      );
      await invalidate();
    },
    onError: (err) => {
      toast.error(err instanceof Error ? err.message : "Scan failed.");
    },
  });

  const dismissMutation = useMutation({
    mutationFn: (id: string) => dismissGovernanceAIRecommendation(id, "Dismissed escalation suggestion"),
    onSuccess: async () => {
      toast.success("Suggestion dismissed.");
      await invalidate();
    },
    onError: (err) => {
      toast.error(err instanceof Error ? err.message : "Dismiss failed.");
    },
  });

  const snoozeMutation = useMutation({
    mutationFn: (id: string) => snoozeEscalationSuggestion(id, { days: 7 }),
    onSuccess: async () => {
      toast.success("Suggestion snoozed.");
      await invalidate();
    },
    onError: (err) => {
      toast.error(err instanceof Error ? err.message : "Snooze failed.");
    },
  });

  const items = listQuery.data ?? [];
  const lastScan = scansQuery.data?.[0];
  const busy =
    scanMutation.isPending || dismissMutation.isPending || snoozeMutation.isPending;

  const content = (
    <>
      <div className="mb-4 flex flex-wrap items-start justify-between gap-3">
        <SectionHeader
          title="Escalation suggestions"
          sub="Deterministic detection — review before creating any escalation"
        />
        {canWrite ? (
          <Button
            type="button"
            size="sm"
            className="shadow-none"
            disabled={busy}
            onClick={() => scanMutation.mutate()}
          >
            {scanMutation.isPending ? "Scanning…" : "Scan for escalation risks"}
          </Button>
        ) : null}
      </div>
      <p className="mb-3 text-xs text-muted-foreground">
        Scans never run on dashboard load. Escalations are never created automatically.
        {lastScan ? (
          <>
            {" "}
            Last scan {lastScan.status} at {new Date(lastScan.started_at).toLocaleString()}:{" "}
            {lastScan.suggestions_created} created, {lastScan.suggestions_refreshed} refreshed,{" "}
            {lastScan.signals_evaluated} signal(s).
          </>
        ) : null}
      </p>
      {listQuery.isLoading ? (
        <div className="space-y-2">
          <Skeleton className="h-16 w-full" />
          <Skeleton className="h-16 w-full" />
        </div>
      ) : items.length === 0 ? (
        <p className="py-2 text-sm text-muted-foreground">
          No active escalation suggestions
          {focusProjectId ? " for this project" : ""}. Run a scan when ready.
        </p>
      ) : (
        <div className="space-y-3">
          {items.map((item) => (
            <EscalationSuggestionCard
              key={item.id}
              suggestion={item}
              busy={busy}
              onConvert={onConvert}
              onDismiss={(id) => dismissMutation.mutate(id)}
              onSnooze={(id) => snoozeMutation.mutate(id)}
            />
          ))}
        </div>
      )}
    </>
  );

  if (embedded) return content;

  return <Card>{content}</Card>;
}
