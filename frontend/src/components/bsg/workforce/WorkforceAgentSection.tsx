import type { UseMutationResult } from "@tanstack/react-query";

import { AiBadge, Card, SectionHeader } from "@/components/bsg/widgets";
import { WorkforceAgentAnswer } from "@/components/bsg/workforce/WorkforceAgentAnswer";
import { WorkforcePlaceholder } from "@/components/bsg/workforce/WorkforcePlaceholder";
import type { AgentQueryRead } from "@/types/workforce";

export function WorkforceAgentSection({
  canReadInternalWorkforce,
  resolvedProjectId,
  starterQuestions,
  agentQuestion,
  onAgentQuestionChange,
  submitAgentQuestion,
  agentQueryMutation,
  agentAnswer,
}: {
  canReadInternalWorkforce: boolean;
  resolvedProjectId: string | null;
  starterQuestions: string[];
  agentQuestion: string;
  onAgentQuestionChange: (question: string) => void;
  submitAgentQuestion: (question: string) => void;
  agentQueryMutation: UseMutationResult<AgentQueryRead, Error, string>;
  agentAnswer: AgentQueryRead | null;
}) {
  return (
    <Card>
      <SectionHeader
        title="Ask Workforce Agent"
        sub="Evidence-backed answers on capacity, skills, and gaps"
        right={<AiBadge label="AI" />}
      />
      {!canReadInternalWorkforce ? (
        <WorkforcePlaceholder
          title="Workforce Agent restricted"
          reason="The Workforce Agent is available to internal roles only."
        />
      ) : (
        <div className="space-y-3">
          <div className="flex flex-wrap gap-1.5">
            {starterQuestions.map((question) => (
              <button
                key={question}
                type="button"
                onClick={() => {
                  onAgentQuestionChange(question);
                  submitAgentQuestion(question);
                }}
                disabled={agentQueryMutation.isPending || !resolvedProjectId}
                className="rounded border border-border bg-elevated px-2 py-1 text-[11px] text-muted-foreground hover:bg-card disabled:opacity-50"
              >
                {question}
              </button>
            ))}
          </div>
          <textarea
            value={agentQuestion}
            onChange={(event) => onAgentQuestionChange(event.target.value)}
            placeholder="Ask about capacity, SME coverage, utilization, skills, training, or capability gaps..."
            rows={3}
            className="w-full resize-y rounded border border-border bg-card px-3 py-2 text-xs outline-none placeholder:text-muted-foreground/60"
          />
          <div className="flex items-center justify-between gap-3">
            <span className="text-[11px] text-muted-foreground">
              {resolvedProjectId
                ? "Scoped to the selected project."
                : "Select a project to ask a question."}
            </span>
            <button
              type="button"
              onClick={() => submitAgentQuestion(agentQuestion)}
              disabled={
                agentQueryMutation.isPending ||
                !resolvedProjectId ||
                agentQuestion.trim().length === 0
              }
              className="rounded border border-[color:var(--brand)]/30 bg-[color:var(--brand)]/10 px-3 py-1.5 text-[11px] font-medium text-[color:var(--brand)] hover:bg-[color:var(--brand)]/20 disabled:opacity-50"
            >
              {agentQueryMutation.isPending ? "Asking..." : "Ask"}
            </button>
          </div>
          {agentQueryMutation.isError && (
            <p className="text-xs text-[color:var(--danger)]">
              {agentQueryMutation.error instanceof Error
                ? agentQueryMutation.error.message
                : "Failed to get an answer."}
            </p>
          )}
          {agentQueryMutation.isPending && (
            <div className="space-y-2">
              <div className="h-4 animate-pulse rounded bg-elevated" />
              <div className="h-4 w-3/4 animate-pulse rounded bg-elevated" />
            </div>
          )}
          {agentAnswer && !agentQueryMutation.isPending && (
            <WorkforceAgentAnswer answer={agentAnswer} />
          )}
        </div>
      )}
    </Card>
  );
}
