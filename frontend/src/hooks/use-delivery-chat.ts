import { useCallback, useRef, useState } from "react";
import { sendDeliveryChatMessage } from "@/lib/api";
import type { DeliveryChatMessage } from "@/types/delivery-chat";

function createMessageId(): string {
  return crypto.randomUUID();
}

type UseDeliveryChatOptions = {
  projectId?: string | null;
};

export function useDeliveryChat({ projectId }: UseDeliveryChatOptions = {}) {
  const [messages, setMessages] = useState<DeliveryChatMessage[]>([]);
  const [input, setInput] = useState("");
  const [asking, setAsking] = useState(false);
  const [animatingMessageIndex, setAnimatingMessageIndex] = useState<number | null>(null);
  const [error, setError] = useState<string | null>(null);
  const conversationIdRef = useRef<string | null>(null);

  const resetConversation = useCallback(() => {
    conversationIdRef.current = null;
    setMessages([]);
    setInput("");
    setError(null);
    setAnimatingMessageIndex(null);
  }, []);

  const sendMessage = useCallback(
    async (text: string) => {
      const question = text.trim();
      if (!question || asking || animatingMessageIndex !== null) return;

      setMessages((current) => [
        ...current,
        { id: createMessageId(), role: "user", text: question },
      ]);
      setInput("");
      setAsking(true);
      setError(null);

      try {
        const response = await sendDeliveryChatMessage({
          message: question,
          project_id: projectId ?? null,
          conversation_id: conversationIdRef.current,
        });
        conversationIdRef.current = response.conversation_id;

        setMessages((current) => {
          const next: DeliveryChatMessage[] = [
            ...current,
            {
              id: createMessageId(),
              role: "agent",
              text: response.answer,
              sources: response.sources,
            },
          ];
          setAnimatingMessageIndex(next.length - 1);
          return next;
        });
      } catch (err) {
        const message =
          err instanceof Error ? err.message : "The delivery agent could not complete your request.";
        setError(message);
        setMessages((current) => {
          const next: DeliveryChatMessage[] = [
            ...current,
            {
              id: createMessageId(),
              role: "agent",
              text: message,
              error: true,
            },
          ];
          setAnimatingMessageIndex(next.length - 1);
          return next;
        });
      } finally {
        setAsking(false);
      }
    },
    [animatingMessageIndex, asking, projectId],
  );

  const onAnimationComplete = useCallback(() => {
    setAnimatingMessageIndex(null);
  }, []);

  const isInputDisabled = asking || animatingMessageIndex !== null;

  return {
    messages,
    input,
    setInput,
    asking,
    animatingMessageIndex,
    error,
    isInputDisabled,
    sendMessage,
    onAnimationComplete,
    resetConversation,
  };
}
