import { useEffect, useRef } from "react";
import { Bot } from "lucide-react";
import { Card, AiBadge } from "@/components/bsg/widgets";
import { TypingIndicator } from "@/components/knowledge/TypingIndicator";
import { DeliveryChatInput } from "@/components/delivery/delivery-chat-input";
import { DeliveryMessage } from "@/components/delivery/delivery-message";
import { DeliverySuggestions } from "@/components/delivery/delivery-suggestions";
import { useDeliveryChat } from "@/hooks/use-delivery-chat";

type Props = {
  projectId?: string | null;
};

export function DeliveryChat({ projectId }: Props) {
  const chatEndRef = useRef<HTMLDivElement | null>(null);
  const {
    messages,
    input,
    setInput,
    asking,
    animatingMessageIndex,
    isInputDisabled,
    suggestions,
    sendMessage,
    onAnimationComplete,
    resetConversation,
  } = useDeliveryChat({ projectId });

  const hasUserMessage = messages.some((message) => message.role === "user");

  const scrollToEnd = () => {
    chatEndRef.current?.scrollIntoView({ behavior: "smooth", block: "end" });
  };

  useEffect(() => {
    resetConversation();
  }, [projectId, resetConversation]);

  useEffect(() => {
    scrollToEnd();
  }, [asking, messages.length, animatingMessageIndex]);

  const handleSubmit = () => {
    if (input.trim()) {
      void sendMessage(input.trim());
    }
  };

  return (
    <Card className="sticky top-20 flex flex-col p-0">
      <div className="border-b border-border/70 px-4 py-3">
        <div className="flex items-start justify-between gap-2">
          <div className="flex min-w-0 items-center gap-2">
            <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-md bg-[color:var(--brand)] text-[color:var(--brand-foreground)]">
              <Bot className="h-4 w-4" />
            </div>
            <div className="min-w-0">
              <h3 className="text-sm font-semibold tracking-tight text-foreground">Ask Delivery Agent</h3>
              <p className="mt-0.5 text-xs text-muted-foreground">Evidence-backed delivery operations</p>
            </div>
          </div>
          <AiBadge />
        </div>
      </div>

      {!hasUserMessage && (
        <div className="px-4 pt-3">
          <DeliverySuggestions
            disabled={isInputDisabled}
            onSelect={(prompt) => void sendMessage(prompt)}
          />
        </div>
      )}

      <div className="mx-4 mb-3 mt-3 min-h-[220px] max-h-[420px] flex-1 space-y-4 overflow-y-auto rounded-md bg-secondary/35 p-3 text-xs">
        {messages.length === 0 && !asking && (
          <div className="flex flex-col items-center justify-center gap-2 py-8 text-center text-muted-foreground">
            <p className="max-w-[220px] text-[11px] leading-5">
              Ask about portfolio risk, throughput, milestones, blockers, or recovery priorities.
            </p>
          </div>
        )}

        {messages.map((message, index) => (
          <DeliveryMessage
            key={message.id}
            message={message}
            isAnimating={message.role === "agent" && index === animatingMessageIndex}
            onAnimationProgress={scrollToEnd}
            onAnimationComplete={onAnimationComplete}
          />
        ))}

        {asking && (
          <div className="flex gap-3">
            <div className="mt-1 flex h-7 w-7 shrink-0 items-center justify-center rounded-full bg-card text-muted-foreground">
              <Bot className="h-3.5 w-3.5" />
            </div>
            <div className="rounded-md bg-card px-3 py-3 text-xs text-muted-foreground">
              <div className="mb-1 text-[10px] font-semibold uppercase tracking-wider text-muted-foreground">
                Delivery Agent
              </div>
              <TypingIndicator label="Analyzing delivery data" />
            </div>
          </div>
        )}

        <div ref={chatEndRef} aria-hidden="true" />
      </div>

      {suggestions.length > 0 && animatingMessageIndex === null && !asking && (
        <div className="px-4 pb-3">
          <DeliverySuggestions
            suggestions={suggestions}
            label="Follow-up"
            disabled={isInputDisabled}
            onSelect={(prompt) => void sendMessage(prompt)}
          />
        </div>
      )}

      <div className="border-t border-border/70 px-4 py-3">
        <DeliveryChatInput
          value={input}
          disabled={isInputDisabled}
          asking={asking}
          replying={animatingMessageIndex !== null}
          onChange={setInput}
          onSubmit={handleSubmit}
        />
      </div>
    </Card>
  );
}
