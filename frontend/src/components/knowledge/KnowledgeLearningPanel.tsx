import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { toast } from "sonner";

import { SectionHeader, StatusPill } from "@/components/bsg/widgets";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import {
  applyKnowledgeSuggestion,
  compareKnowledgeDuplicates,
  dismissKnowledgeSuggestion,
  generateKnowledgeSuggestions,
  getKnowledgeRetrievalQuality,
  listKnowledgeDocumentDuplicates,
  listKnowledgeGapSuggestions,
  listKnowledgeSuggestions,
  runKnowledgeEvaluation,
} from "@/lib/api";
import { queryKeys } from "@/lib/queries/keys";
import type {
  KnowledgeDuplicateCompareApi,
  KnowledgeEvaluationReportApi,
} from "@/types/knowledge";

export function KnowledgeLearningPanel({
  enabled,
  selectedDocumentId,
  canManage,
}: {
  enabled: boolean;
  selectedDocumentId?: string | null;
  canManage: boolean;
}) {
  const queryClient = useQueryClient();
  const [evalReport, setEvalReport] = useState<KnowledgeEvaluationReportApi | null>(null);
  const [duplicateCompare, setDuplicateCompare] = useState<KnowledgeDuplicateCompareApi | null>(
    null,
  );

  const suggestionsQuery = useQuery({
    queryKey: queryKeys.knowledgeSuggestions("open"),
    queryFn: () => listKnowledgeSuggestions("open"),
    enabled,
  });
  const gapsQuery = useQuery({
    queryKey: ["knowledge", "gap-suggestions"],
    queryFn: () => listKnowledgeGapSuggestions(2),
    enabled,
  });
  const qualityQuery = useQuery({
    queryKey: ["knowledge", "retrieval-quality"],
    queryFn: () => getKnowledgeRetrievalQuality(),
    enabled,
  });
  const duplicatesQuery = useQuery({
    queryKey: ["knowledge", "duplicates", selectedDocumentId ?? "__none__"],
    queryFn: () => listKnowledgeDocumentDuplicates(selectedDocumentId!),
    enabled: enabled && Boolean(selectedDocumentId),
  });

  const invalidate = async () => {
    await queryClient.invalidateQueries({ queryKey: ["knowledge", "suggestions"] });
    await queryClient.invalidateQueries({ queryKey: queryKeys.knowledgeSuggestions("open") });
    await queryClient.invalidateQueries({ queryKey: ["knowledge", "documents"] });
  };

  const generateMutation = useMutation({
    mutationFn: () => generateKnowledgeSuggestions(selectedDocumentId || undefined),
    onSuccess: async (rows) => {
      toast.success(`${rows.length} suggestion(s) generated.`);
      await invalidate();
    },
    onError: (err) => toast.error(err instanceof Error ? err.message : "Generate failed."),
  });

  const applyMutation = useMutation({
    mutationFn: (id: string) => applyKnowledgeSuggestion(id),
    onSuccess: async () => {
      toast.success("Suggestion applied.");
      await invalidate();
    },
    onError: (err) => toast.error(err instanceof Error ? err.message : "Apply failed."),
  });

  const dismissMutation = useMutation({
    mutationFn: (id: string) => dismissKnowledgeSuggestion(id),
    onSuccess: async () => {
      toast.success("Suggestion dismissed.");
      await invalidate();
    },
    onError: (err) => toast.error(err instanceof Error ? err.message : "Dismiss failed."),
  });

  const evalMutation = useMutation({
    mutationFn: () => runKnowledgeEvaluation(),
    onSuccess: (report) => {
      setEvalReport(report);
      toast.success(`Evaluation complete: ${report.passed}/${report.total} passed.`);
    },
    onError: (err) => toast.error(err instanceof Error ? err.message : "Evaluation failed."),
  });

  const compareMutation = useMutation({
    mutationFn: (rightId: string) =>
      compareKnowledgeDuplicates(selectedDocumentId!, rightId),
    onSuccess: (result) => setDuplicateCompare(result),
    onError: (err) => toast.error(err instanceof Error ? err.message : "Compare failed."),
  });

  if (!enabled) return null;

  const suggestions = suggestionsQuery.data ?? [];
  const gaps = gapsQuery.data ?? [];
  const quality = qualityQuery.data;
  const duplicates = duplicatesQuery.data ?? [];
  const busy =
    generateMutation.isPending ||
    applyMutation.isPending ||
    dismissMutation.isPending ||
    evalMutation.isPending ||
    compareMutation.isPending;

  return (
    <div className="space-y-3 rounded-md border border-border/70 bg-card/60 p-3">
      <div className="flex flex-wrap items-start justify-between gap-2">
        <SectionHeader
          title="Continuous learning"
          sub="Reviewable AI suggestions — never auto-applied"
        />
        {canManage ? (
          <div className="flex flex-wrap gap-1.5">
            <Button
              type="button"
              size="sm"
              variant="outline"
              className="h-7 px-2 text-[10px] shadow-none"
              disabled={busy}
              onClick={() => generateMutation.mutate()}
            >
              {generateMutation.isPending ? "Generating…" : "Generate suggestions"}
            </Button>
            <Button
              type="button"
              size="sm"
              variant="outline"
              className="h-7 px-2 text-[10px] shadow-none"
              disabled={busy}
              onClick={() => evalMutation.mutate()}
            >
              {evalMutation.isPending ? "Evaluating…" : "Run evaluation"}
            </Button>
          </div>
        ) : null}
      </div>

      <div>
        <p className="mb-2 text-[10px] font-semibold uppercase tracking-wider text-muted-foreground">
          Open suggestions
        </p>
        {suggestionsQuery.isLoading ? (
          <Skeleton className="h-12 w-full" />
        ) : suggestions.length === 0 ? (
          <p className="text-xs text-muted-foreground">No open suggestions.</p>
        ) : (
          <ul className="space-y-2">
            {suggestions.slice(0, 8).map((item) => (
              <li key={item.id} className="rounded border border-border/60 px-2 py-1.5 text-xs">
                <div className="flex flex-wrap items-center gap-2">
                  <StatusPill status={item.suggestion_type.replaceAll("_", " ")} />
                  <span className="font-medium text-foreground">{item.title}</span>
                </div>
                <p className="mt-1 text-muted-foreground">{item.detail}</p>
                {canManage ? (
                  <div className="mt-2 flex gap-1.5">
                    <Button
                      type="button"
                      size="sm"
                      className="h-6 px-2 text-[10px] shadow-none"
                      disabled={busy}
                      onClick={() => applyMutation.mutate(item.id)}
                    >
                      Apply
                    </Button>
                    <Button
                      type="button"
                      size="sm"
                      variant="outline"
                      className="h-6 px-2 text-[10px] shadow-none"
                      disabled={busy}
                      onClick={() => dismissMutation.mutate(item.id)}
                    >
                      Dismiss
                    </Button>
                  </div>
                ) : null}
              </li>
            ))}
          </ul>
        )}
      </div>

      <div>
        <p className="mb-2 text-[10px] font-semibold uppercase tracking-wider text-muted-foreground">
          Gap resolution suggestions
        </p>
        {gapsQuery.isLoading ? (
          <Skeleton className="h-10 w-full" />
        ) : gaps.length === 0 ? (
          <p className="text-xs text-muted-foreground">No repeated gaps detected.</p>
        ) : (
          <ul className="space-y-2">
            {gaps.slice(0, 5).map((gap) => (
              <li key={gap.gap_query} className="rounded border border-border/60 px-2 py-1.5 text-xs">
                <p className="font-medium text-foreground">
                  “{gap.gap_query}” · {gap.occurrence_count}×
                </p>
                <p className="mt-1 text-muted-foreground">
                  Auto-resolved: {gap.auto_resolved ? "yes" : "no"} ·{" "}
                  {gap.existing_documents_that_may_resolve.length} candidate doc(s) ·{" "}
                  {gap.documents_that_should_be_created.length} create suggestion(s)
                </p>
              </li>
            ))}
          </ul>
        )}
      </div>

      <div>
        <p className="mb-2 text-[10px] font-semibold uppercase tracking-wider text-muted-foreground">
          Retrieval quality
        </p>
        {qualityQuery.isLoading ? (
          <Skeleton className="h-10 w-full" />
        ) : !quality ? (
          <p className="text-xs text-muted-foreground">No quality analysis yet.</p>
        ) : (
          <div className="space-y-1 text-xs text-muted-foreground">
            <p>
              Failures {quality.repeated_retrieval_failures} · low-confidence trends{" "}
              {quality.low_confidence_trend_count}
              {quality.average_confidence != null
                ? ` · avg confidence ${Math.round(quality.average_confidence * 100)}%`
                : ""}
            </p>
            {quality.recommendations.slice(0, 3).map((item) => (
              <p key={item}>• {item}</p>
            ))}
          </div>
        )}
      </div>

      {selectedDocumentId ? (
        <div>
          <p className="mb-2 text-[10px] font-semibold uppercase tracking-wider text-muted-foreground">
            Duplicate detection
          </p>
          {duplicatesQuery.isLoading ? (
            <Skeleton className="h-10 w-full" />
          ) : duplicates.length === 0 ? (
            <p className="text-xs text-muted-foreground">No near-duplicates found for this document.</p>
          ) : (
            <ul className="space-y-2">
              {duplicates.slice(0, 5).map((match) => (
                <li key={match.document_id} className="rounded border border-border/60 px-2 py-1.5 text-xs">
                  <div className="flex flex-wrap items-center justify-between gap-2">
                    <span>
                      {match.title} · {Math.round(match.similarity * 100)}% · {match.kind}
                    </span>
                    {canManage ? (
                      <Button
                        type="button"
                        size="sm"
                        variant="outline"
                        className="h-6 px-2 text-[10px] shadow-none"
                        disabled={busy}
                        onClick={() => compareMutation.mutate(match.document_id)}
                      >
                        Compare
                      </Button>
                    ) : null}
                  </div>
                  <p className="mt-1 text-muted-foreground">{match.message}</p>
                </li>
              ))}
            </ul>
          )}
          {duplicateCompare ? (
            <div className="mt-2 rounded border border-border/60 bg-elevated px-2 py-1.5 text-xs">
              <p className="font-medium">
                {duplicateCompare.left_title} vs {duplicateCompare.right_title}
              </p>
              <p className="mt-1 text-muted-foreground">
                Similarity {Math.round(duplicateCompare.similarity * 100)}% · merge allowed:{" "}
                {duplicateCompare.can_merge ? "yes" : "no"}
              </p>
              <p className="mt-1 text-muted-foreground">{duplicateCompare.message}</p>
            </div>
          ) : null}
        </div>
      ) : null}

      {evalReport ? (
        <div className="rounded border border-border/60 px-2 py-1.5 text-xs">
          <p className="font-medium">
            Evaluation · {evalReport.passed}/{evalReport.total} passed (
            {Math.round(evalReport.pass_rate * 100)}%)
          </p>
          <p className="mt-1 whitespace-pre-wrap text-muted-foreground">{evalReport.report_text}</p>
        </div>
      ) : null}
    </div>
  );
}
