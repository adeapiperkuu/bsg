import { useMutation } from "@tanstack/react-query";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { ApiError, createAgentQuery } from "@/lib/api";
import type { AgentQueryRead } from "@/types/workforce";
import { WORKFORCE_AGENT_NAME, WORKFORCE_CHAT_MAX_MESSAGE_LENGTH } from "./constants";
import { createMessageId, createSession, sessionPreviewTitle } from "./session-utils";
import type { WorkforceChatMessage, WorkforceChatSession } from "./types";

type UseWorkforceAgentChatOptions = {
  projectId: string | null;
  onAskingChange?: (asking: boolean) => void;
};

function upsertSession(
  sessions: WorkforceChatSession[],
  sessionId: string,
  updater: (session: WorkforceChatSession) => WorkforceChatSession,
): WorkforceChatSession[] {
  return sessions.map((session) => (session.id === sessionId ? updater(session) : session));
}

function describeWorkforceChatError(err: unknown): string {
  if (err instanceof ApiError) {
    if (err.status === 401) {
      return "Your session expired before the Workforce Agent could answer. Sign in again, then retry the question.";
    }
    if (err.status === 403) {
      return "Your account does not have access to the Workforce Agent for this project.";
    }
    if (err.status === 404) {
      return "The selected project is no longer available to your account. Pick another project and try again.";
    }
    if (err.status >= 500) {
      return err.message || "The workforce agent hit a server error. Please try again shortly.";
    }
  }
  return err instanceof Error
    ? err.message
    : "The workforce agent could not complete your request.";
}

function latestSessionForProject(
  sessions: WorkforceChatSession[],
  scopedProjectId: string,
): WorkforceChatSession | undefined {
  return [...sessions]
    .filter((session) => session.projectId === scopedProjectId)
    .sort((left, right) => right.updatedAt.localeCompare(left.updatedAt))[0];
}

function applyProjectScope(
  current: WorkforceChatSession[],
  scopedProjectId: string | null,
): { sessions: WorkforceChatSession[]; activeSessionId: string } {
  if (!scopedProjectId) {
    const fallback = current[0] ?? createSession(null);
    const sessions = current.length > 0 ? current : [fallback];
    return { sessions, activeSessionId: fallback.id };
  }

  const latestForProject = latestSessionForProject(current, scopedProjectId);
  if (latestForProject) {
    return { sessions: current, activeSessionId: latestForProject.id };
  }

  const nextSession = createSession(scopedProjectId);
  return { sessions: [nextSession, ...current], activeSessionId: nextSession.id };
}

/**
 * Resolve a writable session for the current project. Reuses the preferred id when
 * it still exists; otherwise picks the latest project session or creates one.
 */
function resolveWritableSession(
  sessions: WorkforceChatSession[],
  preferredSessionId: string | null,
  scopedProjectId: string,
): { sessions: WorkforceChatSession[]; sessionId: string } {
  const preferred = preferredSessionId
    ? sessions.find((session) => session.id === preferredSessionId)
    : undefined;
  if (preferred && preferred.projectId === scopedProjectId) {
    return { sessions, sessionId: preferred.id };
  }

  const latestForProject = latestSessionForProject(sessions, scopedProjectId);
  if (latestForProject) {
    return { sessions, sessionId: latestForProject.id };
  }

  const nextSession = createSession(scopedProjectId);
  return { sessions: [nextSession, ...sessions], sessionId: nextSession.id };
}

function appendMessageToSession(
  sessions: WorkforceChatSession[],
  sessionId: string,
  scopedProjectId: string,
  message: WorkforceChatMessage,
  titleForFirstMessage?: string,
): { sessions: WorkforceChatSession[]; sessionId: string } {
  const hasSession = sessions.some((session) => session.id === sessionId);
  const resolved = hasSession
    ? { sessions, sessionId }
    : resolveWritableSession(sessions, sessionId, scopedProjectId);

  const now = new Date().toISOString();
  const nextSessions = upsertSession(resolved.sessions, resolved.sessionId, (session) => {
    const isFirstMessage = session.messages.length === 0;
    return {
      ...session,
      projectId: scopedProjectId,
      title: isFirstMessage
        ? (titleForFirstMessage ?? sessionPreviewTitle(message.text))
        : session.title,
      messages: [...session.messages, message],
      updatedAt: now,
    };
  });

  return { sessions: nextSessions, sessionId: resolved.sessionId };
}

export function useWorkforceAgentChat({ projectId, onAskingChange }: UseWorkforceAgentChatOptions) {
  const [sessions, setSessions] = useState<WorkforceChatSession[]>(() => [
    createSession(projectId),
  ]);
  const [activeSessionId, setActiveSessionId] = useState<string>(() => sessions[0]!.id);
  const [input, setInput] = useState("");
  const [asking, setAsking] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const sessionsRef = useRef(sessions);
  const activeSessionIdRef = useRef(activeSessionId);
  const projectIdRef = useRef(projectId);
  const inFlightSessionIdRef = useRef<string | null>(null);
  const pendingProjectIdRef = useRef<string | null>(null);
  const previousProjectIdRef = useRef(projectId);

  const replaceSessions = useCallback((nextSessions: WorkforceChatSession[]) => {
    sessionsRef.current = nextSessions;
    setSessions(nextSessions);
  }, []);

  const syncActiveSessionId = useCallback((sessionId: string) => {
    activeSessionIdRef.current = sessionId;
    setActiveSessionId(sessionId);
  }, []);

  useEffect(() => {
    sessionsRef.current = sessions;
  }, [sessions]);

  useEffect(() => {
    projectIdRef.current = projectId;
  }, [projectId]);

  useEffect(() => {
    activeSessionIdRef.current = activeSessionId;
  }, [activeSessionId]);

  useEffect(() => {
    onAskingChange?.(asking);
  }, [asking, onAskingChange]);

  const activeSession = useMemo(() => {
    const matched = sessions.find((session) => session.id === activeSessionId);
    if (matched) return matched;

    const inFlightSession = inFlightSessionIdRef.current
      ? sessions.find((session) => session.id === inFlightSessionIdRef.current)
      : undefined;
    if (inFlightSession) return inFlightSession;

    if (projectId) {
      const latestForProject = latestSessionForProject(sessions, projectId);
      if (latestForProject) return latestForProject;
    }

    return sessions[0] ?? createSession(projectId);
  }, [activeSessionId, projectId, sessions]);

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

  const switchProjectScope = useCallback(
    (nextProjectId: string | null) => {
      previousProjectIdRef.current = nextProjectId;
      const scoped = applyProjectScope(sessionsRef.current, nextProjectId);
      replaceSessions(scoped.sessions);
      syncActiveSessionId(scoped.activeSessionId);
      setInput("");
      setError(null);
    },
    [replaceSessions, syncActiveSessionId],
  );

  useEffect(() => {
    if (previousProjectIdRef.current === projectId) return;

    if (inFlightSessionIdRef.current) {
      pendingProjectIdRef.current = projectId;
      return;
    }

    switchProjectScope(projectId);
  }, [projectId, switchProjectScope]);

  useEffect(() => {
    if (asking || pendingProjectIdRef.current === null) return;
    if (pendingProjectIdRef.current === previousProjectIdRef.current) {
      pendingProjectIdRef.current = null;
      return;
    }

    const pendingProjectId = pendingProjectIdRef.current;
    pendingProjectIdRef.current = null;
    switchProjectScope(pendingProjectId);
  }, [asking, switchProjectScope]);

  const askMutation = useMutation({
    mutationFn: (question: string) => {
      const scopedProjectId = projectIdRef.current;
      if (!scopedProjectId) {
        return Promise.reject(new Error("Select a project before asking the Workforce Agent."));
      }

      return createAgentQuery({
        agent_name: WORKFORCE_AGENT_NAME,
        project_id: scopedProjectId,
        query_text: question,
      });
    },
  });

  const resetConversation = useCallback(() => {
    if (inFlightSessionIdRef.current) return;

    const currentSessions = sessionsRef.current;
    const emptyForProject = currentSessions.find(
      (session) => session.projectId === projectId && session.messages.length === 0,
    );
    if (emptyForProject) {
      syncActiveSessionId(emptyForProject.id);
      setInput("");
      setError(null);
      return;
    }

    const nextSession = createSession(projectId);
    replaceSessions([nextSession, ...currentSessions]);
    syncActiveSessionId(nextSession.id);
    setInput("");
    setError(null);
  }, [projectId, replaceSessions, syncActiveSessionId]);

  const loadSession = useCallback(
    (sessionId: string) => {
      if (inFlightSessionIdRef.current) return;
      syncActiveSessionId(sessionId);
      setInput("");
      setError(null);
    },
    [syncActiveSessionId],
  );

  const sendMessage = useCallback(
    async (text: string) => {
      const question = text.trim();
      const scopedProjectId = projectIdRef.current;
      // Guard duplicate submits from double-clicks / Enter+click races.
      if (!question || !scopedProjectId || asking || inFlightSessionIdRef.current) return;
      if (question.length > WORKFORCE_CHAT_MAX_MESSAGE_LENGTH) {
        setError(
          `Your message is ${question.length} characters — the limit is ${WORKFORCE_CHAT_MAX_MESSAGE_LENGTH}. Please shorten it and try again.`,
        );
        return;
      }

      const userMessageId = createMessageId();
      const userMessage: WorkforceChatMessage = {
        id: userMessageId,
        role: "user",
        text: question,
      };
      const appendedUser = appendMessageToSession(
        sessionsRef.current,
        activeSessionIdRef.current,
        scopedProjectId,
        userMessage,
        sessionPreviewTitle(question),
      );
      const targetSessionId = appendedUser.sessionId;

      setError(null);
      setInput("");
      setAsking(true);
      replaceSessions(appendedUser.sessions);
      syncActiveSessionId(targetSessionId);
      inFlightSessionIdRef.current = targetSessionId;

      try {
        const answer: AgentQueryRead = await askMutation.mutateAsync(question);
        const agentMessage: WorkforceChatMessage = {
          id: createMessageId(),
          role: "agent",
          text: answer.answer_text,
          answer,
        };
        const capturedSessionId = targetSessionId;
        const appendedAnswer = appendMessageToSession(
          sessionsRef.current,
          capturedSessionId,
          scopedProjectId,
          agentMessage,
        );
        replaceSessions(appendedAnswer.sessions);
      } catch (err) {
        const message = describeWorkforceChatError(err);
        setError(message);
        const capturedSessionId = targetSessionId;
        const agentMessage: WorkforceChatMessage = {
          id: createMessageId(),
          role: "agent",
          text: message,
          error: true,
        };
        const appendedError = appendMessageToSession(
          sessionsRef.current,
          capturedSessionId,
          scopedProjectId,
          agentMessage,
        );
        replaceSessions(appendedError.sessions);
      } finally {
        inFlightSessionIdRef.current = null;
        setAsking(false);
      }
    },
    [askMutation, asking, replaceSessions, syncActiveSessionId],
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
