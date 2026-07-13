import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, renderHook, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { ApiError, createAgentQuery } from "@/lib/api";
import type { AgentQueryRead } from "@/types/workforce";
import { useWorkforceAgentChat } from "./useWorkforceAgentChat";

vi.mock("@/lib/api", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/lib/api")>();
  return {
    ...actual,
    createAgentQuery: vi.fn(),
  };
});

const mockedCreateAgentQuery = vi.mocked(createAgentQuery);

function createWrapper() {
  const queryClient = new QueryClient({
    defaultOptions: {
      queries: { retry: false },
      mutations: { retry: false },
    },
  });

  return function Wrapper({ children }: { children: ReactNode }) {
    return <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>;
  };
}

function buildAnswer(queryText: string, answerText?: string): AgentQueryRead {
  return {
    id: `answer-${queryText}`,
    agent_name: "workforce_capability_agent",
    project_id: "project-1",
    query_text: queryText,
    answer_text:
      answerText ??
      (queryText.toLowerCase().includes("underload")
        ? "Underloaded teams for Project: 1 team(s) below 60%.\nUnderloaded: Pod B (48%)."
        : "Overloaded teams for Project: 1 team(s) at or above 85%.\nOverloaded: Pod A (108%)."),
    model_used: null,
    latency_ms: 12,
    created_at: new Date().toISOString(),
    evidence_links: [
      {
        id: "evidence-1",
        source_table: "capability_gaps",
        source_row_id: "gap-12345678",
        description: "Open skill shortage gap",
        created_at: null,
      },
    ],
  };
}

afterEach(() => {
  vi.clearAllMocks();
});

describe("useWorkforceAgentChat", () => {
  it("renders submitted question and agent response in the active session", async () => {
    mockedCreateAgentQuery.mockResolvedValue(buildAnswer("Which teams are overloaded?"));

    const { result } = renderHook(() => useWorkforceAgentChat({ projectId: "project-1" }), {
      wrapper: createWrapper(),
    });

    await act(async () => {
      await result.current.sendMessage("Which teams are overloaded?");
    });

    await waitFor(() => {
      expect(result.current.asking).toBe(false);
    });

    const messages = result.current.messages;
    expect(messages).toHaveLength(2);
    expect(messages[0]).toMatchObject({ role: "user", text: "Which teams are overloaded?" });
    expect(messages[1]).toMatchObject({
      role: "agent",
      text: expect.stringContaining("Overloaded teams for"),
    });
    expect(messages[1]?.answer?.evidence_links).toHaveLength(1);
  });

  it("shows the user message immediately before the agent responds", async () => {
    let resolveAnswer: ((value: AgentQueryRead) => void) | undefined;
    mockedCreateAgentQuery.mockImplementation(
      () =>
        new Promise<AgentQueryRead>((resolve) => {
          resolveAnswer = resolve;
        }),
    );

    const { result } = renderHook(() => useWorkforceAgentChat({ projectId: "project-1" }), {
      wrapper: createWrapper(),
    });

    act(() => {
      void result.current.sendMessage("Which teams are overloaded?");
    });

    await waitFor(() => {
      expect(result.current.messages).toHaveLength(1);
      expect(result.current.messages[0]).toMatchObject({
        role: "user",
        text: "Which teams are overloaded?",
      });
      expect(result.current.asking).toBe(true);
    });

    await act(async () => {
      resolveAnswer?.(buildAnswer("Which teams are overloaded?"));
      await Promise.resolve();
    });

    await waitFor(() => {
      expect(result.current.asking).toBe(false);
      expect(result.current.messages).toHaveLength(2);
    });
  });

  it("recovers when activeSessionId is stale and still renders user + agent messages", async () => {
    mockedCreateAgentQuery.mockResolvedValue(
      buildAnswer("Which teams are overloaded?", "Recovered answer"),
    );

    const { result, rerender } = renderHook(
      ({ projectId }) => useWorkforceAgentChat({ projectId }),
      {
        wrapper: createWrapper(),
        initialProps: { projectId: null as string | null },
      },
    );

    const staleSessionId = result.current.activeSessionId;

    rerender({ projectId: "project-1" });

    await act(async () => {
      await result.current.sendMessage("Which teams are overloaded?");
    });

    await waitFor(() => {
      expect(result.current.asking).toBe(false);
    });

    expect(result.current.activeSessionId).not.toBe(staleSessionId);
    expect(result.current.messages).toHaveLength(2);
    expect(result.current.messages[0]).toMatchObject({
      role: "user",
      text: "Which teams are overloaded?",
    });
    expect(result.current.messages[1]).toMatchObject({
      role: "agent",
      text: "Recovered answer",
    });
  });

  it("starts a new chat and clears the active conversation", async () => {
    mockedCreateAgentQuery.mockResolvedValue(
      buildAnswer("First question", "Answer for First question"),
    );

    const { result } = renderHook(() => useWorkforceAgentChat({ projectId: "project-1" }), {
      wrapper: createWrapper(),
    });

    await act(async () => {
      await result.current.sendMessage("First question");
    });

    await waitFor(() => {
      expect(result.current.messages).toHaveLength(2);
    });

    act(() => {
      result.current.resetConversation();
    });

    expect(result.current.messages).toHaveLength(0);
    expect(
      result.current.historySessions.some((session) => session.title === "First question"),
    ).toBe(true);
  });

  it("restores a previous chat when history is selected", async () => {
    mockedCreateAgentQuery
      .mockResolvedValueOnce(buildAnswer("First question", "Answer for First question"))
      .mockResolvedValueOnce(buildAnswer("Second question", "Answer for Second question"));

    const { result } = renderHook(() => useWorkforceAgentChat({ projectId: "project-1" }), {
      wrapper: createWrapper(),
    });

    await act(async () => {
      await result.current.sendMessage("First question");
    });

    const firstSessionId = result.current.activeSessionId;

    act(() => {
      result.current.resetConversation();
    });

    await act(async () => {
      await result.current.sendMessage("Second question");
    });

    act(() => {
      result.current.loadSession(firstSessionId);
    });

    expect(result.current.activeSessionId).toBe(firstSessionId);
    expect(result.current.messages[0]?.text).toBe("First question");
    expect(result.current.messages[1]?.text).toBe("Answer for First question");
  });

  it("keeps distinct answers for consecutive utilization questions", async () => {
    mockedCreateAgentQuery
      .mockResolvedValueOnce(buildAnswer("Which teams are overloaded?"))
      .mockResolvedValueOnce(buildAnswer("which team is underloaded?"));

    const { result } = renderHook(() => useWorkforceAgentChat({ projectId: "project-1" }), {
      wrapper: createWrapper(),
    });

    await act(async () => {
      await result.current.sendMessage("Which teams are overloaded?");
    });

    await act(async () => {
      await result.current.sendMessage("which team is underloaded?");
    });

    await waitFor(() => {
      expect(result.current.messages).toHaveLength(4);
    });

    expect(result.current.messages[1]?.text).toContain("Pod A (108%)");
    expect(result.current.messages[3]?.text).toContain("Pod B (48%)");
    expect(result.current.messages[3]?.text).not.toContain("Pod A (108%)");
  });

  it("surfaces loading and error states", async () => {
    mockedCreateAgentQuery.mockRejectedValueOnce(new Error("Agent unavailable"));

    const { result } = renderHook(() => useWorkforceAgentChat({ projectId: "project-1" }), {
      wrapper: createWrapper(),
    });

    await act(async () => {
      await result.current.sendMessage("Broken request");
    });

    await waitFor(() => {
      expect(result.current.asking).toBe(false);
    });

    expect(result.current.error).toBe("Agent unavailable");
    expect(result.current.messages[1]).toMatchObject({
      role: "agent",
      text: "Agent unavailable",
      error: true,
    });
  });

  it("explains expired sessions instead of leaving the chat in a loading state", async () => {
    mockedCreateAgentQuery.mockRejectedValueOnce(
      new ApiError(401, "AUTH_REQUIRED", "Authentication required."),
    );

    const { result } = renderHook(() => useWorkforceAgentChat({ projectId: "project-1" }), {
      wrapper: createWrapper(),
    });

    await act(async () => {
      await result.current.sendMessage("Which teams are overloaded?");
    });

    await waitFor(() => {
      expect(result.current.asking).toBe(false);
    });

    expect(result.current.error).toMatch(/session expired/i);
    expect(result.current.messages[1]).toMatchObject({
      role: "agent",
      text: expect.stringMatching(/session expired/i),
      error: true,
    });
  });

  it("keeps the answer on the original session when project scope changes mid-flight", async () => {
    let resolveAnswer: ((value: AgentQueryRead) => void) | undefined;
    mockedCreateAgentQuery.mockImplementation(
      () =>
        new Promise<AgentQueryRead>((resolve) => {
          resolveAnswer = resolve;
        }),
    );

    const { result, rerender } = renderHook(
      ({ projectId }) => useWorkforceAgentChat({ projectId }),
      {
        wrapper: createWrapper(),
        initialProps: { projectId: "project-1" },
      },
    );

    act(() => {
      void result.current.sendMessage("Which teams are overloaded?");
    });

    await waitFor(() => {
      expect(result.current.asking).toBe(true);
      expect(result.current.messages).toHaveLength(1);
    });

    const originalSessionId = result.current.activeSessionId;

    rerender({ projectId: "project-2" });

    await act(async () => {
      resolveAnswer?.(buildAnswer("Which teams are overloaded?", "Answer after project switch"));
      await Promise.resolve();
    });

    await waitFor(() => {
      expect(result.current.asking).toBe(false);
    });

    act(() => {
      result.current.loadSession(originalSessionId);
    });

    expect(result.current.messages).toHaveLength(2);
    expect(result.current.messages[1]?.text).toContain("Answer after project switch");
  });

  it("ignores duplicate sends while a request is in flight", async () => {
    let resolveAnswer: ((value: AgentQueryRead) => void) | undefined;
    mockedCreateAgentQuery.mockImplementation(
      () =>
        new Promise<AgentQueryRead>((resolve) => {
          resolveAnswer = resolve;
        }),
    );

    const { result } = renderHook(() => useWorkforceAgentChat({ projectId: "project-1" }), {
      wrapper: createWrapper(),
    });

    act(() => {
      void result.current.sendMessage("Which teams are overloaded?");
      void result.current.sendMessage("Which teams are overloaded?");
    });

    await waitFor(() => {
      expect(result.current.messages.filter((message) => message.role === "user")).toHaveLength(1);
    });

    await act(async () => {
      resolveAnswer?.(buildAnswer("Which teams are overloaded?"));
      await Promise.resolve();
    });

    await waitFor(() => {
      expect(result.current.asking).toBe(false);
    });

    expect(mockedCreateAgentQuery).toHaveBeenCalledTimes(1);
  });
});
