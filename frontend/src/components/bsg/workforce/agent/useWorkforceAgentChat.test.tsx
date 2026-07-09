import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, renderHook, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { createAgentQuery } from "@/lib/api";
import type { AgentQueryRead } from "@/types/workforce";
import { useWorkforceAgentChat } from "./useWorkforceAgentChat";

vi.mock("@/lib/api", () => ({
  createAgentQuery: vi.fn(),
}));

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
});
