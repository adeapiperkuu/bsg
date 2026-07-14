import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { GovernanceEscalationSuggestionsSection } from "@/features/governance/GovernanceEscalationSuggestionsSection";

const listMock = vi.fn();
const scanMock = vi.fn();
const dismissMock = vi.fn();
const snoozeMock = vi.fn();

vi.mock("@/lib/queries/governance", async () => {
  const actual = await vi.importActual<typeof import("@/lib/queries/governance")>(
    "@/lib/queries/governance",
  );
  return {
    ...actual,
    listEscalationSuggestions: (...args: unknown[]) => listMock(...args),
    scanEscalationSuggestions: (...args: unknown[]) => scanMock(...args),
    dismissGovernanceAIRecommendation: (...args: unknown[]) => dismissMock(...args),
    snoozeEscalationSuggestion: (...args: unknown[]) => snoozeMock(...args),
    escalationSuggestionsQueryOptions: (params: Record<string, unknown> = {}) => ({
      queryKey: ["governance", "escalation-suggestions", params],
      queryFn: () => listMock(params),
    }),
  };
});

vi.mock("sonner", () => ({
  toast: { success: vi.fn(), error: vi.fn(), message: vi.fn() },
}));

function renderSection() {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  const onConvert = vi.fn();
  render(
    <QueryClientProvider client={client}>
      <GovernanceEscalationSuggestionsSection
        focusProjectId="project-1"
        canWrite
        onConvert={onConvert}
      />
    </QueryClientProvider>,
  );
  return { onConvert };
}

describe("GovernanceEscalationSuggestionsSection", () => {
  beforeEach(() => {
    listMock.mockReset();
    scanMock.mockReset();
    dismissMock.mockReset();
    snoozeMock.mockReset();
    listMock.mockResolvedValue([]);
  });

  it("lists suggestions without scanning on mount", async () => {
    renderSection();
    await waitFor(() => {
      expect(listMock).toHaveBeenCalled();
    });
    expect(scanMock).not.toHaveBeenCalled();
    await waitFor(() => {
      expect(screen.getByText(/No active escalation suggestions/i)).toBeInTheDocument();
    });
  });

  it("runs scan only when button clicked", async () => {
    const user = userEvent.setup();
    scanMock.mockResolvedValue({
      suggestions: [],
      candidates_detected: 0,
      suggestions_created: 0,
      suggestions_reused: 0,
      suggestions_suppressed_existing_escalation: 0,
      projects_scanned: 1,
      duration_ms: 12,
      query_executes: 4,
      llm_enrichment_used: false,
      enabled: true,
    });
    renderSection();
    await waitFor(() => expect(listMock).toHaveBeenCalled());
    await user.click(screen.getByRole("button", { name: /Scan for escalation risks/i }));
    await waitFor(() => expect(scanMock).toHaveBeenCalledTimes(1));
  });

  it("renders suggestion and opens conversion via create escalation", async () => {
    const user = userEvent.setup();
    listMock.mockResolvedValue([
      {
        id: "sug-1",
        scope: "project",
        project_id: "project-1",
        project_name: "Alpha",
        recommendation_type: "escalation_required",
        title: "Escalate overdue blocking dependency",
        narrative: "Dependency has been blocking for 12 days.",
        rationale: "Deterministic trigger",
        priority: "high",
        confidence: 0.9,
        suggested_actions: [
          {
            label: "Create escalation",
            description: "Create high-severity escalation",
            action_type: "consider_escalation",
            target_entity_type: "dependency",
            target_entity_id: "dep-1",
          },
        ],
        evidence: [],
        status: "active",
        generated_at: "2026-07-13T10:00:00Z",
        expires_at: null,
        can_regenerate: false,
        can_dismiss: true,
        can_snooze: true,
        is_ai_generated: false,
        source_type: "rule_based",
        is_stale: false,
        evidence_hash: "hash",
        acceptance_status: "not_accepted",
        accepted_at: null,
        accepted_by_user_id: null,
        converted_action_id: null,
        converted_escalation_id: null,
        accepted_suggested_action_index: null,
        acceptance_note: null,
        auto_detected: true,
        trigger_type: "overdue_blocking_dependency",
        severity_score: 72,
        detected_at: "2026-07-13T10:00:00Z",
      },
    ]);
    const { onConvert } = renderSection();
    await waitFor(() => {
      expect(screen.getByText(/Escalate overdue blocking dependency/i)).toBeInTheDocument();
    });
    await user.click(screen.getByRole("button", { name: /Create escalation/i }));
    expect(onConvert).toHaveBeenCalled();
  });
});
