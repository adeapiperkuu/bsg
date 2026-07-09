import { Bot } from "lucide-react";
import { cn } from "@/lib/utils";
import { WorkforceAgentAnswer } from "./WorkforceAgentAnswer";
import type { WorkforceChatMessage } from "./types";

type Props = {
  message: WorkforceChatMessage;
};

export function WorkforceAgentMessage({ message }: Props) {
  return (
    <div className={cn("flex gap-3", message.role === "user" ? "justify-end" : "justify-start")}>
      {message.role === "agent" && (
        <div className="mt-1 flex h-7 w-7 shrink-0 items-center justify-center rounded-full bg-card text-muted-foreground">
          <Bot className="h-3.5 w-3.5" />
        </div>
      )}
      <div
        className={cn(
          "max-w-[88%] rounded-md px-3 py-3",
          message.role === "user"
            ? "bg-[color:var(--brand)] text-[color:var(--brand-foreground)]"
            : "bg-card",
          message.error && "border border-[color:var(--danger)]/30",
        )}
      >
        <div
          className={cn(
            "mb-1 text-[10px] font-semibold uppercase tracking-wider",
            message.role === "user" ? "text-white/70" : "text-muted-foreground",
          )}
        >
          {message.role === "user" ? "You" : "Workforce Agent"}
        </div>

        {message.role === "agent" && message.answer ? (
          <WorkforceAgentAnswer
            answerText={message.answer.answer_text}
            evidenceLinks={message.answer.evidence_links ?? []}
            confidenceLevel={message.answer.confidence_level}
            insufficientEvidence={message.answer.insufficient_evidence}
            modelUsed={message.answer.model_used}
            latencyMs={message.answer.latency_ms}
          />
        ) : message.role === "agent" ? (
          <p className="text-[11px] leading-5">{message.text}</p>
        ) : (
          <p className="text-[11px] leading-5">{message.text}</p>
        )}
      </div>
    </div>
  );
}
