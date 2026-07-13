import { useMemo } from "react";
import { AlertTriangle, CheckCircle2, Lightbulb } from "lucide-react";
import type { AgentQueryEvidenceLinkRead } from "@/types/workforce";
import { cn } from "@/lib/utils";
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

function answerTone(
  headline: string,
  insufficientEvidence?: boolean,
): "warning" | "success" | "info" {
  if (
    insufficientEvidence ||
    /below|gap|overloaded|underutilized|attention|shortage|limited/i.test(headline)
  ) {
    return "warning";
  }
  if (/on track|enough|no .*found|healthy/i.test(headline)) return "success";
  return "info";
}

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
  const tone = answerTone(formatted.headline, insufficientEvidence);
  const StatusIcon = tone === "success" ? CheckCircle2 : AlertTriangle;

  return (
    <div className="space-y-3 text-[11px] leading-5">
      <div className="space-y-2">
        <div className="flex items-center gap-1.5">
          <span
            className={cn(
              "inline-flex h-5 w-5 shrink-0 items-center justify-center rounded-full",
              tone === "warning" && "bg-[color:var(--warning)]/12 text-[color:var(--warning)]",
              tone === "success" && "bg-[color:var(--success)]/12 text-[color:var(--success)]",
              tone === "info" && "bg-[color:var(--brand)]/10 text-[color:var(--brand)]",
            )}
            aria-hidden="true"
          >
            <StatusIcon className="h-3.5 w-3.5" />
          </span>
          <span
            className={cn(
              "text-[10px] font-semibold uppercase tracking-wide",
              tone === "warning" && "text-[color:var(--warning)]",
              tone === "success" && "text-[color:var(--success)]",
              tone === "info" && "text-[color:var(--brand)]",
            )}
          >
            {tone === "warning" ? "Needs attention" : tone === "success" ? "On track" : "Insight"}
          </span>
        </div>

        <h4 className="text-[14px] font-semibold leading-5 text-foreground">
          {formatted.headline}
        </h4>
        {formatted.summary && formatted.summary !== formatted.headline ? (
          <p className="text-[12px] leading-5 text-foreground">{formatted.summary}</p>
        ) : null}
      </div>

      {formatted.keyFindings.length > 0 ? (
        <ul className="space-y-1.5 text-foreground">
          {formatted.keyFindings.map((finding) => (
            <li key={finding} className="flex gap-2">
              <span className="mt-[7px] h-1 w-1 shrink-0 rounded-full bg-[color:var(--brand)]" />
              <span>{finding}</span>
            </li>
          ))}
        </ul>
      ) : null}

      {formatted.dataFreshness ? (
        <div className="border-l-2 border-border bg-secondary/25 px-2.5 py-2 text-foreground">
          <div className="mb-0.5 text-[10px] font-semibold uppercase tracking-wide text-muted-foreground">
            Data freshness
          </div>
          {formatted.dataFreshness}
        </div>
      ) : null}

      {formatted.caution ? (
        <div className="border-l-2 border-[color:var(--warning)] bg-[color:var(--warning)]/8 px-2.5 py-2 text-foreground">
          <div className="mb-0.5 text-[10px] font-semibold uppercase tracking-wide text-[color:var(--warning)]">
            Caution
          </div>
          {formatted.caution}
        </div>
      ) : null}

      {formatted.nextStep ? (
        <div className="border-l-2 border-[color:var(--brand)] bg-[color:var(--brand)]/7 px-2.5 py-2 text-foreground">
          <div className="mb-0.5 flex items-center gap-1.5 text-[10px] font-semibold uppercase tracking-wide text-[color:var(--brand)]">
            <Lightbulb className="h-3 w-3" />
            Recommended action
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
