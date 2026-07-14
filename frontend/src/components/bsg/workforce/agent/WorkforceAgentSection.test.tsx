import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi, afterEach } from "vitest";
import { createAgentQuery } from "@/lib/api";
import type { AgentQueryRead } from "@/types/workforce";
import { WorkforceAgentSection } from "./WorkforceAgentSection";

vi.mock("@/lib/api", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/lib/api")>();
  return {
    ...actual,
    createAgentQuery: vi.fn(),
  };
});

const mockedCreateAgentQuery = vi.mocked(createAgentQuery);

afterEach(() => {
  vi.clearAllMocks();
});

function renderSection(projectId: string | null = "project-1") {
  const queryClient = new QueryClient({
    defaultOptions: {
      queries: { retry: false },
      mutations: { retry: false },
    },
  });

  return render(
    <QueryClientProvider client={queryClient}>
      <WorkforceAgentSection projectId={projectId} canReadInternalWorkforce />
    </QueryClientProvider>,
  );
}

function buildAnswer(queryText: string): AgentQueryRead {
  return {
    id: "answer-1",
    agent_name: "workforce_capability_agent",
    project_id: "project-1",
    query_text: queryText,
    answer_text: `Answer for ${queryText}`,
    model_used: null,
    latency_ms: 8,
    created_at: new Date().toISOString(),
    evidence_links: [],
  };
}

describe("WorkforceAgentSection", () => {
  it("renders the empty state", () => {
    renderSection();

    expect(screen.getByText("Ask Workforce Agent")).toBeInTheDocument();
    expect(
      screen.getByText(
        "Ask about capacity, SME coverage, utilization, skills, training, or capability gaps.",
      ),
    ).toBeInTheDocument();
    expect(screen.getByText("Suggested prompts")).toBeInTheDocument();
  });

  it("submits a question and shows user and agent messages", async () => {
    mockedCreateAgentQuery.mockResolvedValue(buildAnswer("Which teams are overloaded?"));
    const user = userEvent.setup();

    renderSection();

    await user.click(screen.getByRole("button", { name: "Which teams are overloaded?" }));

    await waitFor(() => {
      expect(screen.getByText("Which teams are overloaded?")).toBeInTheDocument();
    });

    await waitFor(() => {
      expect(screen.getByText("Answer for Which teams are overloaded?")).toBeInTheDocument();
    });

    expect(mockedCreateAgentQuery).toHaveBeenCalledTimes(1);
    expect(mockedCreateAgentQuery).toHaveBeenCalledWith({
      agent_name: "workforce_capability_agent",
      project_id: "project-1",
      query_text: "Which teams are overloaded?",
    });
    expect(screen.getByText("You")).toBeInTheDocument();
    expect(screen.getByText("Workforce Agent")).toBeInTheDocument();
  });

  it("shows the user bubble immediately after clicking a starter prompt", async () => {
    let resolveAnswer: ((value: AgentQueryRead) => void) | undefined;
    mockedCreateAgentQuery.mockImplementation(
      () =>
        new Promise<AgentQueryRead>((resolve) => {
          resolveAnswer = resolve;
        }),
    );
    const user = userEvent.setup();

    renderSection();

    await user.click(screen.getByRole("button", { name: "Which teams are overloaded?" }));

    await waitFor(() => {
      expect(screen.getByText("Which teams are overloaded?")).toBeInTheDocument();
      expect(screen.getByText("Analyzing workforce data")).toBeInTheDocument();
    });

    resolveAnswer?.(buildAnswer("Which teams are overloaded?"));

    await waitFor(() => {
      expect(screen.getByText("Answer for Which teams are overloaded?")).toBeInTheDocument();
    });
  });

  it("keeps chat scrolling inside the panel when a question is submitted", async () => {
    mockedCreateAgentQuery.mockResolvedValue(buildAnswer("Which teams are overloaded?"));
    const user = userEvent.setup();
    const scrollToSpy = vi
      .spyOn(HTMLElement.prototype, "scrollTo")
      .mockImplementation(() => undefined);
    if (!HTMLElement.prototype.scrollIntoView) {
      HTMLElement.prototype.scrollIntoView = vi.fn();
    }
    const scrollIntoViewSpy = vi
      .spyOn(HTMLElement.prototype, "scrollIntoView")
      .mockImplementation(() => undefined);

    renderSection();
    scrollToSpy.mockClear();
    scrollIntoViewSpy.mockClear();

    await user.click(screen.getByRole("button", { name: "Which teams are overloaded?" }));

    await waitFor(() => {
      expect(screen.getByText("Answer for Which teams are overloaded?")).toBeInTheDocument();
    });

    expect(scrollToSpy).toHaveBeenCalled();
    expect(scrollIntoViewSpy).not.toHaveBeenCalled();

    scrollToSpy.mockRestore();
    scrollIntoViewSpy.mockRestore();
  });

  it("starts a new chat from the control", async () => {
    mockedCreateAgentQuery.mockResolvedValue(buildAnswer("Which teams are overloaded?"));
    const user = userEvent.setup();

    renderSection();

    await user.click(screen.getByRole("button", { name: "Which teams are overloaded?" }));

    await waitFor(() => {
      expect(screen.getByText("Answer for Which teams are overloaded?")).toBeInTheDocument();
    });

    await user.click(screen.getByRole("button", { name: /New chat/i }));

    expect(
      screen.getByText(
        "Ask about capacity, SME coverage, utilization, skills, training, or capability gaps.",
      ),
    ).toBeInTheDocument();
  });

  it("shows an error when the request fails", async () => {
    mockedCreateAgentQuery.mockRejectedValueOnce(new Error("Agent unavailable"));
    const user = userEvent.setup();

    renderSection();

    await user.click(screen.getByRole("button", { name: "Which teams are overloaded?" }));

    await waitFor(() => {
      expect(screen.getAllByText("Agent unavailable").length).toBeGreaterThan(0);
    });
  });

  it("restores a previous chat from history", async () => {
    mockedCreateAgentQuery
      .mockResolvedValueOnce(buildAnswer("Which teams are overloaded?"))
      .mockResolvedValueOnce(buildAnswer("Do we have enough SME coverage?"));
    const user = userEvent.setup();

    renderSection();

    await user.click(screen.getByRole("button", { name: "Which teams are overloaded?" }));
    await waitFor(() => {
      expect(screen.getByText("Answer for Which teams are overloaded?")).toBeInTheDocument();
    });

    await user.click(screen.getByRole("button", { name: /New chat/i }));
    await user.click(screen.getByRole("button", { name: "Do we have enough SME coverage?" }));
    await waitFor(() => {
      expect(screen.getByText("Answer for Do we have enough SME coverage?")).toBeInTheDocument();
    });

    await user.click(screen.getByRole("button", { name: /^History$/i }));
    await user.click(screen.getByRole("button", { name: /Which teams are overloaded/i }));

    expect(screen.getByText("Answer for Which teams are overloaded?")).toBeInTheDocument();
    expect(
      screen.queryByText("Answer for Do we have enough SME coverage?"),
    ).not.toBeInTheDocument();
  });
});
