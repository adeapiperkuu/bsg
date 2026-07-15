import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useMemo, useState } from "react";
import { Plus, ThumbsDown, ThumbsUp } from "lucide-react";
import { toast } from "sonner";

import { Card, SectionHeader, StatusPill } from "@/components/bsg/widgets";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Skeleton } from "@/components/ui/skeleton";
import { Textarea } from "@/components/ui/textarea";
import { useGovernanceJob } from "@/features/governance/useGovernanceJob";
import {
  convertGovernanceAIRecommendationToAction,
  convertGovernanceAIRecommendationToEscalation,
  dismissGovernanceAIRecommendation,
  generateGovernanceAIRecommendations,
  governanceAIRecommendationsQueryOptions,
  regenerateGovernanceAIRecommendation,
  submitGovernanceAIRecommendationFeedback,
} from "@/lib/queries/governance";
import { queryKeys } from "@/lib/queries/keys";
import type {
  GovernanceAIRecommendation,
  GovernanceAISuggestedAction,
  GovernanceEscalationSeverity,
  GovernanceRecommendationConversion,
} from "@/types/governance";

function formatPriority(priority: string): string {
  if (priority === "critical") return "Critical";
  if (priority === "high") return "High";
  if (priority === "medium") return "Medium";
  if (priority === "low") return "Low";
  return priority;
}

type ConversionDraft =
  | {
      target: "action";
      recommendation: GovernanceAIRecommendation;
      action: GovernanceAISuggestedAction;
      suggestedActionIndex: number;
    }
  | {
      target: "escalation";
      recommendation: GovernanceAIRecommendation;
      action: GovernanceAISuggestedAction;
      suggestedActionIndex: number;
    };

const ACTION_CONVERTIBLE_TYPES = new Set([
  "review",
  "assign_owner",
  "resolve_dependency",
  "create_action",
  "schedule_governance_review",
  "update_scope",
  "monitor",
]);

const ESCALATION_CONVERTIBLE_TYPES = new Set(["consider_escalation"]);

function idempotencyKey(): string {
  if (typeof crypto !== "undefined" && "randomUUID" in crypto) {
    return crypto.randomUUID();
  }
  return `${Date.now()}-${Math.random().toString(16).slice(2)}`;
}

function conversionStatusLabel(
  status: GovernanceAIRecommendation["acceptance_status"],
): string | null {
  if (status === "accepted_as_action") return "Converted to Action";
  if (status === "accepted_as_escalation") return "Converted to Escalation";
  if (status === "partially_accepted") return "Partially Accepted";
  return null;
}

function AIRecommendationCard({
  recommendation,
  onDismiss,
  onRegenerate,
  onFeedback,
  onConvert,
  busy,
}: {
  recommendation: GovernanceAIRecommendation;
  onDismiss: (id: string) => void;
  onRegenerate: (id: string) => void;
  onFeedback: (id: string, helpful: boolean) => void;
  onConvert: (draft: ConversionDraft) => void;
  busy: boolean;
}) {
  const [showEvidence, setShowEvidence] = useState(false);
  const convertedLabel = conversionStatusLabel(recommendation.acceptance_status);
  const convertedIndex = recommendation.accepted_suggested_action_index;
  return (
    <div className="rounded-md border border-border bg-elevated p-2.5">
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0 flex-1">
          <div className="mb-1 flex flex-wrap items-center gap-2">
            {recommendation.is_stale ? <StatusPill status="Stale" /> : null}
            {convertedLabel ? <StatusPill status={convertedLabel} /> : null}
            {recommendation.project_name ? (
              <span className="text-[11px] text-muted-foreground">
                {recommendation.project_name}
              </span>
            ) : (
              <span className="text-[11px] text-muted-foreground">Portfolio</span>
            )}
          </div>
          <p className="text-sm font-medium">{recommendation.title}</p>
          <p className="mt-1 line-clamp-2 text-xs text-muted-foreground">
            {recommendation.narrative}
          </p>
          <p className="mt-1.5 line-clamp-2 text-[11px] text-muted-foreground">
            <span className="font-medium text-foreground">Rationale:</span>{" "}
            {recommendation.rationale}
          </p>
          {recommendation.suggested_actions.length > 0 ? (
            <ul className="mt-1.5 space-y-0.5 text-[11px] text-muted-foreground">
              {recommendation.suggested_actions.map((action, index) => (
                <li key={`${action.action_type}-${action.label}`}>
                  <span className="font-medium text-foreground">{action.label}:</span>{" "}
                  <span className="line-clamp-1">{action.description}</span>
                  {convertedIndex === index ? (
                    <span className="ml-2 text-foreground">
                      Converted
                      {recommendation.converted_action_id
                        ? ` → action ${recommendation.converted_action_id.slice(0, 8)}`
                        : recommendation.converted_escalation_id
                          ? ` → escalation ${recommendation.converted_escalation_id.slice(0, 8)}`
                          : ""}
                    </span>
                  ) : null}
                </li>
              ))}
            </ul>
          ) : null}
          <p className="mt-1.5 text-[10px] text-muted-foreground">
            Generated {new Date(recommendation.generated_at).toLocaleString()}
          </p>
        </div>
        <StatusPill status={formatPriority(recommendation.priority)} />
      </div>

      {showEvidence && recommendation.evidence.length > 0 ? (
        <ul className="mt-3 space-y-1 border-t border-border pt-2 text-[11px] text-muted-foreground">
          {recommendation.evidence.map((item) => (
            <li key={item.evidence_id} className="truncate">
              {item.title}
              {item.summary ? ` — ${item.summary}` : ""}
            </li>
          ))}
        </ul>
      ) : null}

      <div className="mt-2.5 flex flex-wrap gap-1.5">
        <Button
          type="button"
          size="sm"
          variant="outline"
          className="h-7 px-2 text-[10px] shadow-none"
          disabled={busy}
          onClick={() => setShowEvidence((value) => !value)}
        >
          {showEvidence ? "Hide evidence" : "Show evidence"}
        </Button>
        {recommendation.can_regenerate ? (
          <Button
            type="button"
            size="sm"
            variant="outline"
            className="h-7 px-2 text-[10px] shadow-none"
            disabled={busy}
            onClick={() => onRegenerate(recommendation.id)}
          >
            Regenerate
          </Button>
        ) : null}
        {recommendation.can_dismiss ? (
          <Button
            type="button"
            size="sm"
            variant="outline"
            className="h-7 px-2 text-[10px] shadow-none"
            disabled={busy}
            onClick={() => onDismiss(recommendation.id)}
          >
            Dismiss
          </Button>
        ) : null}
        {recommendation.status === "active" && !recommendation.is_stale
          ? recommendation.suggested_actions.map((action, index) => {
              const alreadyConverted = convertedIndex === index;
              const key = `${action.action_type}-${action.label}-${index}`;
              return (
                <span key={key} className="flex flex-wrap gap-2">
                  {ACTION_CONVERTIBLE_TYPES.has(action.action_type) ? (
                    <Button
                      type="button"
                      size="sm"
                      className="h-7 gap-1 px-2 text-[10px] shadow-none"
                      disabled={busy || alreadyConverted}
                      onClick={() =>
                        onConvert({
                          target: "action",
                          recommendation,
                          action,
                          suggestedActionIndex: index,
                        })
                      }
                    >
                      <Plus className="h-3.5 w-3.5" />
                      Create action
                    </Button>
                  ) : null}
                  {ESCALATION_CONVERTIBLE_TYPES.has(action.action_type) ? (
                    <Button
                      type="button"
                      size="sm"
                      variant="outline"
                      className="h-8 gap-1.5 px-2.5 text-xs shadow-none"
                      disabled={busy || alreadyConverted}
                      onClick={() =>
                        onConvert({
                          target: "escalation",
                          recommendation,
                          action,
                          suggestedActionIndex: index,
                        })
                      }
                    >
                      <Plus className="h-3.5 w-3.5" />
                      Create escalation
                    </Button>
                  ) : null}
                </span>
              );
            })
          : null}
        <span className="flex items-center gap-0.5">
          <Button
            type="button"
            size="icon"
            variant="ghost"
            className="h-7 w-7 rounded-md p-0 text-muted-foreground shadow-none hover:bg-transparent hover:text-foreground"
            aria-label="Helpful"
            title="Helpful"
            disabled={busy}
            onClick={() => onFeedback(recommendation.id, true)}
          >
            <ThumbsUp className="h-4 w-4" />
          </Button>
          <Button
            type="button"
            size="icon"
            variant="ghost"
            className="h-7 w-7 rounded-md p-0 text-muted-foreground shadow-none hover:bg-transparent hover:text-foreground"
            aria-label="Not helpful"
            title="Not helpful"
            disabled={busy}
            onClick={() => onFeedback(recommendation.id, false)}
          >
            <ThumbsDown className="h-4 w-4" />
          </Button>
        </span>
      </div>
    </div>
  );
}

function AIRecommendationsByProject({
  recommendations,
  busy,
  onDismiss,
  onRegenerate,
  onFeedback,
  onConvert,
}: {
  recommendations: GovernanceAIRecommendation[];
  busy: boolean;
  onDismiss: (id: string) => void;
  onRegenerate: (id: string) => void;
  onFeedback: (id: string, helpful: boolean) => void;
  onConvert: (draft: ConversionDraft) => void;
}) {
  const groups = useMemo(() => {
    const byProject = new Map<
      string,
      { key: string; label: string; recommendations: GovernanceAIRecommendation[] }
    >();
    for (const recommendation of recommendations) {
      const key = recommendation.project_id ?? "portfolio";
      const existing = byProject.get(key);
      if (existing) {
        existing.recommendations.push(recommendation);
        continue;
      }
      byProject.set(key, {
        key,
        label:
          recommendation.project_name ??
          (recommendation.project_id
            ? `Project ${recommendation.project_id.slice(0, 8)}`
            : "Portfolio"),
        recommendations: [recommendation],
      });
    }
    return Array.from(byProject.values());
  }, [recommendations]);
  const [selectedProject, setSelectedProject] = useState(groups[0]?.key ?? "");

  useEffect(() => {
    if (!groups.some((group) => group.key === selectedProject)) {
      setSelectedProject(groups[0]?.key ?? "");
    }
  }, [groups, selectedProject]);

  if (groups.length === 0) return null;
  const activeGroup = groups.find((group) => group.key === selectedProject) ?? groups[0];

  return (
    <div>
      <div className="flex flex-wrap items-center gap-2">
        <Label htmlFor="recommendation-project" className="text-xs text-muted-foreground">
          Project
        </Label>
        <Select value={activeGroup.key} onValueChange={setSelectedProject}>
          <SelectTrigger
            id="recommendation-project"
            aria-label="Recommendation project"
            className="h-8 w-full text-xs sm:w-[280px]"
          >
            <SelectValue placeholder="Select a project" />
          </SelectTrigger>
          <SelectContent>
            {groups.map((group) => (
              <SelectItem key={group.key} value={group.key}>
                {group.label} ({group.recommendations.length})
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      </div>

      <div className="mt-3 space-y-3">
        {activeGroup.recommendations.map((recommendation) => (
          <AIRecommendationCard
            key={recommendation.id}
            recommendation={recommendation}
            busy={busy}
            onDismiss={onDismiss}
            onRegenerate={onRegenerate}
            onFeedback={onFeedback}
            onConvert={onConvert}
          />
        ))}
      </div>
    </div>
  );
}

function ConversionDialog({
  draft,
  open,
  onOpenChange,
  onSubmit,
  pending,
}: {
  draft: ConversionDraft | null;
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onSubmit: (draft: ConversionDraft, values: Record<string, string>) => void;
  pending: boolean;
}) {
  const [title, setTitle] = useState("");
  const [description, setDescription] = useState("");
  const [projectId, setProjectId] = useState("");
  const [dueDate, setDueDate] = useState("");
  const [status, setStatus] = useState("open");
  const [severity, setSeverity] = useState<GovernanceEscalationSeverity>("medium");
  const [note, setNote] = useState("");

  useEffect(() => {
    if (!draft) return;
    setTitle(draft.action.label || draft.recommendation.title);
    setDescription(draft.action.description || draft.recommendation.narrative);
    setProjectId(draft.recommendation.project_id ?? "");
    setDueDate("");
    setStatus("open");
    setSeverity(
      draft.recommendation.priority === "critical" ? "high" : draft.recommendation.priority,
    );
    setNote("");
  }, [draft]);

  const disabled = pending || !draft || !title.trim() || !projectId.trim();

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="governance-no-shadow max-w-2xl rounded-xl border-border/80 shadow-none">
        <DialogHeader>
          <DialogTitle>
            {draft?.target === "escalation"
              ? "Create Governance Escalation"
              : "Create Governance Action"}
          </DialogTitle>
          <DialogDescription>
            Review and edit the record before creating it from the selected recommendation.
          </DialogDescription>
        </DialogHeader>
        {draft ? (
          <div className="space-y-4">
            <div className="rounded-lg border border-border bg-muted/20 p-3 text-xs text-muted-foreground">
              <p className="font-medium text-foreground">{draft.recommendation.title}</p>
              <p className="mt-1">{draft.action.description}</p>
            </div>
            <div className="grid gap-3 md:grid-cols-2">
              <div className="space-y-1.5 md:col-span-2">
                <Label htmlFor="conversion-title">Title</Label>
                <Input
                  id="conversion-title"
                  value={title}
                  onChange={(event) => setTitle(event.target.value)}
                />
              </div>
              <div className="space-y-1.5 md:col-span-2">
                <Label htmlFor="conversion-description">Description</Label>
                <Textarea
                  id="conversion-description"
                  rows={4}
                  value={description}
                  onChange={(event) => setDescription(event.target.value)}
                />
              </div>
              <div className="space-y-1.5">
                <Label htmlFor="conversion-project">Project ID</Label>
                <Input
                  id="conversion-project"
                  value={projectId}
                  onChange={(event) => setProjectId(event.target.value)}
                />
              </div>
              {draft.target === "action" ? (
                <>
                  <div className="space-y-1.5">
                    <Label htmlFor="conversion-due-date">Due date</Label>
                    <Input
                      id="conversion-due-date"
                      type="date"
                      value={dueDate}
                      onChange={(event) => setDueDate(event.target.value)}
                    />
                  </div>
                  <div className="space-y-1.5">
                    <Label>Status</Label>
                    <Select value={status} onValueChange={setStatus}>
                      <SelectTrigger>
                        <SelectValue />
                      </SelectTrigger>
                      <SelectContent>
                        <SelectItem value="open">Open</SelectItem>
                        <SelectItem value="in_progress">In Progress</SelectItem>
                      </SelectContent>
                    </Select>
                  </div>
                </>
              ) : (
                <>
                  <div className="space-y-1.5">
                    <Label>Severity</Label>
                    <Select
                      value={severity}
                      onValueChange={(value) => setSeverity(value as GovernanceEscalationSeverity)}
                    >
                      <SelectTrigger>
                        <SelectValue />
                      </SelectTrigger>
                      <SelectContent>
                        <SelectItem value="low">Low</SelectItem>
                        <SelectItem value="medium">Medium</SelectItem>
                        <SelectItem value="high">High</SelectItem>
                        <SelectItem value="critical">Critical</SelectItem>
                      </SelectContent>
                    </Select>
                  </div>
                  <div className="space-y-1.5">
                    <Label>Status</Label>
                    <Select value={status} onValueChange={setStatus}>
                      <SelectTrigger>
                        <SelectValue />
                      </SelectTrigger>
                      <SelectContent>
                        <SelectItem value="open">Open</SelectItem>
                        <SelectItem value="in_progress">In Progress</SelectItem>
                      </SelectContent>
                    </Select>
                  </div>
                </>
              )}
              <div className="space-y-1.5 md:col-span-2">
                <Label htmlFor="conversion-note">Acceptance note</Label>
                <Textarea
                  id="conversion-note"
                  rows={2}
                  value={note}
                  onChange={(event) => setNote(event.target.value)}
                />
              </div>
            </div>
          </div>
        ) : null}
        <DialogFooter>
          <Button
            type="button"
            variant="outline"
            onClick={() => onOpenChange(false)}
            disabled={pending}
          >
            Cancel
          </Button>
          <Button
            type="button"
            disabled={disabled}
            onClick={() =>
              draft &&
              onSubmit(draft, {
                title,
                description,
                projectId,
                dueDate,
                status,
                severity,
                note,
              })
            }
          >
            {pending ? "Creating..." : "Confirm"}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

export function GovernanceRecommendationsSection({
  canWrite,
  enabled = true,
}: {
  canWrite: boolean;
  enabled?: boolean;
}) {
  const queryClient = useQueryClient();
  const [conversionDraft, setConversionDraft] = useState<ConversionDraft | null>(null);
  const [lastConversion, setLastConversion] = useState<GovernanceRecommendationConversion | null>(
    null,
  );
  const listParams = { scope: "project" as const, status: "active", limit: 100 };
  const aiQuery = useQuery({
    ...governanceAIRecommendationsQueryOptions(listParams),
    // List only — never generate on mount.
    enabled,
  });

  const invalidate = async () => {
    await queryClient.invalidateQueries({ queryKey: ["governance", "ai-recommendations"] });
  };

  const generationJob = useGovernanceJob({
    jobType: "ai_recommendation_generate",
    enabled: canWrite && enabled,
    onSucceeded: async () => {
      toast.success("AI recommendations generated for review.");
      await invalidate();
    },
  });

  const generateMutation = useMutation({
    mutationFn: () =>
      generateGovernanceAIRecommendations({
        scope: "project",
        force: false,
      }),
    onSuccess: (started) => {
      generationJob.track(started);
      toast.message(
        started.deduplicated
          ? "Recommendation job already active."
          : "Recommendation generation queued.",
      );
    },
    onError: (err) => {
      toast.error(err instanceof Error ? err.message : "Failed to generate recommendations.");
    },
  });

  const regenerateMutation = useMutation({
    mutationFn: (id: string) => regenerateGovernanceAIRecommendation(id),
    onSuccess: (started) => {
      generationJob.track(started);
      toast.message(
        started.deduplicated ? "Regeneration job already active." : "Regeneration queued.",
      );
    },
    onError: (err) => {
      toast.error(err instanceof Error ? err.message : "Failed to regenerate.");
    },
  });

  const dismissMutation = useMutation({
    mutationFn: (id: string) => dismissGovernanceAIRecommendation(id),
    onSuccess: async () => {
      toast.success("Recommendation dismissed.");
      await invalidate();
    },
    onError: (err) => {
      toast.error(err instanceof Error ? err.message : "Failed to dismiss.");
    },
  });

  const feedbackMutation = useMutation({
    mutationFn: ({ id, helpful }: { id: string; helpful: boolean }) =>
      submitGovernanceAIRecommendationFeedback(id, { helpful }),
    onSuccess: () => toast.success("Feedback recorded."),
    onError: (err) => {
      toast.error(err instanceof Error ? err.message : "Failed to submit feedback.");
    },
  });

  const conversionMutation = useMutation({
    mutationFn: ({ draft, values }: { draft: ConversionDraft; values: Record<string, string> }) => {
      const base = {
        suggested_action_index: draft.suggestedActionIndex,
        title: values.title.trim(),
        description: values.description.trim() || null,
        project_id: values.projectId.trim(),
        note: values.note.trim() || null,
        idempotency_key: idempotencyKey(),
      };
      if (draft.target === "action") {
        return convertGovernanceAIRecommendationToAction(draft.recommendation.id, {
          ...base,
          due_date: values.dueDate || null,
          status: values.status as "open" | "in_progress",
        });
      }
      return convertGovernanceAIRecommendationToEscalation(draft.recommendation.id, {
        ...base,
        severity: values.severity as GovernanceEscalationSeverity,
        status: values.status as "open" | "in_progress",
      });
    },
    onSuccess: async (result) => {
      const created = result.created_action ?? result.created_escalation;
      const evidenceCount = created?.evidence_link_count ?? 0;
      toast.success(
        result.idempotent_reuse
          ? `Existing conversion reused${evidenceCount ? ` (${evidenceCount} evidence link(s))` : ""}.`
          : `Recommendation converted${evidenceCount ? ` with ${evidenceCount} evidence link(s)` : ""}.`,
      );
      setConversionDraft(null);
      setLastConversion(result);
      await invalidate();
      await queryClient.invalidateQueries({ queryKey: queryKeys.governanceActions({}) });
      await queryClient.invalidateQueries({ queryKey: queryKeys.governanceEscalations({}) });
      await queryClient.invalidateQueries({ queryKey: queryKeys.governanceBootstrap });
    },
    onError: (err) => {
      toast.error(err instanceof Error ? err.message : "Failed to convert recommendation.");
    },
  });

  const aiItems = (aiQuery.data?.items ?? []).filter(
    (item) => !(item.auto_detected && item.recommendation_type === "escalation_required"),
  );
  const aiEnabled = aiQuery.data?.ai_enabled ?? false;
  const canGenerate = Boolean(canWrite && aiQuery.data?.can_generate);
  const busy =
    generationJob.active ||
    generateMutation.isPending ||
    regenerateMutation.isPending ||
    dismissMutation.isPending ||
    feedbackMutation.isPending ||
    conversionMutation.isPending;

  return (
    <Card className="flex h-[460px] flex-col overflow-hidden">
      <div className="mb-3 flex flex-wrap items-start justify-between gap-2">
        <SectionHeader
          title="Recommendations"
          sub="AI-generated analysis with deterministic operational fallback"
        />
        {canGenerate ? (
          <Button
            type="button"
            size="sm"
            className="shadow-none"
            disabled={busy}
            onClick={() => generateMutation.mutate()}
          >
            {generateMutation.isPending || generationJob.active ? "Generating…" : "Generate"}
          </Button>
        ) : null}
      </div>

      {!aiEnabled ? (
        <p className="mb-3 text-xs text-muted-foreground">
          AI recommendations are disabled. Operational rule-based recommendations remain available.
        </p>
      ) : null}

      {lastConversion ? (
        <div className="mb-4 rounded-md border border-border bg-elevated p-3 text-xs">
          <p className="font-medium">
            {lastConversion.idempotent_reuse ? "Conversion reused" : "Conversion created"}
          </p>
          <p className="mt-1 text-muted-foreground">
            {lastConversion.conversion_target === "action"
              ? `Action ${lastConversion.created_action_id ?? ""}`
              : `Escalation ${lastConversion.created_escalation_id ?? ""}`}
            {" · "}
            {(lastConversion.created_action ?? lastConversion.created_escalation)
              ?.evidence_link_count ?? 0}{" "}
            evidence link(s) · source/evidence traceability available on the created record
          </p>
          <Button
            type="button"
            size="sm"
            variant="outline"
            className="mt-2 shadow-none"
            onClick={() => setLastConversion(null)}
          >
            Dismiss
          </Button>
        </div>
      ) : null}

      {aiQuery.isError ? (
        <p className="mb-3 text-sm text-destructive">
          {aiQuery.error instanceof Error
            ? aiQuery.error.message
            : "Unable to load AI recommendations."}
        </p>
      ) : null}

      <div className="min-h-0 flex-1 overflow-y-auto pr-1">
        <div className="space-y-3">
          {!enabled ? null : aiQuery.isLoading && aiItems.length === 0 ? (
            <div className="space-y-2">
              {[0, 1].map((row) => (
                <Skeleton key={row} className="h-20 w-full" />
              ))}
            </div>
          ) : aiItems.length === 0 ? (
            <p className="py-2 text-sm text-muted-foreground">
              No AI recommendations yet. Generate recommendations for every project when ready -
              this never runs on page load.
            </p>
          ) : (
            <AIRecommendationsByProject
              recommendations={aiItems}
              busy={busy}
              onDismiss={(id) => dismissMutation.mutate(id)}
              onRegenerate={(id) => regenerateMutation.mutate(id)}
              onFeedback={(id, helpful) => feedbackMutation.mutate({ id, helpful })}
              onConvert={setConversionDraft}
            />
          )}
        </div>
      </div>

      <ConversionDialog
        draft={conversionDraft}
        open={conversionDraft !== null}
        pending={conversionMutation.isPending}
        onOpenChange={(next) => {
          if (!next) setConversionDraft(null);
        }}
        onSubmit={(draft, values) => conversionMutation.mutate({ draft, values })}
      />
    </Card>
  );
}
