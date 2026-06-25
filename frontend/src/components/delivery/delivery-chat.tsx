import { useEffect, useRef } from "react";
import { Bot } from "lucide-react";
import { Card, SectionHeader, AiBadge } from "@/components/bsg/widgets";
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
    sendMessage,
    onAnimationComplete,
    resetConversation,
  } = useDeliveryChat({ projectId });

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
    <Card className="sticky top-20">
      <SectionHeader title="Ask Delivery Agent" sub="Evidence-backed answers" right={<AiBadge />} />

      <div className="mb-3">
        <DeliverySuggestions
          disabled={isInputDisabled}
          onSelect={(prompt) => void sendMessage(prompt)}
        />
      </div>

      <div className="mb-3 max-h-[420px] min-h-[200px] space-y-4 overflow-y-auto rounded-md bg-secondary/35 p-3 text-xs">
        {messages.length === 0 && !asking && (
          <div className="flex flex-col items-center justify-center gap-2 py-8 text-center text-muted-foreground">
            <div className="flex h-10 w-10 items-center justify-center rounded-full bg-card">
              <Bot className="h-5 w-5" />
            </div>
            <p className="text-[11px] leading-5">
              Ask about delivery performance, risks, milestones, throughput, or recovery plans.
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
              <TypingIndicator />
            </div>
          </div>
        )}

        <div ref={chatEndRef} aria-hidden="true" />
      </div>

      <DeliveryChatInput
        value={input}
        disabled={isInputDisabled}
        asking={asking}
        replying={animatingMessageIndex !== null}
        onChange={setInput}
        onSubmit={handleSubmit}
      />
    </Card>
  );
}
