import { Loader2, Send } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { Card, EvidenceBadge, SectionHeader } from "@/components/bsg/widgets";
import { useAgentQuery } from "@/hooks/useAgentQuery";
import { cn } from "@/lib/utils";

const SUGGESTED_PROMPTS = [
  "Why is accuracy dropping this week?",
  "Which team has the most drift alerts?",
  "What's driving the rework rate?",
  "Summarize this week's quality for the client",
];

type Message = {
  role: "user" | "ai";
  text: string;
  confidenceLevel?: string | null;
  insufficientEvidence?: boolean;
  evidence?: string[];
};

function confidenceToneClass(level: string | null | undefined): string {
  if (level === "high") {
    return "border-[color:var(--success)]/30 bg-[color:var(--success)]/10 text-[color:var(--success)]";
  }
  if (level === "medium") {
    return "border-[color:var(--warning)]/30 bg-[color:var(--warning)]/10 text-[color:var(--warning)]";
  }
  if (level === "low") {
    return "border-[color:var(--danger)]/30 bg-[color:var(--danger)]/10 text-[color:var(--danger)]";
  }
  return "border-border bg-secondary text-muted-foreground";
}

export function AskQualityAgentPanel({ projectId }: { projectId: string | undefined }) {
  const [messages, setMessages] = useState<Message[]>([]);
  const [input, setInput] = useState("");
  const mutation = useAgentQuery(projectId);
  const scrollRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!scrollRef.current) return;
    scrollRef.current.scrollTo({ top: scrollRef.current.scrollHeight, behavior: "smooth" });
  }, [messages]);

  const send = async (text: string) => {
    if (!text.trim() || !projectId) return;
    setMessages((m) => [...m, { role: "user", text }]);
    setInput("");
    try {
      const result = await mutation.mutateAsync(text);
      setMessages((m) => [
        ...m,
        {
          role: "ai",
          text: result.answer_text,
          confidenceLevel: result.confidence_level,
          insufficientEvidence: result.insufficient_evidence,
          evidence: result.evidence_links.map((e) => e.description).filter(Boolean),
        },
      ]);
    } catch {
      setMessages((m) => [
        ...m,
        {
          role: "ai",
          text: "Unable to reach the quality agent. Check your connection and try again.",
        },
      ]);
    }
  };

  return (
    <Card>
      <SectionHeader
        title="Ask Quality Intelligence"
        sub="Natural-language queries, answered with cited evidence"
        right={<EvidenceBadge />}
      />
      {!projectId && (
        <p className="mb-3 text-xs text-muted-foreground">
          Select a project to ask quality questions.
        </p>
      )}

      {messages.length === 0 ? (
        <div className="mb-3">
          <div className="mb-2 text-[10px] font-semibold uppercase tracking-wider text-muted-foreground">
            Try asking
          </div>
          <div className="flex flex-wrap gap-1.5">
            {SUGGESTED_PROMPTS.map((prompt) => (
              <button
                key={prompt}
                type="button"
                disabled={!projectId || mutation.isPending}
                onClick={() => void send(prompt)}
                className="rounded-full border border-border bg-elevated px-2.5 py-1 text-[11px] hover:bg-card disabled:cursor-not-allowed disabled:opacity-50"
              >
                {prompt}
              </button>
            ))}
          </div>
        </div>
      ) : (
        <div ref={scrollRef} className="mb-3 max-h-72 space-y-2 overflow-y-auto pr-1 text-xs">
          {messages.map((msg, i) => (
            <div
              key={i}
              className={cn(
                "rounded-md p-2.5",
                msg.role === "user" ? "ml-8 bg-card" : "mr-8 bg-elevated",
              )}
            >
              <div className="mb-1 flex items-center gap-2">
                <span className="font-medium text-muted-foreground">
                  {msg.role === "user" ? "You" : "Agent"}
                </span>
                {msg.role === "ai" && msg.confidenceLevel && (
                  <span
                    className={cn(
                      "rounded-full border px-1.5 py-0.5 text-[10px] font-medium capitalize",
                      confidenceToneClass(msg.confidenceLevel),
                    )}
                  >
                    {msg.confidenceLevel} confidence
                  </span>
                )}
              </div>
              <p className="whitespace-pre-wrap leading-5">{msg.text}</p>
              {msg.insufficientEvidence && (
                <p className="mt-1.5 text-[10px] italic text-muted-foreground">
                  Limited evidence available for this answer.
                </p>
              )}
              {msg.evidence && msg.evidence.length > 0 && (
                <ul className="mt-2 space-y-0.5 border-t border-border pt-1.5">
                  {msg.evidence.map((item, idx) => (
                    <li key={idx} className="flex gap-1.5 text-[10px] text-muted-foreground">
                      <span aria-hidden>•</span>
                      <span>{item}</span>
                    </li>
                  ))}
                </ul>
              )}
            </div>
          ))}
        </div>
      )}

      <form
        className="flex gap-2"
        onSubmit={(e) => {
          e.preventDefault();
          void send(input);
        }}
      >
        <input
          value={input}
          onChange={(e) => setInput(e.target.value)}
          placeholder="Why is accuracy dropping this week?"
          disabled={!projectId || mutation.isPending}
          className="flex-1 rounded border border-border bg-card px-3 py-2 text-xs outline-none disabled:cursor-not-allowed disabled:opacity-60"
        />
        <button
          type="submit"
          disabled={!projectId || mutation.isPending || !input.trim()}
          className="flex items-center gap-1.5 rounded bg-[color:var(--brand)] px-3 py-2 text-xs font-medium text-[color:var(--brand-foreground)] disabled:opacity-50"
        >
          {mutation.isPending ? (
            <Loader2 className="h-3.5 w-3.5 animate-spin" aria-hidden />
          ) : (
            <Send className="h-3.5 w-3.5" aria-hidden />
          )}
          Ask
        </button>
      </form>
    </Card>
  );
}
