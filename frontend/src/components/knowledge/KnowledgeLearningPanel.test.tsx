import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { KnowledgeLearningPanel } from "@/components/knowledge/KnowledgeLearningPanel";

const listSuggestions = vi.fn();
const listGaps = vi.fn();
const getQuality = vi.fn();
const listDuplicates = vi.fn();
const generateSuggestions = vi.fn();
const runEval = vi.fn();

vi.mock("@/lib/api", () => ({
  listKnowledgeSuggestions: (...args: unknown[]) => listSuggestions(...args),
  listKnowledgeGapSuggestions: (...args: unknown[]) => listGaps(...args),
  getKnowledgeRetrievalQuality: (...args: unknown[]) => getQuality(...args),
  listKnowledgeDocumentDuplicates: (...args: unknown[]) => listDuplicates(...args),
  generateKnowledgeSuggestions: (...args: unknown[]) => generateSuggestions(...args),
  applyKnowledgeSuggestion: vi.fn(),
  dismissKnowledgeSuggestion: vi.fn(),
  compareKnowledgeDuplicates: vi.fn(),
  runKnowledgeEvaluation: (...args: unknown[]) => runEval(...args),
}));

vi.mock("sonner", () => ({
  toast: { success: vi.fn(), error: vi.fn(), message: vi.fn() },
}));

function renderPanel() {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return render(
    <QueryClientProvider client={client}>
      <KnowledgeLearningPanel enabled canManage selectedDocumentId="doc-1" />
    </QueryClientProvider>,
  );
}

describe("KnowledgeLearningPanel", () => {
  beforeEach(() => {
    listSuggestions.mockReset();
    listGaps.mockReset();
    getQuality.mockReset();
    listDuplicates.mockReset();
    generateSuggestions.mockReset();
    runEval.mockReset();
    listSuggestions.mockResolvedValue([]);
    listGaps.mockResolvedValue([]);
    getQuality.mockResolvedValue({
      frequently_selected_documents: [],
      frequently_ignored_documents: [],
      weak_citations: [],
      conflicting_answers: [],
      repeated_retrieval_failures: 0,
      low_confidence_trend_count: 0,
      average_confidence: 0.7,
      recommendations: ["Improve ignored guide citations"],
    });
    listDuplicates.mockResolvedValue([]);
  });

  it("loads learning insights without generating on mount", async () => {
    renderPanel();
    await waitFor(() => expect(listSuggestions).toHaveBeenCalled());
    expect(generateSuggestions).not.toHaveBeenCalled();
    expect(runEval).not.toHaveBeenCalled();
    await waitFor(() => {
      expect(screen.getByText(/Improve ignored guide citations/i)).toBeInTheDocument();
    });
  });

  it("generates suggestions on demand", async () => {
    const user = userEvent.setup();
    generateSuggestions.mockResolvedValue([]);
    renderPanel();
    await waitFor(() => expect(listSuggestions).toHaveBeenCalled());
    await user.click(screen.getByRole("button", { name: /Generate suggestions/i }));
    await waitFor(() => expect(generateSuggestions).toHaveBeenCalled());
  });
});
