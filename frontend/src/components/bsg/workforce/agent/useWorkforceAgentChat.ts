import { useMutation } from "@tanstack/react-query";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { createAgentQuery } from "@/lib/api";
import type { AgentQueryRead } from "@/types/workforce";
import { WORKFORCE_AGENT_NAME, WORKFORCE_CHAT_MAX_MESSAGE_LENGTH } from "./constants";
import { createMessageId, createSession, sessionPreviewTitle } from "./session-utils";
import type { WorkforceChatMessage, WorkforceChatSession } from "./types";

type UseWorkforceAgentChatOptions = {
  projectId: string | null;
};

function upsertSession(
  sessions: WorkforceChatSession[],
  sessionId: string,
  updater: (session: WorkforceChatSession) => WorkforceChatSession,
): WorkforceChatSession[] {
  return sessions.map((session) => (session.id === sessionId ? updater(session) : session));
}

function describeWorkforceChatError(err: unknown): string {
  return err instanceof Error
    ? err.message
    : "The workforce agent could not complete your request.";
}

export function useWorkforceAgentChat({ projectId }: UseWorkforceAgentChatOptions) {
  const [sessions, setSessions] = useState<WorkforceChatSession[]>(() => [
    createSession(projectId),
  ]);
  const [activeSessionId, setActiveSessionId] = useState<string>(() => sessions[0]!.id);
  const [input, setInput] = useState("");
  const [asking, setAsking] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const activeSession = useMemo(
    () => sessions.find((session) => session.id === activeSessionId) ?? sessions[0]!,
    [activeSessionId, sessions],
  );

  const messages = activeSession.messages;

  const historySessions = useMemo(
    () =>
      [...sessions]
        .filter((session) => session.projectId === projectId && session.messages.length > 0)
        .sort((left, right) => right.updatedAt.localeCompare(left.updatedAt)),
    [projectId, sessions],
  );

  useEffect(() => {
    setError(null);
  }, [input, activeSessionId]);

  const previousProjectIdRef = useRef(projectId);
  useEffect(() => {
    if (previousProjectIdRef.current === projectId) return;
    previousProjectIdRef.current = projectId;

    setSessions((current) => {
      const latestForProject = current
        .filter((session) => session.projectId === projectId)
        .sort((left, right) => right.updatedAt.localeCompare(left.updatedAt))[0];

      if (latestForProject) {
        setActiveSessionId(latestForProject.id);
        return current;
      }

      const nextSession = createSession(projectId);
      setActiveSessionId(nextSession.id);
      return [nextSession, ...current];
    });
    setInput("");
    setError(null);
  }, [projectId]);

  const askMutation = useMutation({
    mutationFn: (question: string) =>
      createAgentQuery({
        agent_name: WORKFORCE_AGENT_NAME,
        project_id: projectId,
        query_text: question,
      }),
  });

  const resetConversation = useCallback(() => {
    const emptyForProject = sessions.find(
      (session) => session.projectId === projectId && session.messages.length === 0,
    );
    if (emptyForProject) {
      setActiveSessionId(emptyForProject.id);
      setInput("");
      setError(null);
      return;
    }

    const nextSession = createSession(projectId);
    setSessions((current) => [nextSession, ...current]);
    setActiveSessionId(nextSession.id);
    setInput("");
    setError(null);
  }, [projectId, sessions]);

  const loadSession = useCallback((sessionId: string) => {
    setActiveSessionId(sessionId);
    setInput("");
    setError(null);
  }, []);

  const sendMessage = useCallback(
    async (text: string) => {
      const question = text.trim();
      if (!question || !projectId || asking || askMutation.isPending) return;
      if (question.length > WORKFORCE_CHAT_MAX_MESSAGE_LENGTH) {
        setError(
          `Your message is ${question.length} characters — the limit is ${WORKFORCE_CHAT_MAX_MESSAGE_LENGTH}. Please shorten it and try again.`,
        );
        return;
      }

      const userMessageId = createMessageId();
      setError(null);
      setInput("");
      setAsking(true);

      setSessions((current) =>
        upsertSession(current, activeSessionId, (session) => {
          const nextTitle =
            session.messages.length === 0 ? sessionPreviewTitle(question) : session.title;
          return {
            ...session,
            projectId,
            title: nextTitle,
            messages: [...session.messages, { id: userMessageId, role: "user", text: question }],
            updatedAt: new Date().toISOString(),
          };
        }),
      );

      try {
        const answer: AgentQueryRead = await askMutation.mutateAsync(question);
        const agentMessage: WorkforceChatMessage = {
          id: createMessageId(),
          role: "agent",
          text: answer.answer_text,
          answer,
        };
        setSessions((current) =>
          upsertSession(current, activeSessionId, (session) => ({
            ...session,
            messages: [...session.messages, agentMessage],
            updatedAt: new Date().toISOString(),
          })),
        );
      } catch (err) {
        const message = describeWorkforceChatError(err);
        setError(message);
        setSessions((current) =>
          upsertSession(current, activeSessionId, (session) => ({
            ...session,
            messages: [
              ...session.messages,
              { id: createMessageId(), role: "agent", text: message, error: true },
            ],
            updatedAt: new Date().toISOString(),
          })),
        );
      } finally {
        setAsking(false);
      }
    },
    [activeSessionId, askMutation, asking, projectId],
  );

  const isInputDisabled = asking || !projectId;

  return {
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
  };
}
