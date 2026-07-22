import { useEffect, useRef } from "react";
import { Bot, Plus } from "lucide-react";
import { Card } from "@/components/bsg/widgets";
import { TypingIndicator } from "@/components/knowledge/TypingIndicator";
import { Button } from "@/components/ui/button";
import { WorkforceAgentComposer } from "./WorkforceAgentComposer";
import { WorkforceAgentHistory } from "./WorkforceAgentHistory";
import { WorkforceAgentMessage } from "./WorkforceAgentMessage";
import { WorkforceAgentSuggestions } from "./WorkforceAgentSuggestions";
import { useWorkforceAgentChat } from "./useWorkforceAgentChat";

type Props = {
  projectId: string | null;
  onAskingChange?: (asking: boolean) => void;
  /** Parent fold already provides chrome — skip outer Card + title. */
  embedded?: boolean;
};

export function WorkforceAgentChat({ projectId, onAskingChange, embedded = false }: Props) {
  const chatScrollRef = useRef<HTMLDivElement | null>(null);
  const {
    messages,
    input,
    setInput,
    asking,
    isInputDisabled,
    error,
    activeSessionId,
    historySessions,
    sendMessage,
    resetConversation,
    loadSession,
  } = useWorkforceAgentChat({ projectId, onAskingChange });

  const hasUserMessage = messages.some((message) => message.role === "user");

  const scrollToEnd = () => {
    const container = chatScrollRef.current;
    if (container) {
      container.scrollTo({ top: container.scrollHeight, behavior: "smooth" });
    }
  };

  useEffect(() => {
    scrollToEnd();
  }, [asking, messages.length]);

  const handleSubmit = () => {
    if (asking || isInputDisabled || !input.trim()) return;
    void sendMessage(input.trim());
  };

  const toolbar = (
    <div className="flex shrink-0 items-center justify-end gap-2">
      <WorkforceAgentHistory
        asking={isInputDisabled}
        activeSessionId={activeSessionId}
        sessions={historySessions}
        onSelectSession={loadSession}
      />
      {messages.length > 0 && (
        <Button
          type="button"
          variant="ghost"
          size="sm"
          disabled={isInputDisabled}
          className="h-8 gap-1.5 px-2 text-xs text-muted-foreground"
          onClick={resetConversation}
        >
          <Plus className="h-3.5 w-3.5" />
          New chat
        </Button>
      )}
    </div>
  );

  const body = (
    <>
      {embedded ? <div className="mb-2">{toolbar}</div> : null}

      {!embedded ? (
        <div className="border-b border-border/70 px-4 py-3">
          <div className="flex items-start justify-between gap-2">
            <div className="flex min-w-0 items-center gap-2">
              <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-md bg-[color:var(--brand)] text-[color:var(--brand-foreground)]">
                <Bot className="h-4 w-4" />
              </div>
              <div className="min-w-0">
                <h3 className="text-sm font-semibold tracking-tight text-foreground">
                  Ask Workforce Agent
                </h3>
              </div>
            </div>
            {toolbar}
          </div>
        </div>
      ) : null}

      {!hasUserMessage && (
        <div className={embedded ? "pb-2" : "px-4 pt-3"}>
          <WorkforceAgentSuggestions
            disabled={isInputDisabled}
            onSelect={(prompt) => void sendMessage(prompt)}
          />
        </div>
      )}

      <div
        ref={chatScrollRef}
        className={
          embedded
            ? "mb-3 min-h-[220px] max-h-[420px] flex-1 space-y-4 overflow-y-auto rounded-md bg-secondary/35 p-3 text-xs"
            : "mx-4 mb-3 mt-3 min-h-[220px] max-h-[420px] flex-1 space-y-4 overflow-y-auto rounded-md bg-secondary/35 p-3 text-xs"
        }
      >
        {messages.length === 0 && !asking && (
          <div className="flex flex-col items-center justify-center gap-2 py-8 text-center text-muted-foreground">
            <p className="max-w-[240px] text-[11px] leading-5">
              Ask about capacity, SME coverage, utilization, skills, training, or capability gaps.
            </p>
          </div>
        )}

        {messages.map((message) => (
          <WorkforceAgentMessage key={message.id} message={message} />
        ))}

        {asking && (
          <div className="flex gap-3">
            <div className="mt-1 flex h-7 w-7 shrink-0 items-center justify-center rounded-full bg-card text-muted-foreground">
              <Bot className="h-3.5 w-3.5" />
            </div>
            <div className="rounded-md bg-card px-3 py-3 text-xs text-muted-foreground">
              <div className="mb-1 text-[10px] font-semibold uppercase tracking-wider text-muted-foreground">
                Workforce Agent
              </div>
              <TypingIndicator label="Analyzing workforce data" />
            </div>
          </div>
        )}
      </div>

      <div className={embedded ? "border-t border-border/70 pt-3" : "border-t border-border/70 px-4 py-3"}>
        {!projectId && (
          <p className="mb-2 text-[11px] text-muted-foreground">
            Select a project to ask a question.
          </p>
        )}
        {error && <p className="mb-2 text-[11px] text-[color:var(--danger)]">{error}</p>}
        <WorkforceAgentComposer
          value={input}
          disabled={isInputDisabled}
          asking={asking}
          onChange={setInput}
          onSubmit={handleSubmit}
        />
      </div>
    </>
  );

  if (embedded) return <div className="flex flex-col">{body}</div>;

  return <Card className="flex flex-col p-0">{body}</Card>;
}
