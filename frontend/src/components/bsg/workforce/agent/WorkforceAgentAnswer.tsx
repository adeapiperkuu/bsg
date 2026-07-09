import { useMemo } from "react";
import type { AgentQueryEvidenceLinkRead } from "@/types/workforce";
import { confidenceLabel } from "./evidence-utils";
import { formatWorkforceAnswer } from "./format-workforce-answer";

type WorkforceAgentAnswerProps = {
  answerText: string;
  evidenceLinks: AgentQueryEvidenceLinkRead[];
  confidenceLevel?: string | null;
  insufficientEvidence?: boolean;
  modelUsed?: string | null;
  latencyMs?: number | null;
};

export function WorkforceAgentAnswer({
  answerText,
  evidenceLinks,
  confidenceLevel,
  insufficientEvidence,
}: WorkforceAgentAnswerProps) {
  const formatted = useMemo(() => {
    const dateContext = evidenceLinks
      .map((link) => link.description ?? "")
      .filter(Boolean)
      .join("\n");
    return formatWorkforceAnswer(answerText, { dateContext });
  }, [answerText, evidenceLinks]);

  const confidence =
    confidenceLabel(confidenceLevel) ?? confidenceLabel(formatted.parsedConfidence);

  return (
    <div className="space-y-3">
      <div>
        <h4 className="text-[13px] font-semibold leading-5 text-foreground">
          {formatted.headline}
        </h4>
        {formatted.summary && formatted.summary !== formatted.headline ? (
          <p className="mt-1 text-[11px] leading-5 text-muted-foreground">{formatted.summary}</p>
        ) : null}
      </div>

      {formatted.keyFindings.length > 0 && (
        <ul className="space-y-1.5 text-[11px] leading-5 text-foreground">
          {formatted.keyFindings.map((finding) => (
            <li key={finding} className="flex gap-2">
              <span className="mt-[7px] h-1 w-1 shrink-0 rounded-full bg-[color:var(--brand)]" />
              <span>{finding}</span>
            </li>
          ))}
        </ul>
      )}

      {formatted.dataFreshness ? (
        <div className="rounded-md border border-border/70 bg-secondary/30 px-2.5 py-2 text-[11px] leading-5 text-foreground">
          <div className="mb-0.5 text-[10px] font-semibold uppercase tracking-wide text-muted-foreground">
            Data freshness
          </div>
          {formatted.dataFreshness}
        </div>
      ) : null}

      {formatted.caution ? (
        <div className="rounded-md border border-[color:var(--warning)]/30 bg-[color:var(--warning)]/10 px-2.5 py-2 text-[11px] leading-5 text-foreground">
          <div className="mb-0.5 text-[10px] font-semibold uppercase tracking-wide text-[color:var(--warning)]">
            Caution
          </div>
          {formatted.caution}
        </div>
      ) : null}

      {formatted.nextStep ? (
        <div className="rounded-md border border-[color:var(--brand)]/20 bg-[color:var(--brand)]/5 px-2.5 py-2 text-[11px] leading-5 text-foreground">
          <div className="mb-0.5 text-[10px] font-semibold uppercase tracking-wide text-[color:var(--brand)]">
            Suggested next step
          </div>
          {formatted.nextStep}
        </div>
      ) : null}

      {(confidence || insufficientEvidence) && (
        <div className="flex flex-wrap items-center gap-2 text-[10px] text-muted-foreground">
          {confidence ? <span>Confidence: {confidence}</span> : null}
          {insufficientEvidence ? (
            <span className="text-[color:var(--warning)]">Limited evidence</span>
          ) : null}
        </div>
      )}
    </div>
  );
}
