import { useCallback, useEffect, useRef, useState } from "react";
import { ApiError, getDeliveryChatConversation, streamDeliveryChatMessage } from "@/lib/api";
import { sanitizeDeliveryMarkdown } from "@/components/delivery/delivery-markdown";
import { DELIVERY_CHAT_MAX_MESSAGE_LENGTH, generateDeliverySuggestions } from "@/types/delivery-chat";
import type { DeliveryChatMessage, DeliveryChatTurn } from "@/types/delivery-chat";

function createMessageId(): string {
  return crypto.randomUUID();
}

function conversationStorageKey(projectId: string | null | undefined): string {
  return `delivery-chat:conversation:${projectId ?? "__portfolio__"}`;
}

function persistConversationId(projectId: string | null | undefined, conversationId: string): void {
  if (typeof window === "undefined") return;
  window.localStorage.setItem(conversationStorageKey(projectId), conversationId);
}

function clearPersistedConversationId(projectId: string | null | undefined): void {
  if (typeof window === "undefined") return;
  window.localStorage.removeItem(conversationStorageKey(projectId));
}

function turnsToMessages(turns: DeliveryChatTurn[]): DeliveryChatMessage[] {
  return turns.flatMap((turn) => [
    { id: `${turn.id}:q`, role: "user" as const, text: turn.query_text },
    {
      id: `${turn.id}:a`,
      role: "agent" as const,
      text: sanitizeDeliveryMarkdown(turn.answer_text),
      sources: turn.sources,
    },
  ]);
}

/** Distinct, accurate copy per failure category — never the same generic message twice. */
function describeDeliveryChatError(err: unknown): string {
  if (err instanceof ApiError) {
    if (err.code === "RATE_LIMITED") {
      return "You're sending messages too quickly. Please wait a moment and try again.";
    }
    if (err.code === "VALIDATION_ERROR") {
      return "That message couldn't be sent — please check its length and content and try again.";
    }
    if (err.status === 401 || err.status === 403) {
      return "Your session no longer has access to this conversation. Please refresh and sign in again.";
    }
    if (err.status >= 500) {
      return "The delivery agent hit an unexpected server error. Please try again shortly.";
    }
    return err.message;
  }
  if (err instanceof TypeError) {
    // fetch() throws TypeError for network-level failures (offline, DNS, connection refused).
    return "Could not reach the delivery agent — check your connection and try again.";
  }
  return err instanceof Error ? err.message : "The delivery agent could not complete your request.";
}

type UseDeliveryChatOptions = {
  projectId?: string | null;
};

export function useDeliveryChat({ projectId }: UseDeliveryChatOptions = {}) {
  const [messages, setMessages] = useState<DeliveryChatMessage[]>([]);
  const [input, setInput] = useState("");
  const [asking, setAsking] = useState(false);
  const [streamingMessageId, setStreamingMessageId] = useState<string | null>(null);
  const [loadingHistory, setLoadingHistory] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [suggestions, setSuggestions] = useState<string[]>([]);
  const conversationIdRef = useRef<string | null>(null);

  // Clear a stale validation error as soon as the user edits the message.
  useEffect(() => {
    setError(null);
  }, [input]);

  const resetConversation = useCallback(() => {
    conversationIdRef.current = null;
    clearPersistedConversationId(projectId);
    setMessages([]);
    setInput("");
    setError(null);
    setStreamingMessageId(null);
    setSuggestions([]);
  }, [projectId]);

  // On mount / project change: clear the visible thread, then try to restore a
  // previously persisted conversation for this project so a page refresh doesn't
  // lose history that the backend already has durably stored.
  useEffect(() => {
    conversationIdRef.current = null;
    setMessages([]);
    setInput("");
    setError(null);
    setStreamingMessageId(null);
    setSuggestions([]);

    const storedId =
      typeof window !== "undefined" ? window.localStorage.getItem(conversationStorageKey(projectId)) : null;
    if (!storedId) return;

    let cancelled = false;
    setLoadingHistory(true);
    getDeliveryChatConversation(storedId)
      .then((conversation) => {
        if (cancelled) return;
        conversationIdRef.current = conversation.conversation_id;
        setMessages(turnsToMessages(conversation.turns));
      })
      .catch(() => {
        // Stale, unauthorized, or deleted conversation — drop it silently and start fresh.
        clearPersistedConversationId(projectId);
      })
      .finally(() => {
        if (!cancelled) setLoadingHistory(false);
      });

    return () => {
      cancelled = true;
    };
  }, [projectId]);

  const sendMessage = useCallback(
    async (text: string) => {
      const question = text.trim();
      if (!question || asking || streamingMessageId) return;
      if (question.length > DELIVERY_CHAT_MAX_MESSAGE_LENGTH) {
        setError(
          `Your message is ${question.length} characters — the limit is ${DELIVERY_CHAT_MAX_MESSAGE_LENGTH}. Please shorten it and try again.`,
        );
        return;
      }

      setMessages((current) => [
        ...current,
        { id: createMessageId(), role: "user", text: question },
      ]);
      setInput("");
      setAsking(true);
      setError(null);
      setSuggestions([]);

      const agentMessageId = createMessageId();
      let streamStarted = false;

      try {
        for await (const event of streamDeliveryChatMessage({
          message: question,
          project_id: projectId ?? null,
          conversation_id: conversationIdRef.current,
        })) {
          if (event.type === "delta") {
            if (!streamStarted) {
              streamStarted = true;
              setAsking(false);
              setStreamingMessageId(agentMessageId);
              setMessages((current) => [
                ...current,
                { id: agentMessageId, role: "agent", text: event.text, streaming: true },
              ]);
            } else {
              setMessages((current) =>
                current.map((m) =>
                  m.id === agentMessageId ? { ...m, text: m.text + event.text } : m,
                ),
              );
            }
          } else if (event.type === "done") {
            conversationIdRef.current = event.conversation_id;
            persistConversationId(projectId, event.conversation_id);
            const finalText = sanitizeDeliveryMarkdown(event.answer);
            setSuggestions(generateDeliverySuggestions(event.answer));
            setMessages((current) => {
              const hasStreamedMessage = current.some((m) => m.id === agentMessageId);
              if (hasStreamedMessage) {
                return current.map((m) =>
                  m.id === agentMessageId
                    ? { ...m, text: finalText, sources: event.sources, streaming: false }
                    : m,
                );
              }
              // No deltas arrived (e.g. agent not configured, or it failed before any
              // tokens streamed) — the done event carries the only text we have.
              return [
                ...current,
                { id: agentMessageId, role: "agent", text: finalText, sources: event.sources },
              ];
            });
          }
        }
      } catch (err) {
        const message = describeDeliveryChatError(err);
        setMessages((current) => [
          ...current,
          { id: createMessageId(), role: "agent", text: message, error: true },
        ]);
      } finally {
        setAsking(false);
        setStreamingMessageId(null);
      }
    },
    [asking, streamingMessageId, projectId],
  );

  const isInputDisabled = asking || streamingMessageId !== null;

  return {
    messages,
    input,
    setInput,
    asking,
    loadingHistory,
    isStreaming: streamingMessageId !== null,
    isInputDisabled,
    error,
    suggestions,
    sendMessage,
    resetConversation,
  };
}
