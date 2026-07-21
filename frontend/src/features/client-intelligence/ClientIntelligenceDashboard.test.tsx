import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { ReactNode } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { navForUser } from "@/components/bsg/navigation";
import { ClientIntelligenceDashboard } from "@/features/client-intelligence/ClientIntelligenceDashboard";
import {
  ApiError,
  canAccessPath,
  approveClientIntelligenceCommunication,
  createClientIntelligenceDraft,
  createClientIntelligenceQuery,
  editClientIntelligenceDraft,
  fetchClientMaster,
  fetchClientIntelligenceOverview,
  fetchClientIntelligenceQueryHistory,
  fetchClientIntelligenceSummary,
  fetchDeliveryConfidenceHistory,
  fetchClientIntelligenceReportHistory,
  listClientIntelligenceCommunications,
  listProjects,
  rejectClientIntelligenceCommunication,
  sendClientIntelligenceCommunication,
  submitClientIntelligenceDraftForReview,
  type ProjectRead,
} from "@/lib/api";
import {
  clientIntelligenceDeliveryConfidenceHistoryQueryOptions,
  clientIntelligenceOverviewQueryOptions,
  clientIntelligenceProjectSummaryQueryOptions,
  clientIntelligenceSummaryQueryOptions,
} from "@/lib/queries/client-intelligence";
import { clearClientIntelligenceProjectPrefetchTimers } from "@/lib/queries/client-intelligence-prefetch";
import { queryKeys, STALE_TIME_MS } from "@/lib/queries/keys";
import type { MeUser } from "@/types/auth";
import type {
  ClientCommunicationDraft,
  ClientIntelligenceOverview,
  ClientIntelligenceQueryHistory,
  ClientIntelligenceQueryRead,
  ClientIntelligenceReportHistory,
  ClientIntelligenceReportHistoryItem,
  ClientIntelligenceSummary,
  ClientMasterRow,
  DeliveryConfidenceHistory,
} from "@/types/client-intelligence";
import { useAuthStore } from "@/stores/useAuthStore";

vi.mock("@/lib/api", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/lib/api")>();
  return {
    ...actual,
    listProjects: vi.fn(),
    fetchClientMaster: vi.fn(),
    createClientIntelligenceDraft: vi.fn(),
    createClientIntelligenceQuery: vi.fn(),
    editClientIntelligenceDraft: vi.fn(),
    submitClientIntelligenceDraftForReview: vi.fn(),
    approveClientIntelligenceCommunication: vi.fn(),
    rejectClientIntelligenceCommunication: vi.fn(),
    sendClientIntelligenceCommunication: vi.fn(),
    fetchClientIntelligenceOverview: vi.fn(),
    fetchClientIntelligenceQueryHistory: vi.fn(),
    fetchClientIntelligenceSummary: vi.fn(),
    fetchDeliveryConfidenceHistory: vi.fn(),
    fetchClientIntelligenceReportHistory: vi.fn(),
    listClientIntelligenceCommunications: vi.fn(),
  };
});

const mockedListProjects = vi.mocked(listProjects);
const mockedFetchMaster = vi.mocked(fetchClientMaster);
const mockedCreateDraft = vi.mocked(createClientIntelligenceDraft);
const mockedCreateQuery = vi.mocked(createClientIntelligenceQuery);
const mockedEditDraft = vi.mocked(editClientIntelligenceDraft);
const mockedSubmitForReview = vi.mocked(submitClientIntelligenceDraftForReview);
const mockedApproveCommunication = vi.mocked(approveClientIntelligenceCommunication);
const mockedRejectCommunication = vi.mocked(rejectClientIntelligenceCommunication);
const mockedSendCommunication = vi.mocked(sendClientIntelligenceCommunication);
const mockedFetchOverview = vi.mocked(fetchClientIntelligenceOverview);
const mockedFetchSummary = vi.mocked(fetchClientIntelligenceSummary);
const mockedFetchConfidenceHistory = vi.mocked(fetchDeliveryConfidenceHistory);
const mockedFetchReportHistory = vi.mocked(fetchClientIntelligenceReportHistory);
const mockedFetchQueryHistory = vi.mocked(fetchClientIntelligenceQueryHistory);
const mockedListCommunications = vi.mocked(listClientIntelligenceCommunications);

const projects: ProjectRead[] = [
  {
    id: "11111111-1111-1111-1111-111111111111",
    org_id: "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
    name: "Atlas Delivery",
    description: null,
    vertical: "Data Operations",
    status: "active",
    start_date: "2026-01-01",
    target_end_date: "2026-12-31",
    actual_end_date: null,
    daily_target_units: null,
    created_at: "2026-01-01T00:00:00Z",
    updated_at: "2026-07-15T00:00:00Z",
  },
  {
    id: "22222222-2222-2222-2222-222222222222",
    org_id: "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
    name: "Borealis Review",
    description: null,
    vertical: "Quality",
    status: "ramping",
    start_date: "2026-02-01",
    target_end_date: "2027-01-31",
    actual_end_date: null,
    daily_target_units: null,
    created_at: "2026-02-01T00:00:00Z",
    updated_at: "2026-07-15T00:00:00Z",
  },
];

const masterRows: ClientMasterRow[] = projects.map((project, index) => ({
  project_id: project.id,
  project_name: project.name,
  project_count: 1,
  health_status: null,
  health_availability: "not_assessed",
  confidence_score_pct: index === 0 ? "92.00" : "74.00",
  last_report_at: index === 0 ? "2026-07-17T08:00:00Z" : "2026-07-16T08:00:00Z",
  next_milestone_date: index === 0 ? "2026-07-24" : "2026-07-25",
  csat_average: index === 0 ? "5.0" : "4.0",
  csat_sample_size: 2,
  draft_count: index === 0 ? 1 : 0,
}));

const historyFor = (
  project: ProjectRead,
  overrides: Partial<DeliveryConfidenceHistory> = {},
): DeliveryConfidenceHistory => {
  const points =
    overrides.points ??
    ([
      {
        source_row_id: "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaa0001",
        project_id: project.id,
        milestone_id: "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaa0002",
        score_pct: "80.00",
        confidence_status: "on_track",
        observed_at: "2026-07-10T12:00:00Z",
      },
      {
        source_row_id: "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaa0003",
        project_id: project.id,
        milestone_id: "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaa0004",
        score_pct: "87.50",
        confidence_status: "on_track",
        observed_at: "2026-07-15T12:00:00Z",
      },
    ] as DeliveryConfidenceHistory["points"]);
  const latestId = points.length > 0 ? points[points.length - 1].source_row_id : null;
  return {
    project_id: project.id,
    availability: "available",
    points,
    returned_point_count: points.length,
    total_valid_point_count: points.length,
    limitations: [],
    current_score_availability: points.length > 0 ? "available" : "missing",
    current_source_row_id: latestId,
    latest_history_point_is_current: points.length > 0,
    ...overrides,
  };
};

const fingerprint = "a".repeat(64);
const reportingPeriod = {
  start_date: "2026-07-06",
  end_date: "2026-07-12",
  previous_start_date: "2026-06-29",
  previous_end_date: "2026-07-05",
  as_of: "2026-07-15",
};

const emptySummary = (): ClientIntelligenceSummary => ({
  delivery_confidence: {
    availability: "no_data",
    average_score_pct: null,
    covered_project_count: 0,
    eligible_project_count: 2,
    limitations: [],
  },
  reports: {
    availability: "no_data",
    drafted_count: 0,
    approved_count: 0,
    eligible_record_count: 0,
    limitations: [],
  },
  query_response: {
    availability: "no_data",
    average_latency_ms: null,
    sample_size: 0,
    limitations: [],
  },
  csat: {
    availability: "no_data",
    average_score: null,
    sample_size: 0,
    scale_max: 5,
    limitations: [],
  },
  authorized_project_count: 2,
});

const populatedSummary = (): ClientIntelligenceSummary => ({
  delivery_confidence: {
    availability: "available",
    average_score_pct: "87.50",
    covered_project_count: 2,
    eligible_project_count: 2,
    limitations: [],
  },
  reports: {
    availability: "available",
    drafted_count: 2,
    approved_count: 5,
    eligible_record_count: 7,
    limitations: [],
  },
  query_response: {
    availability: "available",
    average_latency_ms: 850,
    sample_size: 4,
    limitations: [],
  },
  csat: {
    availability: "available",
    average_score: "4.5",
    sample_size: 8,
    scale_max: 5,
    limitations: [],
  },
  authorized_project_count: 2,
});

const selectedProjectSummary = (): ClientIntelligenceSummary => ({
  delivery_confidence: {
    availability: "available",
    average_score_pct: "73.25",
    covered_project_count: 1,
    eligible_project_count: 1,
    limitations: [],
  },
  reports: {
    availability: "available",
    drafted_count: 1,
    approved_count: 2,
    eligible_record_count: 3,
    limitations: [],
  },
  query_response: {
    availability: "available",
    average_latency_ms: 5000,
    sample_size: 2,
    limitations: [],
  },
  csat: {
    availability: "available",
    average_score: "3.8",
    sample_size: 2,
    scale_max: 5,
    limitations: [],
  },
  authorized_project_count: 1,
});

function overviewFor(
  project: ProjectRead,
  overrides: Partial<ClientIntelligenceOverview> = {},
): ClientIntelligenceOverview {
  return {
    project: {
      project_id: project.id,
      org_id: project.org_id,
      project_name: project.name,
      project_status: project.status,
    },
    reporting_period: reportingPeriod,
    as_of: "2026-07-15",
    generated_at: "2026-07-15T08:30:00Z",
    visibility_mode: "internal",
    source_fingerprint: fingerprint,
    overall_data_quality: "partial",
    data_quality: [
      {
        source: "throughput_snapshots",
        state: "partial",
        detail: "Forecast coverage is incomplete.",
        observed_at: "2026-07-15T00:00:00Z",
      },
    ],
    source_limitations: ["Historical delivery confidence is unavailable."],
    visibility_limitations: [
      {
        source: "operational_knowledge",
        reason: "SOURCE_NOT_VISIBLE",
        detail: "Knowledge evidence was not visible in this projection.",
      },
    ],
    project_health: {
      org_id: project.org_id,
      project_id: project.id,
      reporting_period: reportingPeriod,
      visibility_mode: "internal",
      status: "insufficient",
      rules_version: null,
      source_fingerprint: fingerprint,
      policy_fingerprint: null,
      overall_data_quality: "partial",
      signals: [],
      positive_drivers: [],
      negative_drivers: [],
      limitations: ["PROJECT_HEALTH_POLICY_UNAVAILABLE"],
      evidence: [],
      history: {
        previous_status: null,
        current_status: "insufficient",
        trend: "unknown",
        previous_reporting_period: null,
        added_driver_keys: [],
        removed_driver_keys: [],
        changed_driver_keys: [],
        limitation: "PREVIOUS_ASSESSMENT_UNAVAILABLE",
      },
      assessed_at: "2026-07-15T08:30:00Z",
    },
    delivery_confidence: {
      org_id: project.org_id,
      project_id: project.id,
      reporting_period: reportingPeriod,
      visibility_mode: "internal",
      availability: "partial",
      score_pct: "87.50",
      confidence_band: "on_track",
      confidence_band_is_delivery_owned_status: true,
      current_milestone: {
        milestone_id: "33333333-3333-3333-3333-333333333333",
        name: "Governed milestone",
        status: "in_progress",
        planned_date: "2026-07-30",
        actual_date: null,
        evidence: [],
      },
      forecast_completion_date: "2026-08-15",
      observed_at: "2026-07-15T00:00:00Z",
      source_data_quality: "partial",
      trend: "unknown",
      previous_score_pct: null,
      positive_drivers: [],
      negative_drivers: [],
      mitigation_contribution: "unavailable",
      limitations: ["EXPLANATION_POLICY_UNAVAILABLE"],
      source_limitations: ["Previous confidence snapshot is unavailable."],
      evidence: [],
      source_fingerprint: fingerprint,
      previous_source_fingerprint: null,
      rules_version: null,
      assessed_at: "2026-07-15T08:30:00Z",
    },
    risk_transparency: {
      org_id: project.org_id,
      project_id: project.id,
      as_of: "2026-07-15",
      visibility_mode: "internal",
      availability: "unavailable",
      risk_items: [],
      evidence: [],
      limitations: [
        "RISK_POLICY_UNAVAILABLE",
        "CLIENT_VISIBILITY_POLICY_UNAVAILABLE",
        "BUSINESS_IMPACT_POLICY_UNRESOLVED",
        "MITIGATION_EVIDENCE_UNAVAILABLE",
      ],
      source_limitations: ["Risk history is unavailable."],
      source_fingerprint: fingerprint,
      rules_version: null,
      assessed_at: "2026-07-15T08:30:00Z",
    },
    delivery_trend: {
      org_id: project.org_id,
      project_id: project.id,
      as_of: "2026-07-15",
      covered_start_date: "2026-07-06",
      covered_end_date: "2026-07-15",
      grain: "day",
      timezone: "utc",
      visibility_mode: "internal",
      availability: "partial",
      trend_points: [
        {
          snapshot_date: "2026-07-14",
          source_row_id: "44444444-4444-4444-4444-444444444444",
          source_agent: "delivery_performance",
          source_table: "throughput_snapshots",
          actual_units: 42,
          actual_state: "observed",
          plan_units: null,
          plan_state: "missing_source",
          forecast_units: null,
          forecast_state: "missing_source",
          delta_actual_forecast: null,
          delta_actual_plan: null,
          data_quality: "partial",
          visibility: "internal",
          source_fingerprint: fingerprint,
          evidence: [],
          limitations: ["PLAN_SERIES_UNAVAILABLE", "FORECAST_VALUE_MISSING"],
        },
      ],
      deviations: [],
      evidence: [],
      limitations: ["PLAN_SERIES_UNAVAILABLE", "DEVIATION_POLICY_UNAVAILABLE"],
      source_limitations: ["Earlier throughput snapshots are unavailable."],
      source_fingerprint: fingerprint,
      rules_version: null,
      assessed_at: "2026-07-15T08:30:00Z",
    },
    ...overrides,
  };
}

function deferred<T>() {
  let resolve!: (value: T) => void;
  let reject!: (reason: unknown) => void;
  const promise = new Promise<T>((res, rej) => {
    resolve = res;
    reject = rej;
  });
  return { promise, resolve, reject };
}

function communicationFixture(
  overrides: Partial<ClientCommunicationDraft> = {},
): ClientCommunicationDraft {
  return {
    id: "55555555-5555-4555-8555-555555555555",
    project_id: projects[0].id,
    comm_type: "weekly_summary",
    subject: "Weekly Client Update",
    body_draft: "Evidence-backed delivery update.",
    body_approved: null,
    status: "draft",
    drafted_by_agent: "client_interaction_agent",
    reviewed_by: null,
    reviewed_at: null,
    approved_by: null,
    approved_at: null,
    sent_at: null,
    rejection_reason: null,
    rejected_by: null,
    rejected_at: null,
    created_at: "2026-07-16T12:00:00Z",
    updated_at: "2026-07-16T12:00:00Z",
    evidence_links: [
      {
        id: "66666666-6666-4666-8666-666666666666",
        source_table: "throughput_snapshots",
        source_row_id: "77777777-7777-4777-8777-777777777777",
        description: "Latest governed throughput snapshot.",
        created_at: "2026-07-16T12:00:00Z",
      },
    ],
    ...overrides,
  };
}

function historyItemFixture(
  overrides: Partial<ClientIntelligenceReportHistoryItem> = {},
): ClientIntelligenceReportHistoryItem {
  return {
    communication_id: "55555555-5555-4555-8555-555555555555",
    project_id: projects[0].id,
    report_type: "weekly_summary",
    subject: "History Weekly Update",
    approved_body: "Final approved narrative.",
    status: "approved",
    reviewed_by: "99999999-9999-9999-9999-999999999999",
    reviewed_at: "2026-07-16T12:00:00Z",
    approved_by: "99999999-9999-9999-9999-999999999999",
    approved_at: "2026-07-16T13:00:00Z",
    sent_at: null,
    history_at: "2026-07-16T13:00:00Z",
    provenance_availability: "complete",
    limitations: [],
    evidence_links: [
      {
        id: "66666666-6666-4666-8666-666666666666",
        source_table: "throughput_snapshots",
        source_row_id: "77777777-7777-4777-8777-777777777777",
        description: "History evidence link.",
        created_at: "2026-07-16T12:00:00Z",
      },
    ],
    created_at: "2026-07-16T12:00:00Z",
    updated_at: "2026-07-16T13:00:00Z",
    ...overrides,
  };
}

function historyPage(
  items: ClientIntelligenceReportHistoryItem[],
  overrides: Partial<ClientIntelligenceReportHistory> = {},
): ClientIntelligenceReportHistory {
  return {
    project_id: projects[0].id,
    items,
    limit: 20,
    offset: 0,
    total: items.length,
    has_more: false,
    status_filter: null,
    ...overrides,
  };
}

function queryItemFixture(
  overrides: Partial<ClientIntelligenceQueryRead> = {},
): ClientIntelligenceQueryRead {
  return {
    query_id: "88888888-8888-4888-8888-888888888888",
    project_id: projects[0].id,
    question: "What is the current delivery confidence?",
    answer_text: "Delivery confidence is 87.50% based on the latest governed snapshot.",
    answer_availability: "answered",
    confidence_level: "high",
    limitations: [],
    next_step: null,
    escalation_required: false,
    source_agents: ["delivery_performance"],
    evidence_links: [
      {
        id: "66666666-6666-4666-8666-666666666666",
        source_table: "delivery_confidence_scores",
        source_row_id: "77777777-7777-4777-8777-777777777777",
        description: "Latest governed confidence score.",
        created_at: "2026-07-16T12:00:00Z",
      },
    ],
    as_of: "2026-07-15",
    reporting_period_start: "2026-07-06",
    reporting_period_end: "2026-07-12",
    model_used: "gpt-test",
    latency_ms: 850,
    created_at: "2026-07-16T12:00:00Z",
    category: "delivery_confidence",
    insufficient_evidence: false,
    ...overrides,
  };
}

function queryHistoryPage(
  items: ClientIntelligenceQueryRead[],
  overrides: Partial<ClientIntelligenceQueryHistory> = {},
): ClientIntelligenceQueryHistory {
  return {
    project_id: projects[0].id,
    items,
    limit: 20,
    offset: 0,
    total: items.length,
    has_more: false,
    ...overrides,
  };
}

async function openQueueItem(user: ReturnType<typeof userEvent.setup>, subject: string) {
  const table = await screen.findByRole("table", { name: "Authorized client projects" });
  const atlasRow = within(table).getByText("Atlas Delivery").closest("tr")!;
  await user.click(within(atlasRow).getByRole("button", { name: "View Atlas Delivery" }));
  const queueHeading = await screen.findByText("Draft Reports Queue");
  const queueSection = queueHeading.closest("section");
  expect(queueSection).not.toBeNull();
  await user.click(within(queueSection!).getByText(subject));
}

function renderDashboard() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false, gcTime: 0 } },
  });
  return {
    queryClient,
    ...render(
      <QueryClientProvider client={queryClient}>
        <ClientIntelligenceDashboard />
      </QueryClientProvider>,
    ),
  };
}

async function selectProject(projectName = "Atlas Delivery") {
  const user = userEvent.setup();
  const table = await screen.findByRole("table", { name: "Authorized client projects" });
  await user.click(within(table).getByText(projectName));
  return table;
}

function userFor(role: MeUser["role"]): MeUser {
  return {
    id: "99999999-9999-9999-9999-999999999999",
    org_id: "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
    email: `${role}@example.com`,
    full_name: role,
    role,
    is_active: true,
  };
}

beforeEach(() => {
  useAuthStore.getState().setUser(userFor("delivery_manager"));
  mockedListProjects.mockResolvedValue(projects);
  mockedFetchMaster.mockResolvedValue(masterRows);
  mockedCreateDraft.mockResolvedValue({
    id: "55555555-5555-4555-8555-555555555555",
    project_id: projects[0].id,
    comm_type: "weekly_summary",
    subject: "Weekly Client Update · 2026-07-16",
    body_draft: "Evidence-backed delivery update.",
    body_approved: null,
    status: "draft",
    drafted_by_agent: "client_interaction_agent",
    reviewed_by: null,
    reviewed_at: null,
    approved_by: null,
    approved_at: null,
    sent_at: null,
    rejection_reason: null,
    rejected_by: null,
    rejected_at: null,
    created_at: "2026-07-16T12:00:00Z",
    updated_at: "2026-07-16T12:00:00Z",
    evidence_links: [],
  } satisfies ClientCommunicationDraft);
  mockedListCommunications.mockResolvedValue([]);
  mockedFetchReportHistory.mockResolvedValue({
    project_id: projects[0].id,
    items: [],
    limit: 20,
    offset: 0,
    total: 0,
    has_more: false,
    status_filter: null,
  } satisfies ClientIntelligenceReportHistory);
  mockedFetchSummary.mockResolvedValue(emptySummary());
  mockedFetchQueryHistory.mockResolvedValue(queryHistoryPage([]));
  mockedFetchConfidenceHistory.mockImplementation(async (projectId) => {
    const project = projects.find((item) => item.id === projectId);
    if (!project) throw new ApiError(404, "PROJECT_NOT_FOUND", "Project not found.");
    return historyFor(project);
  });
  mockedFetchOverview.mockImplementation(async (projectId) => {
    const project = projects.find((item) => item.id === projectId);
    if (!project) throw new ApiError(404, "PROJECT_NOT_FOUND", "Project not found.");
    return overviewFor(project);
  });
});

afterEach(() => {
  clearClientIntelligenceProjectPrefetchTimers();
  useAuthStore.getState().setUser(null);
  vi.clearAllMocks();
});

describe("ClientIntelligenceDashboard", () => {
  it("preserves the original four-card layout and three/two-column main split", async () => {
    renderDashboard();

    const summary = screen.getByTestId("client-intelligence-summary-grid");
    expect(summary).toHaveClass("grid-cols-2", "gap-4", "lg:grid-cols-4");
    expect(summary.children).toHaveLength(4);
    expect(within(summary).getByText("Delivery Confidence")).toBeInTheDocument();
    expect(within(summary).getByText("Reports Drafted vs Approved")).toBeInTheDocument();
    expect(within(summary).getByText("Avg Query Response")).toBeInTheDocument();
    expect(within(summary).getByText("Avg CSAT")).toBeInTheDocument();
    expect(
      (await within(summary).findAllByText(/No data|No responses/)).length,
    ).toBeGreaterThanOrEqual(7);
    expect(within(summary).getByText("No score")).toBeInTheDocument();
    expect(within(summary).getByText("No data · 0 of 2 projects")).toBeInTheDocument();

    const main = screen.getByTestId("client-intelligence-main-grid");
    expect(main).toHaveClass("grid-cols-1", "gap-5", "lg:grid-cols-5");
    expect(main.children[0]).toHaveClass("lg:col-span-3");
    expect(main.children[1]).toHaveClass("lg:col-span-2");
  });

  it("restores the historical KPI card presentation without custom card shells", async () => {
    mockedFetchSummary.mockResolvedValueOnce({
      ...populatedSummary(),
      reports: {
        availability: "available",
        drafted_count: 12,
        approved_count: 9,
        eligible_record_count: 12,
        limitations: [],
      },
      query_response: {
        availability: "available",
        average_latency_ms: 12_240_000,
        sample_size: 6,
        limitations: [],
      },
    });
    renderDashboard();

    const summary = screen.getByTestId("client-intelligence-summary-grid");
    expect(summary).toHaveClass("grid-cols-2", "gap-4", "lg:grid-cols-4");
    expect(summary.children).toHaveLength(4);

    const cards = Array.from(summary.children) as HTMLElement[];
    for (const card of cards) {
      expect(card.className).toMatch(/rounded-lg/);
      expect(card.className).toMatch(/\bp-5\b/);
      expect(card.className).not.toMatch(/min-h-\[148px\]/);
      expect(card.className).not.toMatch(/\bh-\[/);
      expect(card.className).not.toMatch(/\bh-full\b/);
      expect(card.className).not.toMatch(/flex-col/);
      expect(card.className).not.toMatch(/min-h-/);
    }

    const deliveryCard = within(summary).getByText("Delivery Confidence").parentElement!;
    const reportsCard = within(summary).getByText("Reports Drafted vs Approved").parentElement!;
    const queryCard = within(summary).getByText("Avg Query Response").parentElement!;
    const csatCard = within(summary).getByText("Avg CSAT").parentElement!;

    expect(within(summary).getByText("Delivery Confidence")).toHaveClass(
      "text-xs",
      "uppercase",
      "tracking-wider",
      "text-muted-foreground",
    );
    expect(within(summary).getByText("Delivery Confidence").className).not.toMatch(/font-medium/);
    expect(await within(deliveryCard).findByText("87.50%")).toHaveClass(
      "text-2xl",
      "font-semibold",
    );
    const deliveryRow = within(deliveryCard).getByText("87.50%").parentElement!;
    expect(deliveryRow).toHaveClass("mt-2", "flex", "items-center", "justify-between");
    expect(deliveryRow.className).not.toMatch(/\bgap-4\b/);
    const sparkline = await within(deliveryCard).findByRole("img", { name: /2 points/ });
    expect(sparkline).toHaveClass("h-6", "w-[76px]");
    expect(sparkline.querySelector("polyline")).not.toBeNull();

    expect(within(summary).getByText("Reports Drafted vs Approved")).toHaveClass(
      "text-xs",
      "uppercase",
      "tracking-wider",
      "text-muted-foreground",
    );
    expect(within(summary).getByText("Reports Drafted vs Approved").className).not.toMatch(
      /font-medium/,
    );
    expect(await within(reportsCard).findByText("12 drafted · 9 approved")).toHaveClass(
      "mt-2",
      "text-sm",
    );
    const progressTrack = within(reportsCard).getByLabelText(
      /Reports Drafted vs Approved availability/,
    );
    expect(progressTrack).toHaveClass("mt-2", "h-2", "overflow-hidden", "rounded", "bg-elevated");
    expect(progressTrack.className).not.toMatch(/rounded-full/);
    expect(progressTrack.firstElementChild).toHaveStyle({ width: "75%" });
    expect(progressTrack.firstElementChild).toHaveClass("h-full", "bg-[color:var(--brand)]");

    expect(within(summary).getByText("Avg Query Response")).toHaveClass(
      "text-xs",
      "font-medium",
      "uppercase",
      "tracking-wider",
      "text-muted-foreground",
    );
    expect(await within(queryCard).findByText("3.4 h")).toHaveClass(
      "mt-2",
      "text-2xl",
      "font-semibold",
      "text-foreground",
    );
    expect(within(queryCard).getByText("6 responses")).toHaveClass(
      "mt-1",
      "text-xs",
      "font-medium",
      "text-[color:var(--success)]",
    );

    expect(within(summary).getByText("Avg CSAT")).toHaveClass(
      "text-xs",
      "uppercase",
      "tracking-wider",
      "text-muted-foreground",
    );
    expect(within(summary).getByText("Avg CSAT").className).not.toMatch(/font-medium/);
    const stars = within(csatCard).getByLabelText(/average CSAT/);
    expect(stars).toHaveClass("mt-2", "flex", "gap-0.5");
    const starIcons = stars.querySelectorAll("svg");
    expect(starIcons).toHaveLength(5);
    for (const star of Array.from(starIcons)) {
      expect(star).toHaveClass("h-5", "w-5");
      expect(star.getAttribute("class") ?? "").not.toMatch(/\bh-6\b/);
    }
    expect(starIcons[0]).toHaveClass("fill-[color:var(--warning)]", "text-[color:var(--warning)]");
    expect(starIcons[3]).toHaveClass("fill-[color:var(--warning)]", "text-[color:var(--warning)]");
    expect(starIcons[4]).toHaveClass("text-muted-foreground/40");
    expect(starIcons[4].getAttribute("class") ?? "").not.toMatch(/fill-\[color:var\(--warning\)\]/);
    expect(within(csatCard).getByText("4.5 / 5 across 8 responses")).toHaveClass(
      "mt-1",
      "text-[11px]",
      "text-muted-foreground",
    );
  });

  it("clamps report approval percentage and keeps zero-drafted bars empty", async () => {
    mockedFetchSummary
      .mockResolvedValueOnce({
        ...populatedSummary(),
        reports: {
          availability: "available",
          drafted_count: 2,
          approved_count: 5,
          eligible_record_count: 5,
          limitations: [],
        },
      })
      .mockResolvedValueOnce({
        ...emptySummary(),
        reports: {
          availability: "available",
          drafted_count: 0,
          approved_count: 0,
          eligible_record_count: 0,
          limitations: [],
        },
      });

    const { unmount } = renderDashboard();
    const summary = screen.getByTestId("client-intelligence-summary-grid");
    const reportsCard = within(summary).getByText("Reports Drafted vs Approved").parentElement!;
    expect(await within(reportsCard).findByText("2 drafted · 5 approved")).toBeInTheDocument();
    expect(
      within(reportsCard).getByLabelText(/Reports Drafted vs Approved availability/)
        .firstElementChild,
    ).toHaveStyle({ width: "100%" });
    unmount();

    renderDashboard();
    const emptySummaryGrid = screen.getByTestId("client-intelligence-summary-grid");
    const emptyReportsCard = within(emptySummaryGrid).getByText(
      "Reports Drafted vs Approved",
    ).parentElement!;
    expect(await within(emptyReportsCard).findByText("0 drafted · 0 approved")).toBeInTheDocument();
    expect(
      within(emptyReportsCard).getByLabelText(/Reports Drafted vs Approved availability/)
        .firstElementChild,
    ).toHaveStyle({ width: "0%" });
  });

  it("keeps query no-data secondary muted and CSAT outline stars when empty", async () => {
    renderDashboard();

    const summary = screen.getByTestId("client-intelligence-summary-grid");
    const queryCard = within(summary).getByText("Avg Query Response").parentElement!;
    const csatCard = within(summary).getByText("Avg CSAT").parentElement!;

    expect(await within(queryCard).findByText("No data")).toBeInTheDocument();
    const querySecondary = within(queryCard).getByLabelText(/Avg Query Response availability/);
    expect(querySecondary).toHaveClass("text-muted-foreground");
    expect(querySecondary.className).not.toMatch(/--success/);
    expect(querySecondary).toBeEmptyDOMElement();

    const stars = within(csatCard).getByLabelText(/average CSAT/);
    expect(stars.querySelectorAll("svg")).toHaveLength(5);
    for (const star of Array.from(stars.querySelectorAll("svg"))) {
      expect(star).toHaveClass("h-5", "w-5", "text-muted-foreground/40");
      expect(star.getAttribute("class") ?? "").not.toMatch(/fill-\[color:var\(--warning\)\]/);
    }
    expect(within(csatCard).getByText("No responses")).toHaveClass(
      "mt-1",
      "text-[11px]",
      "text-muted-foreground",
    );
  });

  it("requests summary without selecting a project and does not request overview", async () => {
    renderDashboard();

    await waitFor(() => expect(mockedFetchSummary).toHaveBeenCalledTimes(1));
    expect(mockedFetchOverview).not.toHaveBeenCalled();
    expect(
      screen.getByText("Select a project row to view governed Client Intelligence."),
    ).toBeInTheDocument();
    const table = await screen.findByRole("table", { name: "Authorized client projects" });
    expect(within(table).getByText("Atlas Delivery").closest("tr")).toHaveAttribute(
      "aria-selected",
      "false",
    );
  });

  it("renders authorized projects with no initial selection or overview request", async () => {
    renderDashboard();

    const table = await screen.findByRole("table", { name: "Authorized client projects" });
    expect(within(table).getByText("Atlas Delivery")).toBeInTheDocument();
    expect(within(table).getByText("Borealis Review")).toBeInTheDocument();
    expect(mockedFetchOverview).not.toHaveBeenCalled();
    await waitFor(() =>
      expect(mockedFetchConfidenceHistory).toHaveBeenCalledWith(projects[0].id),
    );
    expect(within(table).getByText("Atlas Delivery").closest("tr")).toHaveAttribute(
      "aria-selected",
      "false",
    );
    expect(within(table).getByText("Borealis Review").closest("tr")).toHaveAttribute(
      "aria-selected",
      "false",
    );
    expect(
      screen.getByText("Select a project row to view governed Client Intelligence."),
    ).toBeInTheDocument();
    expect(await screen.findByRole("img", { name: /2 points/ })).toBeInTheDocument();
    expect(screen.queryByText("2,17 15,13 27,16 40,10 53,12 65,7 74,8")).not.toBeInTheDocument();
    const summary = screen.getByTestId("client-intelligence-summary-grid");
    expect(within(summary).getByText("No score")).toBeInTheDocument();
    expect(within(summary).getByText("No data · 0 of 2 projects")).toBeInTheDocument();
    expect(within(summary).queryByText("Not loaded")).not.toBeInTheDocument();
  });

  it("renders live Client Master metrics without requesting every project overview", async () => {
    renderDashboard();

    const table = await screen.findByRole("table", { name: "Authorized client projects" });
    const atlasRow = within(table).getByText("Atlas Delivery").closest("tr")!;
    const borealisRow = within(table).getByText("Borealis Review").closest("tr")!;
    expect(within(atlasRow).getByText("Not assessed")).toBeInTheDocument();
    expect(within(borealisRow).getByText("Not assessed")).toBeInTheDocument();
    expect(within(atlasRow).queryByText("On Track")).not.toBeInTheDocument();
    expect(within(atlasRow).queryByText("At Risk")).not.toBeInTheDocument();
    expect(within(atlasRow).getByText("92.00%")).toBeInTheDocument();
    expect(within(atlasRow).getByText("Jul 17")).toBeInTheDocument();
    expect(within(atlasRow).getByText("Jul 24")).toBeInTheDocument();
    expect(within(atlasRow).getByText("5.0/5")).toBeInTheDocument();
    expect(mockedFetchMaster).toHaveBeenCalledTimes(1);
    expect(mockedFetchOverview).not.toHaveBeenCalled();
  });

  it("updates only the selected row Health from overview project_health status", async () => {
    const user = userEvent.setup();
    renderDashboard();

    const table = await screen.findByRole("table", { name: "Authorized client projects" });
    const atlasRow = within(table).getByText("Atlas Delivery").closest("tr")!;
    const borealisRow = within(table).getByText("Borealis Review").closest("tr")!;
    expect(within(atlasRow).getByText("Not assessed")).toBeInTheDocument();
    expect(within(borealisRow).getByText("Not assessed")).toBeInTheDocument();

    await user.click(within(atlasRow).getByRole("button", { name: "View Atlas Delivery" }));

    await waitFor(() =>
      expect(mockedFetchOverview).toHaveBeenCalledWith(projects[0].id, undefined),
    );
    expect(mockedFetchOverview).toHaveBeenCalledTimes(1);
    expect(await within(atlasRow).findByText("Insufficient")).toBeInTheDocument();
    expect(within(borealisRow).getByText("Not assessed")).toBeInTheDocument();
    expect(within(atlasRow).getByText("87.50%")).toBeInTheDocument();
    expect(within(borealisRow).getByText("74.00%")).toBeInTheDocument();
    expect(atlasRow).toHaveAttribute("aria-selected", "true");
    expect(borealisRow).toHaveAttribute("aria-selected", "false");
  });

  it("does not invent Health when the selected overview fails", async () => {
    const user = userEvent.setup();
    mockedFetchOverview.mockRejectedValueOnce(new Error("overview offline"));
    renderDashboard();

    const table = await screen.findByRole("table", { name: "Authorized client projects" });
    const atlasRow = within(table).getByText("Atlas Delivery").closest("tr")!;
    const borealisRow = within(table).getByText("Borealis Review").closest("tr")!;
    await user.click(within(atlasRow).getByRole("button", { name: "View Atlas Delivery" }));

    await waitFor(() => expect(mockedFetchOverview).toHaveBeenCalled());
    expect(await within(atlasRow).findByText("Not assessed")).toBeInTheDocument();
    expect(within(borealisRow).getByText("Not assessed")).toBeInTheDocument();
    expect(within(atlasRow).queryByText("On Track")).not.toBeInTheDocument();
    expect(within(atlasRow).queryByText("Insufficient")).not.toBeInTheDocument();
  });

  it("clears selected-row Health after a failed overview refresh without inventing a status", async () => {
    const user = userEvent.setup();
    renderDashboard();

    const table = await screen.findByRole("table", { name: "Authorized client projects" });
    const atlasRow = within(table).getByText("Atlas Delivery").closest("tr")!;
    const borealisRow = within(table).getByText("Borealis Review").closest("tr")!;
    await user.click(within(atlasRow).getByRole("button", { name: "View Atlas Delivery" }));

    expect(await within(atlasRow).findByText("Insufficient")).toBeInTheDocument();
    expect(within(atlasRow).getByText("87.50%")).toBeInTheDocument();
    expect(within(borealisRow).getByText("Not assessed")).toBeInTheDocument();
    expect(within(borealisRow).getByText("74.00%")).toBeInTheDocument();

    mockedFetchOverview.mockRejectedValueOnce(new Error("overview refresh offline"));
    await user.click(screen.getByRole("button", { name: "Refresh overview" }));

    await waitFor(() => {
      expect(within(atlasRow).queryByText("Insufficient")).not.toBeInTheDocument();
    });
    expect(within(atlasRow).getByText("Not assessed")).toBeInTheDocument();
    expect(within(borealisRow).getByText("Not assessed")).toBeInTheDocument();
    // Confidence remains driven by retained overview/master values — Health-only correction.
    expect(within(atlasRow).getByText("87.50%")).toBeInTheDocument();
    expect(within(borealisRow).getByText("74.00%")).toBeInTheDocument();
  });

  it("shows Loading… only on the selected row Health while overview loads", async () => {
    const pending = deferred<ClientIntelligenceOverview>();
    mockedFetchOverview.mockReturnValueOnce(pending.promise);
    const user = userEvent.setup();
    renderDashboard();

    const table = await screen.findByRole("table", { name: "Authorized client projects" });
    const atlasRow = within(table).getByText("Atlas Delivery").closest("tr")!;
    const borealisRow = within(table).getByText("Borealis Review").closest("tr")!;
    await user.click(within(atlasRow).getByRole("button", { name: "View Atlas Delivery" }));

    expect(await within(atlasRow).findAllByText("Loading…")).toHaveLength(2);
    expect(within(borealisRow).getByText("Not assessed")).toBeInTheDocument();
    expect(within(borealisRow).queryByText("Loading…")).not.toBeInTheDocument();
    pending.resolve(overviewFor(projects[0]));
    expect(await within(atlasRow).findByText("Insufficient")).toBeInTheDocument();
  });

  it("creates an evidence-backed draft from the Client Master row", async () => {
    const user = userEvent.setup();
    renderDashboard();

    const table = await screen.findByRole("table", { name: "Authorized client projects" });
    const atlasRow = within(table).getByText("Atlas Delivery").closest("tr")!;
    await user.click(within(atlasRow).getByRole("button", { name: "Draft Atlas Delivery" }));

    await waitFor(() =>
      expect(mockedCreateDraft).toHaveBeenCalledWith(projects[0].id, expect.any(Object)),
    );
    expect(
      await screen.findByText("Draft created: Weekly Client Update · 2026-07-16"),
    ).toBeInTheDocument();
    expect(atlasRow).toHaveAttribute("aria-selected", "true");
  });

  it("shows stored drafts in Client Detail and opens their evidence", async () => {
    const user = userEvent.setup();
    mockedListCommunications.mockResolvedValueOnce([
      {
        id: "55555555-5555-4555-8555-555555555555",
        project_id: projects[0].id,
        comm_type: "weekly_summary",
        subject: "Weekly Client Update · 2026-07-16",
        body_draft: "Evidence-backed delivery update.",
        body_approved: null,
        status: "draft",
        drafted_by_agent: "client_interaction_agent",
        reviewed_by: null,
        reviewed_at: null,
        approved_by: null,
        approved_at: null,
        sent_at: null,
        rejection_reason: null,
        rejected_by: null,
        rejected_at: null,
        created_at: "2026-07-16T12:00:00Z",
        updated_at: "2026-07-16T12:00:00Z",
        evidence_links: [
          {
            id: "66666666-6666-4666-8666-666666666666",
            source_table: "throughput_snapshots",
            source_row_id: "77777777-7777-4777-8777-777777777777",
            description: "Latest governed throughput snapshot.",
            created_at: "2026-07-16T12:00:00Z",
          },
        ],
      },
    ]);
    renderDashboard();

    const table = await screen.findByRole("table", { name: "Authorized client projects" });
    const atlasRow = within(table).getByText("Atlas Delivery").closest("tr")!;
    await user.click(within(atlasRow).getByRole("button", { name: "View Atlas Delivery" }));

    expect(await screen.findByText("Draft Reports Queue")).toBeInTheDocument();
    await user.click(await screen.findByText("Weekly Client Update · 2026-07-16"));
    expect(screen.getByText("Evidence-backed delivery update.")).toBeInTheDocument();
    expect(screen.getByText(/Latest governed throughput snapshot/)).toBeInTheDocument();
  });

  it("activates the View button and loads the selected project detail", async () => {
    const user = userEvent.setup();
    renderDashboard();

    const table = await screen.findByRole("table", { name: "Authorized client projects" });
    const atlasRow = within(table).getByText("Atlas Delivery").closest("tr")!;
    await user.click(within(atlasRow).getByRole("button", { name: "View Atlas Delivery" }));

    await waitFor(() =>
      expect(mockedFetchOverview).toHaveBeenCalledWith(projects[0].id, undefined),
    );
    expect(atlasRow).toHaveAttribute("aria-selected", "true");
    expect(await screen.findByText("Atlas Delivery · Detail")).toBeInTheDocument();
  });

  it("keeps Draft clickable and surfaces backend role restrictions", async () => {
    const user = userEvent.setup();
    useAuthStore.getState().setUser(userFor("bsg_leadership"));
    mockedCreateDraft.mockRejectedValueOnce(
      new ApiError(403, "FORBIDDEN", "Drafting requires Delivery Manager or Super Admin access."),
    );
    renderDashboard();

    const table = await screen.findByRole("table", { name: "Authorized client projects" });
    const atlasRow = within(table).getByText("Atlas Delivery").closest("tr")!;
    const draftButton = within(atlasRow).getByRole("button", {
      name: "Draft Atlas Delivery",
    });
    expect(draftButton).toBeEnabled();
    await user.click(draftButton);

    expect(
      await screen.findByText("Drafting requires Delivery Manager or Super Admin access."),
    ).toBeInTheDocument();
    expect(mockedCreateDraft).toHaveBeenCalledWith(projects[0].id, expect.any(Object));
  });

  it("does not request an overview before a valid project is available", async () => {
    const pending = deferred<ProjectRead[]>();
    mockedListProjects.mockReturnValueOnce(pending.promise);
    renderDashboard();

    expect(screen.getByRole("status")).toHaveTextContent("Loading authorized projects…");
    expect(screen.getByTestId("client-intelligence-summary-grid")).toBeInTheDocument();
    expect(screen.getByTestId("client-intelligence-main-grid")).toBeInTheDocument();
    expect(
      screen.getByText("Select a project row to view governed Client Intelligence."),
    ).toBeInTheDocument();
    expect(mockedFetchOverview).not.toHaveBeenCalled();
    await waitFor(() => expect(mockedFetchSummary).toHaveBeenCalled());
    pending.resolve([]);
    expect(
      await screen.findByText("No authorized projects are available for Client Intelligence."),
    ).toBeInTheDocument();
  });

  it("keeps summary loading states in the restored four-card grid", async () => {
    const pending = deferred<ClientIntelligenceSummary>();
    mockedFetchSummary.mockReturnValueOnce(pending.promise);
    renderDashboard();

    const summary = screen.getByTestId("client-intelligence-summary-grid");
    expect(summary.children).toHaveLength(4);
    expect(within(summary).getAllByText("Loading…").length).toBeGreaterThanOrEqual(1);
    pending.resolve(populatedSummary());
    expect(await within(summary).findByText("2 drafted · 5 approved")).toBeInTheDocument();
  });

  it("renders real report counts, latency units, and CSAT sample size", async () => {
    mockedFetchSummary.mockImplementation(async (projectId) =>
      projectId ? selectedProjectSummary() : populatedSummary(),
    );
    renderDashboard();

    const summary = screen.getByTestId("client-intelligence-summary-grid");
    expect(await within(summary).findByText("87.50%")).toBeInTheDocument();
    expect(within(summary).getByText("Available · 2 of 2 projects")).toBeInTheDocument();
    expect(await within(summary).findByText("2 drafted · 5 approved")).toBeInTheDocument();
    expect(within(summary).getByText("850 ms")).toBeInTheDocument();
    expect(within(summary).getByText("4.5 / 5 across 8 responses")).toBeInTheDocument();
  });

  it("switches from authorized-scope confidence to the exact selected project score", async () => {
    const selectedOverview = overviewFor(projects[1]);
    selectedOverview.delivery_confidence = {
      ...selectedOverview.delivery_confidence,
      score_pct: "73.25",
      confidence_band: "at_risk",
    };
    mockedFetchSummary.mockImplementation(async (projectId) =>
      projectId ? selectedProjectSummary() : populatedSummary(),
    );
    mockedFetchOverview.mockResolvedValueOnce(selectedOverview);
    renderDashboard();

    const summary = screen.getByTestId("client-intelligence-summary-grid");
    expect(await within(summary).findByText("87.50%")).toBeInTheDocument();
    expect(within(summary).getByText("Available · 2 of 2 projects")).toBeInTheDocument();

    await selectProject("Borealis Review");

    expect(await within(summary).findByText("73.25%")).toBeInTheDocument();
    expect(within(summary).getByText("Borealis Review · Partial · At Risk")).toBeInTheDocument();
    expect(within(summary).queryByText("Available · 2 of 2 projects")).not.toBeInTheDocument();
    expect(within(summary).getByText("1 drafted · 2 approved")).toBeInTheDocument();
    expect(within(summary).getByText("5 s")).toBeInTheDocument();
    expect(within(summary).getByText("3.8 / 5 across 2 responses")).toBeInTheDocument();
    expect(within(summary).getByText("2 responses")).toBeInTheDocument();
    expect(within(summary).getAllByText("Borealis Review · Available")).toHaveLength(3);
    expect(mockedFetchSummary).toHaveBeenCalledWith(projects[1].id);
  });

  it("renders partial values, availability, samples, and limitations for every KPI", async () => {
    mockedFetchSummary.mockResolvedValueOnce({
      delivery_confidence: {
        availability: "partial",
        average_score_pct: "91.25",
        covered_project_count: 1,
        eligible_project_count: 2,
        limitations: ["DELIVERY_CONFIDENCE_COVERAGE_PARTIAL"],
      },
      reports: {
        availability: "partial",
        drafted_count: 1,
        approved_count: 1,
        eligible_record_count: 2,
        limitations: ["REPORT_SENT_APPROVAL_PROVENANCE_INCOMPLETE"],
      },
      query_response: {
        availability: "partial",
        average_latency_ms: 2400,
        sample_size: 3,
        limitations: ["QUERY_LATENCY_MISSING_OR_INVALID"],
      },
      csat: {
        availability: "partial",
        average_score: "4.2",
        sample_size: 4,
        scale_max: 5,
        limitations: ["CSAT_SCORE_OUT_OF_RANGE"],
      },
      authorized_project_count: 1,
    });
    renderDashboard();

    const summary = screen.getByTestId("client-intelligence-summary-grid");
    await within(summary).findByText("1 drafted · 1 approved");
    const confidenceCard = within(summary).getByText("Delivery Confidence").parentElement!;
    const reportsCard = within(summary).getByText("Reports Drafted vs Approved").parentElement!;
    const queryCard = within(summary).getByText("Avg Query Response").parentElement!;
    const csatCard = within(summary).getByText("Avg CSAT").parentElement!;

    expect(within(confidenceCard).getByText("91.25%")).toBeInTheDocument();
    expect(within(confidenceCard).getByText("Partial · 1 of 2 projects")).toBeInTheDocument();
    expect(
      within(confidenceCard).getByText("Delivery Confidence Coverage Partial"),
    ).toBeInTheDocument();
    expect(within(reportsCard).getByText("1 drafted · 1 approved")).toBeInTheDocument();
    expect(within(reportsCard).getByText("Authorized scope · Partial")).toBeInTheDocument();
    expect(
      within(reportsCard).getByText("Report Sent Approval Provenance Incomplete"),
    ).toBeInTheDocument();
    expect(within(queryCard).getByText("2.4 s")).toBeInTheDocument();
    expect(within(queryCard).getByText("Authorized scope · Partial")).toBeInTheDocument();
    expect(within(queryCard).getByText("Query Latency Missing Or Invalid")).toBeInTheDocument();
    expect(within(csatCard).getByText("4.2 / 5 across 4 responses")).toBeInTheDocument();
    expect(within(csatCard).getByText("Authorized scope · Partial")).toBeInTheDocument();
    expect(within(csatCard).getByText("Csat Score Out Of Range")).toBeInTheDocument();
  });

  it("renders unavailable query response with its limitation", async () => {
    mockedFetchSummary.mockResolvedValueOnce({
      ...emptySummary(),
      delivery_confidence: {
        ...emptySummary().delivery_confidence,
        eligible_project_count: 1,
      },
      query_response: {
        availability: "unavailable",
        average_latency_ms: null,
        sample_size: 0,
        limitations: ["QUERY_LATENCY_MISSING_OR_INVALID"],
      },
      authorized_project_count: 1,
    });
    renderDashboard();

    const summary = screen.getByTestId("client-intelligence-summary-grid");
    await within(summary).findAllByText("Not available");
    const queryCard = within(summary).getByText("Avg Query Response").parentElement!;
    expect(within(queryCard).getAllByText("Not available").length).toBeGreaterThan(0);
    expect(within(queryCard).getByText("Query Latency Missing Or Invalid")).toBeInTheDocument();
  });

  it("keeps projects and selection usable when summary fails", async () => {
    mockedFetchSummary.mockRejectedValueOnce(new Error("summary offline"));
    renderDashboard();

    const table = await screen.findByRole("table", { name: "Authorized client projects" });
    expect(within(table).getByText("Atlas Delivery")).toBeInTheDocument();
    expect(screen.getByTestId("client-intelligence-summary-grid").children).toHaveLength(4);
    expect(mockedFetchOverview).not.toHaveBeenCalled();

    await selectProject();
    await waitFor(() =>
      expect(mockedFetchOverview).toHaveBeenCalledWith(projects[0].id, undefined),
    );
    expect(await screen.findByText("Atlas Delivery · Detail")).toBeInTheDocument();
  });

  it("formats larger query latencies with truthful units", async () => {
    mockedFetchSummary.mockResolvedValueOnce({
      ...populatedSummary(),
      query_response: {
        availability: "available",
        average_latency_ms: 2400,
        sample_size: 3,
        limitations: [],
      },
    });
    renderDashboard();
    const summary = screen.getByTestId("client-intelligence-summary-grid");
    expect(await within(summary).findByText("2.4 s")).toBeInTheDocument();
  });

  it("selects projects by ID and requests the selected project overview", async () => {
    renderDashboard();
    const table = await selectProject("Borealis Review");
    await waitFor(() =>
      expect(mockedFetchOverview).toHaveBeenCalledWith(projects[1].id, undefined),
    );
    expect(mockedFetchOverview).toHaveBeenCalledTimes(1);
    expect(within(table).getByText("Borealis Review").closest("tr")).toHaveAttribute(
      "aria-selected",
      "true",
    );
    expect(within(table).getByText("Atlas Delivery").closest("tr")).toHaveAttribute(
      "aria-selected",
      "false",
    );
  });

  it("clears selection when a project refresh removes the selected project", async () => {
    const user = userEvent.setup();
    mockedListProjects.mockResolvedValueOnce(projects).mockResolvedValueOnce([projects[1]]);
    renderDashboard();
    await selectProject("Atlas Delivery");
    expect(await screen.findByText("Atlas Delivery · Detail")).toBeInTheDocument();
    expect(mockedFetchOverview).toHaveBeenCalledTimes(1);

    await user.click(screen.getByRole("button", { name: "Refresh projects" }));

    const refreshedTable = await screen.findByRole("table", {
      name: "Authorized client projects",
    });
    await waitFor(() =>
      expect(within(refreshedTable).queryByText("Atlas Delivery")).not.toBeInTheDocument(),
    );
    expect(
      screen.getByText("Select a project row to view governed Client Intelligence."),
    ).toBeInTheDocument();
    expect(within(refreshedTable).getByText("Borealis Review").closest("tr")).toHaveAttribute(
      "aria-selected",
      "false",
    );
    expect(mockedFetchOverview).toHaveBeenCalledTimes(1);
    await waitFor(() => expect(mockedFetchSummary).toHaveBeenCalledTimes(4));
    expect(within(refreshedTable).getByText("Borealis Review").closest("tr")).toHaveAttribute(
      "aria-selected",
      "false",
    );
  });

  it("refresh projects refetches summary without selecting or requesting overview", async () => {
    const user = userEvent.setup();
    renderDashboard();
    const table = await screen.findByRole("table", { name: "Authorized client projects" });
    await waitFor(() => expect(mockedFetchSummary).toHaveBeenCalledTimes(1));
    expect(mockedFetchOverview).not.toHaveBeenCalled();

    await user.click(screen.getByRole("button", { name: "Refresh projects" }));

    await waitFor(() => expect(mockedListProjects).toHaveBeenCalledTimes(2));
    await waitFor(() => expect(mockedFetchSummary).toHaveBeenCalledTimes(2));
    expect(mockedFetchOverview).not.toHaveBeenCalled();
    expect(within(table).getByText("Atlas Delivery").closest("tr")).toHaveAttribute(
      "aria-selected",
      "false",
    );
    expect(
      screen.getByText("Select a project row to view governed Client Intelligence."),
    ).toBeInTheDocument();
  });

  it("summary refresh failure preserves selected overview and project list", async () => {
    const user = userEvent.setup();
    let selectedSummaryCalls = 0;
    mockedFetchSummary.mockImplementation(async (projectId) => {
      if (!projectId) return populatedSummary();
      selectedSummaryCalls += 1;
      if (selectedSummaryCalls === 2) {
        throw new Error("summary refresh offline");
      }
      return selectedProjectSummary();
    });
    renderDashboard();
    await selectProject();
    expect(await screen.findByText("Atlas Delivery · Detail")).toBeInTheDocument();
    await waitFor(() => expect(mockedFetchSummary).toHaveBeenCalledTimes(2));

    await user.click(screen.getByRole("button", { name: "Refresh projects" }));

    await waitFor(() => expect(mockedFetchSummary).toHaveBeenCalledTimes(4));
    expect(screen.getByRole("table", { name: "Authorized client projects" })).toBeInTheDocument();
    expect(screen.getByText("Atlas Delivery · Detail")).toBeInTheDocument();
    expect(mockedFetchOverview).toHaveBeenCalledTimes(1);
  });

  it("filters only the authorized project names", async () => {
    const user = userEvent.setup();
    renderDashboard();
    const table = await screen.findByRole("table", { name: "Authorized client projects" });

    await user.type(screen.getByLabelText("Search project names"), "Borealis");
    expect(within(table).queryByText("Atlas Delivery")).not.toBeInTheDocument();
    expect(within(table).getByText("Borealis Review")).toBeInTheDocument();
  });

  it("renders the four real assessment summaries and exact partial states", async () => {
    renderDashboard();
    await selectProject();
    await screen.findByText("Atlas Delivery · Detail");

    expect(screen.getAllByText("Project Health").length).toBeGreaterThan(0);
    expect(screen.getAllByText("Delivery Confidence").length).toBeGreaterThan(0);
    expect(screen.getAllByText("Risk Transparency").length).toBeGreaterThan(0);
    expect(screen.getAllByText("Delivery Trend").length).toBeGreaterThan(0);
    expect(screen.getAllByText("Insufficient").length).toBeGreaterThan(0);
    expect(screen.getAllByText("Partial").length).toBeGreaterThan(0);
    expect(screen.getAllByText("Unavailable").length).toBeGreaterThan(0);
    expect(screen.getAllByText("87.50%").length).toBeGreaterThan(0);
  });

  it("shows missing health policy and never turns unavailable risk into no-risk text", async () => {
    renderDashboard();
    await selectProject();
    await screen.findByText("Atlas Delivery · Detail");

    expect(
      screen.getByText("Project health rules are not configured yet"),
    ).toBeInTheDocument();
    expect(
      screen.getByText("No items are published for this assessment state."),
    ).toBeInTheDocument();
    expect(screen.queryByText(/no risks detected/i)).not.toBeInTheDocument();
  });

  it("shows No score rather than zero when confidence score is null", async () => {
    mockedFetchOverview.mockResolvedValueOnce(
      overviewFor(projects[0], {
        delivery_confidence: {
          ...overviewFor(projects[0]).delivery_confidence,
          availability: "no_score",
          score_pct: null,
          confidence_band: null,
          current_milestone: null,
          forecast_completion_date: null,
          source_data_quality: "unavailable",
          trend: "unknown",
        },
      }),
    );
    renderDashboard();
    await selectProject();

    expect((await screen.findAllByText("No score")).length).toBeGreaterThan(0);
    expect(screen.queryByText("0%")).not.toBeInTheDocument();
  });

  it("preserves null trend values and does not invent plan data", async () => {
    renderDashboard();
    await selectProject();
    await screen.findByText("Atlas Delivery · Detail");

    expect(screen.getByText(/Latest Jul 14, 2026/)).toHaveTextContent("Actual 42");
    expect(screen.getByText(/Latest Jul 14, 2026/)).toHaveTextContent("Plan Missing Source");
    expect(screen.getByText(/Latest Jul 14, 2026/)).toHaveTextContent("Forecast Missing Source");
    expect(screen.queryByText(/Actual 0|Plan 0|Forecast 0/)).not.toBeInTheDocument();
  });

  it("keeps structured, source, visibility, and engine limitations separate", async () => {
    renderDashboard();
    await selectProject();
    await screen.findByText("Atlas Delivery · Detail");

    expect(screen.getByText("Data quality")).toBeInTheDocument();
    expect(screen.getByText("Delivery throughput")).toBeInTheDocument();
    expect(screen.getByText(/Partial · Forecast coverage is incomplete\./)).toBeInTheDocument();
    expect(screen.getByText("Source limitations")).toBeInTheDocument();
    expect(screen.getByText("Historical delivery confidence is unavailable.")).toBeInTheDocument();
    expect(screen.getByText("Visibility limitations")).toBeInTheDocument();
    expect(
      screen.getByText(/Knowledge evidence was not visible in this projection\./),
    ).toBeInTheDocument();
    expect(screen.getByText(/Engine limitations/)).toBeInTheDocument();
    expect(screen.getByText("Technical details")).toBeInTheDocument();
  });

  it("shows friendly data-quality labels and keeps raw detail under Technical details", async () => {
    mockedFetchOverview.mockResolvedValueOnce(
      overviewFor(projects[0], {
        data_quality: [
          {
            source: "ci_d07",
            state: "unavailable",
            detail:
              "CI-D07 Workflow Status is a Phase 1 blocker: KnowledgeSourceType has no source contract.",
            observed_at: "2026-07-15T00:00:00Z",
          },
          {
            source: "throughput_snapshots",
            state: "partial",
            detail: "Forecast coverage is incomplete.",
            observed_at: "2026-07-15T00:00:00Z",
          },
        ],
      }),
    );
    renderDashboard();
    await selectProject();
    await screen.findByText("Atlas Delivery · Detail");

    const dataQualitySection = screen.getByText("Data quality").closest("section");
    expect(dataQualitySection).not.toBeNull();
    expect(dataQualitySection).toHaveTextContent("Delivery");
    expect(dataQualitySection).not.toHaveTextContent("KnowledgeSourceType");
    expect(dataQualitySection).not.toHaveTextContent(/Dq Ci D07/i);

    await screen.getByRole("button", { name: /Show all sources \(2\)/i }).click();
    expect(dataQualitySection).toHaveTextContent("Workflow status");
    expect(dataQualitySection).toHaveTextContent("Delivery throughput");

    const technical = screen.getByText("Technical details").closest("details");
    expect(technical).not.toBeNull();
    expect(technical).toHaveTextContent(/KnowledgeSourceType/);
    expect(technical).toHaveTextContent(/ci_d07/);
  });

  it("groups and collapses dense data-quality issues behind Show all sources", async () => {
    mockedFetchOverview.mockResolvedValueOnce(
      overviewFor(projects[0], {
        overall_data_quality: "partial",
        data_quality: [
          {
            source: "throughput_snapshots",
            state: "partial",
            detail: "Forecast coverage is incomplete.",
            observed_at: null,
          },
          {
            source: "ci_d07",
            state: "unavailable",
            detail: "CI-D07 Workflow Status Phase 1 blocker KnowledgeSourceType",
            observed_at: null,
          },
          {
            source: "knowledge_ci_d11",
            state: "unavailable",
            detail: "CI-D11 SOP KnowledgeSourceType missing",
            observed_at: null,
          },
          {
            source: "knowledge_ci_d12",
            state: "unavailable",
            detail: "CI-D12 training KnowledgeSourceType missing",
            observed_at: null,
          },
          {
            source: "knowledge_ci_d13",
            state: "unavailable",
            detail: "CI-D13 charter KnowledgeSourceType missing",
            observed_at: null,
          },
          {
            source: "governance_actions",
            state: "unavailable",
            detail: "No governance actions for as_of",
            observed_at: null,
          },
          {
            source: "governance_scope",
            state: "partial",
            detail: "Scope notes incomplete",
            observed_at: null,
          },
          {
            source: "quality_snapshots",
            state: "complete",
            detail: "Complete quality snapshot",
            observed_at: null,
          },
        ],
      }),
    );
    renderDashboard();
    await selectProject();
    await screen.findByText("Atlas Delivery · Detail");

    const dataQualitySection = screen.getByText("Data quality").closest("section");
    expect(dataQualitySection).not.toBeNull();
    expect(dataQualitySection).toHaveTextContent("Documents & knowledge");
    expect(dataQualitySection).toHaveTextContent("Governance");
    expect(dataQualitySection).not.toHaveTextContent("Quality snapshots");
    expect(dataQualitySection).not.toHaveTextContent("KnowledgeSourceType");

    await screen.getByRole("button", { name: /Show all sources \(7\)/i }).click();
    expect(dataQualitySection).toHaveTextContent("SOP documents");
    expect(dataQualitySection).toHaveTextContent("Training documents");
    expect(screen.getByRole("button", { name: /Show less/i })).toBeInTheDocument();
  });

  it("keeps the navigator visible while a selected overview is loading", async () => {
    const pending = deferred<ClientIntelligenceOverview>();
    mockedFetchOverview.mockReturnValueOnce(pending.promise);
    renderDashboard();

    await selectProject();
    expect(screen.getByRole("table", { name: "Authorized client projects" })).toBeInTheDocument();
    expect(screen.getByTestId("client-intelligence-summary-grid")).toBeInTheDocument();
    expect(screen.getByTestId("client-intelligence-main-grid")).toBeInTheDocument();
    expect(screen.getByText("Loading Client Intelligence overview…")).toBeInTheDocument();
    pending.resolve(overviewFor(projects[0]));
    expect(await screen.findByText("Atlas Delivery · Detail")).toBeInTheDocument();
  });

  it("renders an empty state for an empty authorized project list", async () => {
    mockedListProjects.mockResolvedValueOnce([]);
    renderDashboard();

    expect(
      await screen.findByText("No authorized projects are available for Client Intelligence."),
    ).toBeInTheDocument();
    expect(mockedFetchOverview).not.toHaveBeenCalled();
  });

  it("renders project errors and retries the projects request", async () => {
    const user = userEvent.setup();
    mockedListProjects.mockRejectedValueOnce(new Error("offline"));
    renderDashboard();

    await user.click(await screen.findByRole("button", { name: "Retry projects" }));
    await waitFor(() => expect(mockedListProjects).toHaveBeenCalledTimes(2));
    expect(
      await screen.findByRole("table", { name: "Authorized client projects" }),
    ).toBeInTheDocument();
  });

  it("renders a safe 403 permission state and retries overview requests", async () => {
    const user = userEvent.setup();
    mockedFetchOverview.mockRejectedValueOnce(new ApiError(403, "FORBIDDEN", "Raw detail"));
    renderDashboard();
    await selectProject();

    expect(
      await screen.findByText(
        "You do not have permission to view Client Intelligence for this project.",
      ),
    ).toBeInTheDocument();
    expect(screen.queryByText("Raw detail")).not.toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Retry overview" }));
    expect(await screen.findByText("Atlas Delivery · Detail")).toBeInTheDocument();
  });

  it("guides project refresh when the overview returns 404", async () => {
    mockedFetchOverview.mockRejectedValueOnce(
      new ApiError(404, "PROJECT_NOT_FOUND", "Project not found."),
    );
    renderDashboard();
    await selectProject();

    expect(
      await screen.findByText(
        "The selected project is no longer available. Refresh the project list.",
      ),
    ).toBeInTheDocument();
    expect(screen.getAllByRole("button", { name: "Refresh projects" })).toHaveLength(2);
  });

  it("shows the sanitized integrity error message", async () => {
    mockedFetchOverview.mockRejectedValueOnce(
      new ApiError(
        500,
        "CLIENT_INTELLIGENCE_INTEGRITY_ERROR",
        "Client Intelligence could not be assembled from the available governed evidence.",
      ),
    );
    renderDashboard();
    await selectProject();

    expect(
      await screen.findByText(
        "Client Intelligence could not be assembled from the available governed evidence.",
      ),
    ).toBeInTheDocument();
  });

  it("refreshes only the selected overview", async () => {
    const user = userEvent.setup();
    renderDashboard();
    await selectProject();
    await screen.findByText("Atlas Delivery · Detail");
    mockedFetchOverview.mockClear();
    mockedFetchConfidenceHistory.mockClear();

    await user.click(screen.getByRole("button", { name: "Refresh overview" }));
    await waitFor(() => expect(mockedFetchOverview).toHaveBeenCalledTimes(1));
    await waitFor(() => expect(mockedFetchConfidenceHistory).toHaveBeenCalledTimes(1));
    expect(mockedFetchOverview).toHaveBeenCalledWith(projects[0].id, undefined);
    expect(mockedFetchConfidenceHistory).toHaveBeenCalledWith(projects[0].id);
    expect(mockedListProjects).toHaveBeenCalledTimes(1);
  });

  it("uses the established query key, stale time, and disabled state", () => {
    expect(clientIntelligenceOverviewQueryOptions(null).enabled).toBe(false);
    expect(clientIntelligenceOverviewQueryOptions(projects[0].id).queryKey).toEqual(
      queryKeys.clientIntelligenceOverview(projects[0].id),
    );
    expect(clientIntelligenceOverviewQueryOptions(projects[0].id, "2026-07-15").queryKey).toEqual(
      queryKeys.clientIntelligenceOverview(projects[0].id, "2026-07-15"),
    );
    expect(clientIntelligenceOverviewQueryOptions(projects[0].id).staleTime).toBe(STALE_TIME_MS);
    expect(clientIntelligenceDeliveryConfidenceHistoryQueryOptions(null).enabled).toBe(false);
    expect(
      clientIntelligenceDeliveryConfidenceHistoryQueryOptions(projects[0].id).queryKey,
    ).toEqual(queryKeys.clientIntelligenceDeliveryConfidenceHistory(projects[0].id));
    expect(clientIntelligenceDeliveryConfidenceHistoryQueryOptions(projects[0].id).staleTime).toBe(
      STALE_TIME_MS,
    );
    expect(clientIntelligenceSummaryQueryOptions().queryKey).toEqual(
      queryKeys.clientIntelligenceSummary,
    );
    expect(clientIntelligenceSummaryQueryOptions().staleTime).toBe(STALE_TIME_MS);
    expect(clientIntelligenceProjectSummaryQueryOptions(null).enabled).toBe(false);
    expect(clientIntelligenceProjectSummaryQueryOptions(projects[0].id).queryKey).toEqual(
      queryKeys.clientIntelligenceProjectSummary(projects[0].id),
    );
    expect(clientIntelligenceProjectSummaryQueryOptions(projects[0].id).staleTime).toBe(
      STALE_TIME_MS,
    );
  });

  it("renders a real confidence sparkline from selected project history points", async () => {
    renderDashboard();
    await selectProject();

    await waitFor(() => expect(mockedFetchConfidenceHistory).toHaveBeenCalledWith(projects[0].id));
    expect(mockedFetchConfidenceHistory).toHaveBeenCalledTimes(1);
    const sparkline = await screen.findByRole("img", {
      name: /2 points · oldest 80\.00% .* · latest\/current 87\.50% .* · Available/,
    });
    const polyline = sparkline.querySelector("polyline");
    expect(polyline).not.toBeNull();
    const points = polyline!.getAttribute("points")!;
    expect(points).not.toBe("2,17 15,13 27,16 40,10 53,12 65,7 74,8");
    const pairs = points.split(" ").map((pair) => pair.split(",").map(Number));
    expect(pairs).toHaveLength(2);
    expect(pairs[0][0]).toBeLessThan(pairs[1][0]);
    expect(pairs[1][1]).toBeLessThan(pairs[0][1]);
    expect(
      within(screen.getByTestId("client-intelligence-summary-grid")).getByText("87.50%"),
    ).toBeInTheDocument();
  });

  it("renders a single confidence history marker without a fake polyline", async () => {
    mockedFetchConfidenceHistory.mockResolvedValueOnce(
      historyFor(projects[0], {
        points: [
          {
            source_row_id: "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaa0001",
            project_id: projects[0].id,
            milestone_id: "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaa0002",
            score_pct: "91.00",
            confidence_status: "on_track",
            observed_at: "2026-07-15T12:00:00Z",
          },
        ],
        returned_point_count: 1,
        total_valid_point_count: 1,
      }),
    );
    renderDashboard();
    await selectProject();

    const sparkline = await screen.findByRole("img", { name: /1 point ·/ });
    expect(sparkline.querySelector("polyline")).toBeNull();
    expect(sparkline.querySelector("circle")).not.toBeNull();
  });

  it("shows no confidence line and truthful text when history has no data", async () => {
    mockedFetchConfidenceHistory.mockResolvedValueOnce(
      historyFor(projects[0], {
        availability: "no_data",
        points: [],
        returned_point_count: 0,
        total_valid_point_count: 0,
        current_score_availability: "missing",
        current_source_row_id: null,
        latest_history_point_is_current: false,
      }),
    );
    renderDashboard();
    await selectProject();

    expect(await screen.findByLabelText("No confidence history available.")).toBeInTheDocument();
    expect(screen.queryByRole("img", { name: /point/ })).not.toBeInTheDocument();
    expect(
      within(screen.getByTestId("client-intelligence-summary-grid")).getByText("87.50%"),
    ).toBeInTheDocument();
  });

  it("announces a current valid history point as latest/current", async () => {
    renderDashboard();
    await selectProject();
    expect(await screen.findByRole("img", { name: /latest\/current 87\.50%/ })).toBeInTheDocument();
    expect(screen.queryByText(/current confidence score unavailable/i)).not.toBeInTheDocument();
  });

  it("announces older valid history as historical when the current source row is invalid", async () => {
    mockedFetchConfidenceHistory.mockResolvedValueOnce(
      historyFor(projects[0], {
        availability: "partial",
        points: [
          {
            source_row_id: "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaa0001",
            project_id: projects[0].id,
            milestone_id: "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaa0002",
            score_pct: "80.00",
            confidence_status: "on_track",
            observed_at: "2026-07-10T12:00:00Z",
          },
        ],
        returned_point_count: 1,
        total_valid_point_count: 1,
        limitations: ["LATEST_DELIVERY_CONFIDENCE_SCORE_OUT_OF_RANGE"],
        current_score_availability: "invalid",
        current_source_row_id: "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaa0099",
        latest_history_point_is_current: false,
      }),
    );
    renderDashboard();
    await selectProject();

    expect(
      await screen.findByRole("img", {
        name: /latest historical point 80\.00% .* · Partial · current confidence score unavailable/,
      }),
    ).toBeInTheDocument();
    expect(screen.getByText("Latest Delivery Confidence Score Out Of Range")).toBeInTheDocument();
    expect(
      within(screen.getByTestId("client-intelligence-summary-grid")).getByText("87.50%"),
    ).toBeInTheDocument();
    expect(screen.queryByRole("img", { name: /latest\/current/ })).not.toBeInTheDocument();
  });

  it("hides confidence history on error and does not keep a misleading line", async () => {
    mockedFetchConfidenceHistory.mockRejectedValueOnce(new Error("history offline"));
    renderDashboard();
    await selectProject();

    expect(await screen.findByLabelText("Confidence history unavailable.")).toBeInTheDocument();
    expect(screen.queryByRole("img", { name: /point/ })).not.toBeInTheDocument();
  });

  it("exposes partial history limitations without implying a complete series", async () => {
    mockedFetchConfidenceHistory.mockResolvedValueOnce(
      historyFor(projects[0], {
        availability: "partial",
        limitations: ["DELIVERY_CONFIDENCE_HISTORY_TRUNCATED"],
        returned_point_count: 2,
        total_valid_point_count: 8,
        latest_history_point_is_current: true,
      }),
    );
    renderDashboard();
    await selectProject();

    const sparkline = await screen.findByRole("img", { name: /Partial/ });
    expect(sparkline.querySelector("polyline")).not.toBeNull();
    expect(screen.getByText("Delivery Confidence History Truncated")).toBeInTheDocument();
  });

  it("never shows the previous project's confidence history after switching", async () => {
    const user = userEvent.setup();
    mockedFetchConfidenceHistory.mockImplementation(async (projectId) => {
      if (projectId === projects[0].id) {
        return historyFor(projects[0], {
          points: [
            {
              source_row_id: "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaa0010",
              project_id: projects[0].id,
              milestone_id: "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaa0011",
              score_pct: "10.00",
              confidence_status: "at_risk",
              observed_at: "2026-07-10T12:00:00Z",
            },
            {
              source_row_id: "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaa0012",
              project_id: projects[0].id,
              milestone_id: "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaa0013",
              score_pct: "20.00",
              confidence_status: "at_risk",
              observed_at: "2026-07-15T12:00:00Z",
            },
          ],
        });
      }
      return historyFor(projects[1], {
        points: [
          {
            source_row_id: "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbb0010",
            project_id: projects[1].id,
            milestone_id: "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbb0011",
            score_pct: "90.00",
            confidence_status: "on_track",
            observed_at: "2026-07-11T12:00:00Z",
          },
          {
            source_row_id: "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbb0012",
            project_id: projects[1].id,
            milestone_id: "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbb0013",
            score_pct: "95.00",
            confidence_status: "on_track",
            observed_at: "2026-07-16T12:00:00Z",
          },
        ],
      });
    });
    renderDashboard();
    await selectProject("Atlas Delivery");
    expect(await screen.findByRole("img", { name: /oldest 10\.00%/ })).toBeInTheDocument();

    await user.click(
      within(screen.getByRole("table", { name: "Authorized client projects" })).getByRole(
        "button",
        { name: "View Borealis Review" },
      ),
    );
    expect(await screen.findByRole("img", { name: /oldest 90\.00%/ })).toBeInTheDocument();
    expect(screen.queryByRole("img", { name: /oldest 10\.00%/ })).not.toBeInTheDocument();
  });

  it("clears confidence history when the selected project is lost on refresh", async () => {
    const user = userEvent.setup();
    renderDashboard();
    await selectProject();
    expect(await screen.findByRole("img", { name: /2 points/ })).toBeInTheDocument();

    mockedListProjects.mockResolvedValueOnce([projects[1]]);
    await user.click(screen.getByRole("button", { name: "Refresh projects" }));

    await waitFor(() =>
      expect(screen.getByRole("img", { name: /2 points/ })).toBeInTheDocument(),
    );
    expect(mockedFetchConfidenceHistory).toHaveBeenCalledWith(projects[1].id);
  });

  it("does not keep a stale cross-project sparkline while history loads", async () => {
    const pending = deferred<DeliveryConfidenceHistory>();
    mockedFetchConfidenceHistory.mockImplementation(async (projectId) => {
      if (projectId === projects[0].id) return historyFor(projects[0]);
      return pending.promise;
    });
    const user = userEvent.setup();
    renderDashboard();
    await selectProject("Atlas Delivery");
    expect(await screen.findByRole("img", { name: /oldest 80\.00%/ })).toBeInTheDocument();

    await user.click(
      within(screen.getByRole("table", { name: "Authorized client projects" })).getByRole(
        "button",
        { name: "View Borealis Review" },
      ),
    );
    expect(await screen.findByLabelText("Loading confidence history…")).toBeInTheDocument();
    expect(screen.queryByRole("img", { name: /oldest 80\.00%/ })).not.toBeInTheDocument();
    pending.resolve(historyFor(projects[1]));
    expect(await screen.findByRole("img", { name: /2 points/ })).toBeInTheDocument();
  });

  it("keeps Health not assessed from confidence and unchanged after history loads", async () => {
    renderDashboard();
    const table = await screen.findByRole("table", { name: "Authorized client projects" });
    const atlasRow = within(table).getByText("Atlas Delivery").closest("tr")!;
    expect(within(atlasRow).getByText("Not assessed")).toBeInTheDocument();
    await selectProject();
    expect(await within(atlasRow).findByText("Insufficient")).toBeInTheDocument();
    expect(await screen.findByRole("img", { name: /2 points/ })).toBeInTheDocument();
    expect(within(atlasRow).queryByText("On Track")).not.toBeInTheDocument();
  });

  it("restores the original visual chrome without restoring fabricated static KPI values", async () => {
    mockedFetchSummary.mockImplementation(async (projectId) =>
      projectId ? selectedProjectSummary() : populatedSummary(),
    );
    renderDashboard();
    await selectProject();
    await screen.findByText("Atlas Delivery · Detail");

    for (const retired of [
      "12 drafted · 9 approved",
      "3.4 h",
      "−18% WoW",
      "4.5 / 5 across 8 clients",
      "AI-drafted reports queue",
      "Client Q&A log",
      "Delivery narrative",
    ]) {
      expect(screen.queryByText(retired)).not.toBeInTheDocument();
    }
    expect(screen.getByText("Client Master")).toBeInTheDocument();
    expect(screen.getAllByRole("button", { name: /^Draft / })).toHaveLength(2);
    expect(document.querySelector("polyline")).toBeInTheDocument();
    expect(document.querySelector(".lucide-star")).toBeInTheDocument();
  });

  it("shows Edit and Submit for review for draft queue items", async () => {
    const user = userEvent.setup();
    mockedListCommunications.mockResolvedValue([communicationFixture()]);
    renderDashboard();
    await openQueueItem(user, "Weekly Client Update");
    expect(
      screen.getByRole("button", { name: "Edit draft Weekly Client Update" }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: "Submit Weekly Client Update for review" }),
    ).toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: "Approve Weekly Client Update" }),
    ).not.toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: "Send Weekly Client Update" }),
    ).not.toBeInTheDocument();
  });

  it("shows Approve and Reject only for in-review items", async () => {
    const user = userEvent.setup();
    mockedListCommunications.mockResolvedValue([
      communicationFixture({
        status: "in_review",
        body_approved: "Reviewed body for client.",
        reviewed_at: "2026-07-16T13:00:00Z",
      }),
    ]);
    renderDashboard();
    await openQueueItem(user, "Weekly Client Update");
    expect(
      screen.getByRole("button", { name: "Approve Weekly Client Update" }),
    ).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Reject Weekly Client Update" })).toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: "Edit draft Weekly Client Update" }),
    ).not.toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: "Send Weekly Client Update" }),
    ).not.toBeInTheDocument();
  });

  it("shows Send only for approved items", async () => {
    const user = userEvent.setup();
    mockedListCommunications.mockResolvedValue([
      communicationFixture({
        status: "approved",
        body_approved: "Approved body",
        approved_at: "2026-07-16T14:00:00Z",
      }),
    ]);
    renderDashboard();
    await openQueueItem(user, "Weekly Client Update");
    expect(screen.getByRole("button", { name: "Send Weekly Client Update" })).toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: "Approve Weekly Client Update" }),
    ).not.toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: "Reject Weekly Client Update" }),
    ).not.toBeInTheDocument();
  });

  it("shows rejection reason and Edit and revise for rejected items", async () => {
    const user = userEvent.setup();
    mockedListCommunications.mockResolvedValue([
      communicationFixture({
        status: "rejected",
        rejection_reason: "Clarify milestone dates.",
        rejected_at: "2026-07-16T15:00:00Z",
      }),
    ]);
    renderDashboard();
    await openQueueItem(user, "Weekly Client Update");
    expect(screen.getByText("Clarify milestone dates.")).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: "Edit and revise Weekly Client Update" }),
    ).toBeInTheDocument();
  });

  it("supports edit Save and Cancel without mutating until Save", async () => {
    const user = userEvent.setup();
    mockedListCommunications.mockResolvedValue([communicationFixture()]);
    mockedEditDraft.mockResolvedValue(
      communicationFixture({ subject: "Updated subject", body_draft: "Updated body" }),
    );
    renderDashboard();
    await openQueueItem(user, "Weekly Client Update");
    await user.click(screen.getByRole("button", { name: "Edit draft Weekly Client Update" }));
    await user.clear(screen.getByLabelText("Subject"));
    await user.type(screen.getByLabelText("Subject"), "Updated subject");
    await user.clear(screen.getByLabelText("Draft body"));
    await user.type(screen.getByLabelText("Draft body"), "Updated body");
    await user.click(screen.getByRole("button", { name: "Cancel editing Weekly Client Update" }));
    expect(mockedEditDraft).not.toHaveBeenCalled();
    expect(screen.getByText("Evidence-backed delivery update.")).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Edit draft Weekly Client Update" }));
    await user.clear(screen.getByLabelText("Subject"));
    await user.type(screen.getByLabelText("Subject"), "Updated subject");
    await user.clear(screen.getByLabelText("Draft body"));
    await user.type(screen.getByLabelText("Draft body"), "Updated body");
    await user.click(screen.getByRole("button", { name: "Save draft Weekly Client Update" }));
    await waitFor(() =>
      expect(mockedEditDraft).toHaveBeenCalledWith("55555555-5555-4555-8555-555555555555", {
        subject: "Updated subject",
        body_draft: "Updated body",
      }),
    );
  });

  it("blocks blank edit values before calling the API", async () => {
    const user = userEvent.setup();
    mockedListCommunications.mockResolvedValue([communicationFixture()]);
    renderDashboard();
    await openQueueItem(user, "Weekly Client Update");
    await user.click(screen.getByRole("button", { name: "Edit draft Weekly Client Update" }));
    await user.clear(screen.getByLabelText("Subject"));
    await user.click(screen.getByRole("button", { name: "Save draft Weekly Client Update" }));
    expect(screen.getByText("Subject and draft body are required.")).toBeInTheDocument();
    expect(mockedEditDraft).not.toHaveBeenCalled();
  });

  it("submits for review using the communication ID endpoint", async () => {
    const user = userEvent.setup();
    mockedListCommunications.mockResolvedValue([communicationFixture()]);
    mockedSubmitForReview.mockResolvedValue(
      communicationFixture({
        status: "in_review",
        body_approved: "Evidence-backed delivery update.",
        reviewed_at: "2026-07-16T13:00:00Z",
      }),
    );
    renderDashboard();
    await openQueueItem(user, "Weekly Client Update");
    await user.click(
      screen.getByRole("button", { name: "Submit Weekly Client Update for review" }),
    );
    await waitFor(() =>
      expect(mockedSubmitForReview).toHaveBeenCalledWith("55555555-5555-4555-8555-555555555555", {
        body_approved: "Evidence-backed delivery update.",
      }),
    );
  });

  it("approves only from in_review and rejects with a reason dialog", async () => {
    const user = userEvent.setup();
    mockedListCommunications.mockResolvedValue([
      communicationFixture({
        status: "in_review",
        body_approved: "Reviewed body",
        reviewed_at: "2026-07-16T13:00:00Z",
      }),
    ]);
    mockedApproveCommunication.mockResolvedValue(
      communicationFixture({
        status: "approved",
        body_approved: "Reviewed body",
        approved_at: "2026-07-16T14:00:00Z",
      }),
    );
    mockedRejectCommunication.mockResolvedValue(
      communicationFixture({
        status: "rejected",
        rejection_reason: "Needs clearer dates.",
      }),
    );
    renderDashboard();
    await openQueueItem(user, "Weekly Client Update");
    await user.click(screen.getByRole("button", { name: "Approve Weekly Client Update" }));
    await waitFor(() =>
      expect(mockedApproveCommunication).toHaveBeenCalledWith(
        "55555555-5555-4555-8555-555555555555",
      ),
    );

    mockedListCommunications.mockResolvedValue([
      communicationFixture({
        status: "in_review",
        body_approved: "Reviewed body",
        reviewed_at: "2026-07-16T13:00:00Z",
      }),
    ]);
    await user.click(screen.getByRole("button", { name: "Reject Weekly Client Update" }));
    expect(screen.getByRole("alertdialog")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Confirm reject Weekly Client Update" }));
    expect(screen.getByText("Rejection reason is required.")).toBeInTheDocument();
    expect(mockedRejectCommunication).not.toHaveBeenCalled();
    await user.type(screen.getByLabelText("Rejection reason"), "Needs clearer dates.");
    await user.click(screen.getByRole("button", { name: "Confirm reject Weekly Client Update" }));
    await waitFor(() =>
      expect(mockedRejectCommunication).toHaveBeenCalledWith(
        "55555555-5555-4555-8555-555555555555",
        { rejection_reason: "Needs clearer dates." },
      ),
    );
  });

  it("requires send confirmation and removes sent items from the active queue", async () => {
    const user = userEvent.setup();
    const approved = communicationFixture({
      status: "approved",
      body_approved: "Approved body",
      approved_at: "2026-07-16T14:00:00Z",
      approved_by: "99999999-9999-9999-9999-999999999999",
    });
    mockedListCommunications.mockResolvedValue([approved]);
    mockedSendCommunication.mockResolvedValue(
      communicationFixture({
        status: "sent",
        body_approved: "Approved body",
        sent_at: "2026-07-16T16:00:00Z",
      }),
    );
    renderDashboard();
    await openQueueItem(user, "Weekly Client Update");
    await user.click(screen.getByRole("button", { name: "Send Weekly Client Update" }));
    expect(screen.getByRole("alertdialog")).toBeInTheDocument();
    expect(mockedSendCommunication).not.toHaveBeenCalled();
    mockedListCommunications.mockResolvedValue([]);
    await user.click(screen.getByRole("button", { name: "Confirm send Weekly Client Update" }));
    await waitFor(() =>
      expect(mockedSendCommunication).toHaveBeenCalledWith("55555555-5555-4555-8555-555555555555"),
    );
    await waitFor(() =>
      expect(screen.getByText("No draft reports for this project.")).toBeInTheDocument(),
    );
    expect(screen.queryByText("Weekly Client Update")).not.toBeInTheDocument();
  });

  it("tracks concurrent pending actions independently and prevents duplicate same-item submits", async () => {
    const user = userEvent.setup();
    const pendingA = deferred<ClientCommunicationDraft>();
    const pendingB = deferred<ClientCommunicationDraft>();
    mockedListCommunications.mockResolvedValue([
      communicationFixture({ id: "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa", subject: "Alpha Update" }),
      communicationFixture({ id: "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb", subject: "Beta Update" }),
    ]);
    mockedSubmitForReview
      .mockReturnValueOnce(pendingA.promise)
      .mockReturnValueOnce(pendingB.promise);
    renderDashboard();
    await openQueueItem(user, "Alpha Update");
    await user.click(screen.getByRole("button", { name: "Submit Alpha Update for review" }));
    expect(
      screen.getByRole("button", { name: "Submit Alpha Update for review" }),
    ).toHaveTextContent("Submitting…");
    expect(screen.getByRole("button", { name: "Submit Alpha Update for review" })).toBeDisabled();

    const betaToggle = screen.getByText("Beta Update").closest("button")!;
    await user.click(betaToggle);
    await user.click(screen.getByRole("button", { name: "Submit Beta Update for review" }));
    expect(screen.getByRole("button", { name: "Submit Beta Update for review" })).toHaveTextContent(
      "Submitting…",
    );
    expect(mockedSubmitForReview).toHaveBeenCalledTimes(2);

    const alphaToggle = screen.getByText("Alpha Update").closest("button")!;
    if (alphaToggle.getAttribute("aria-expanded") !== "true") {
      await user.click(alphaToggle);
    }
    expect(
      screen.getByRole("button", { name: "Submit Alpha Update for review" }),
    ).toHaveTextContent("Submitting…");
    await user.click(screen.getByRole("button", { name: "Submit Alpha Update for review" }));
    expect(mockedSubmitForReview).toHaveBeenCalledTimes(2);

    pendingB.resolve(
      communicationFixture({
        id: "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb",
        subject: "Beta Update",
        status: "in_review",
        body_approved: "Evidence-backed delivery update.",
      }),
    );
    await waitFor(() => expect(mockedSubmitForReview).toHaveBeenCalledTimes(2));
    const betaHeader = screen.getByText("Beta Update").closest("button")!;
    if (betaHeader.getAttribute("aria-expanded") !== "true") {
      await user.click(betaHeader);
    }
    expect(await screen.findByText("Submitted for review: Beta Update")).toBeInTheDocument();
    if (alphaToggle.getAttribute("aria-expanded") !== "true") {
      await user.click(alphaToggle);
    }
    expect(
      screen.getByRole("button", { name: "Submit Alpha Update for review" }),
    ).toHaveTextContent("Submitting…");

    pendingA.resolve(
      communicationFixture({
        id: "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa",
        subject: "Alpha Update",
        status: "in_review",
        body_approved: "Evidence-backed delivery update.",
      }),
    );
    expect(await screen.findByText("Submitted for review: Alpha Update")).toBeInTheDocument();
  });

  it("keeps per-item error feedback and does not leak notices across projects", async () => {
    const user = userEvent.setup();
    const pending = deferred<ClientCommunicationDraft>();
    mockedListCommunications.mockImplementation(async (projectId) => {
      if (projectId === projects[0].id) {
        return [
          communicationFixture({
            id: "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa",
            subject: "Atlas Draft",
            status: "in_review",
            body_approved: "Reviewed body",
            reviewed_at: "2026-07-16T13:00:00Z",
          }),
        ];
      }
      return [
        communicationFixture({
          id: "cccccccc-cccc-4ccc-8ccc-cccccccccccc",
          subject: "Borealis Draft",
          project_id: projects[1].id,
        }),
      ];
    });
    mockedApproveCommunication.mockReturnValueOnce(pending.promise);
    renderDashboard();
    const table = await screen.findByRole("table", { name: "Authorized client projects" });
    await user.click(within(table).getByRole("button", { name: "View Atlas Delivery" }));
    await user.click(await screen.findByText("Atlas Draft"));
    await user.click(screen.getByRole("button", { name: "Approve Atlas Draft" }));
    expect(screen.getByRole("button", { name: "Approve Atlas Draft" })).toHaveTextContent(
      "Approving…",
    );

    await user.click(within(table).getByRole("button", { name: "View Borealis Review" }));
    expect(await screen.findByText("Borealis Draft")).toBeInTheDocument();
    expect(screen.queryByText("Approving…")).not.toBeInTheDocument();
    expect(screen.queryByText(/Approved: Atlas Draft/)).not.toBeInTheDocument();

    pending.reject(new ApiError(409, "INVALID_COMMUNICATION_STATUS_TRANSITION", "Cannot approve."));
    await waitFor(() => expect(screen.queryByText("Cannot approve.")).not.toBeInTheDocument());
    expect(screen.getByText("Borealis Draft")).toBeInTheDocument();
  });

  it("preserves previous status when a lifecycle mutation fails", async () => {
    const user = userEvent.setup();
    mockedListCommunications.mockResolvedValue([
      communicationFixture({
        status: "in_review",
        body_approved: "Reviewed body",
        reviewed_at: "2026-07-16T13:00:00Z",
      }),
    ]);
    mockedApproveCommunication.mockRejectedValueOnce(
      new ApiError(409, "INVALID_COMMUNICATION_STATUS_TRANSITION", "Cannot approve."),
    );
    renderDashboard();
    await openQueueItem(user, "Weekly Client Update");
    await user.click(screen.getByRole("button", { name: "Approve Weekly Client Update" }));
    expect(await screen.findByText("Cannot approve.")).toBeInTheDocument();
    expect(screen.getByText("In Review")).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: "Approve Weekly Client Update" }),
    ).toBeInTheDocument();
  });

  it("disables Save for unchanged draft text", async () => {
    const user = userEvent.setup();
    mockedListCommunications.mockResolvedValue([communicationFixture()]);
    renderDashboard();
    await openQueueItem(user, "Weekly Client Update");
    await user.click(screen.getByRole("button", { name: "Edit draft Weekly Client Update" }));
    expect(screen.getByRole("button", { name: "Save draft Weekly Client Update" })).toBeDisabled();
    expect(mockedEditDraft).not.toHaveBeenCalled();
  });

  it("keeps Save enabled for rejected same-text revise", async () => {
    const user = userEvent.setup();
    mockedListCommunications.mockResolvedValue([
      communicationFixture({
        status: "rejected",
        rejection_reason: "Needs revision",
        rejected_at: "2026-07-16T15:00:00Z",
      }),
    ]);
    renderDashboard();
    await openQueueItem(user, "Weekly Client Update");
    await user.click(screen.getByRole("button", { name: "Edit and revise Weekly Client Update" }));
    expect(screen.getByRole("button", { name: "Save draft Weekly Client Update" })).toBeEnabled();
  });

  it("invalidates queue, master, and summary queries after a successful lifecycle mutation", async () => {
    const user = userEvent.setup();
    mockedListCommunications.mockResolvedValue([communicationFixture()]);
    mockedSubmitForReview.mockResolvedValue(
      communicationFixture({
        status: "in_review",
        body_approved: "Evidence-backed delivery update.",
      }),
    );
    renderDashboard();
    await openQueueItem(user, "Weekly Client Update");
    const masterCalls = mockedFetchMaster.mock.calls.length;
    const summaryCalls = mockedFetchSummary.mock.calls.length;
    const listCalls = mockedListCommunications.mock.calls.length;
    await user.click(
      screen.getByRole("button", { name: "Submit Weekly Client Update for review" }),
    );
    await waitFor(() => expect(mockedFetchMaster.mock.calls.length).toBeGreaterThan(masterCalls));
    await waitFor(() => expect(mockedFetchSummary.mock.calls.length).toBeGreaterThan(summaryCalls));
    await waitFor(() =>
      expect(mockedListCommunications.mock.calls.length).toBeGreaterThan(listCalls),
    );
  });

  it("keeps evidence links visible across lifecycle statuses and never requests before selection", async () => {
    renderDashboard();
    expect(mockedListCommunications).not.toHaveBeenCalled();
    expect(mockedEditDraft).not.toHaveBeenCalled();
    const user = userEvent.setup();
    mockedListCommunications.mockResolvedValue([
      communicationFixture({
        status: "approved",
        body_approved: "Approved body",
        approved_at: "2026-07-16T14:00:00Z",
      }),
    ]);
    await openQueueItem(user, "Weekly Client Update");
    expect(screen.getByText(/Latest governed throughput snapshot/)).toBeInTheDocument();
  });

  it("never shows another project's drafts after switching selection", async () => {
    const user = userEvent.setup();
    mockedListCommunications.mockImplementation(async (projectId) => {
      if (projectId === projects[0].id) {
        return [communicationFixture({ subject: "Atlas Draft" })];
      }
      return [
        communicationFixture({
          id: "cccccccc-cccc-4ccc-8ccc-cccccccccccc",
          subject: "Borealis Draft",
          project_id: projects[1].id,
        }),
      ];
    });
    renderDashboard();
    const table = await screen.findByRole("table", { name: "Authorized client projects" });
    await user.click(within(table).getByRole("button", { name: "View Atlas Delivery" }));
    expect(await screen.findByText("Atlas Draft")).toBeInTheDocument();
    await user.click(within(table).getByRole("button", { name: "View Borealis Review" }));
    expect(await screen.findByText("Borealis Draft")).toBeInTheDocument();
    expect(screen.queryByText("Atlas Draft")).not.toBeInTheDocument();
  });

  it("does not request report history before project selection", async () => {
    renderDashboard();
    await waitFor(() => expect(mockedFetchSummary).toHaveBeenCalled());
    expect(mockedFetchReportHistory).not.toHaveBeenCalled();
  });

  it("loads selected-project report history with approved body only", async () => {
    const user = userEvent.setup();
    mockedFetchReportHistory.mockResolvedValue(
      historyPage([historyItemFixture({ subject: "History Weekly Update" })]),
    );
    renderDashboard();
    const table = await screen.findByRole("table", { name: "Authorized client projects" });
    await user.click(within(table).getByRole("button", { name: "View Atlas Delivery" }));
    expect(await screen.findByLabelText("Approved and sent report history")).toBeInTheDocument();
    await waitFor(() =>
      expect(mockedFetchReportHistory).toHaveBeenCalledWith(
        projects[0].id,
        expect.objectContaining({ offset: 0, status: "all" }),
      ),
    );
    expect(mockedFetchReportHistory.mock.calls.every(([id]) => id === projects[0].id)).toBe(true);
    await user.click(screen.getByRole("button", { name: "Expand report History Weekly Update" }));
    expect(screen.getByText("Final approved narrative.")).toBeInTheDocument();
    expect(screen.queryByText("Draft body must not appear.")).not.toBeInTheDocument();
    expect(screen.getByText(/History evidence link/)).toBeInTheDocument();
  });

  it("deduplicates overlapping infinite pages by communication_id", async () => {
    const user = userEvent.setup();
    const sharedId = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa";
    mockedFetchReportHistory.mockImplementation(async (_projectId, params = {}) => {
      if ((params.offset ?? 0) === 0) {
        return historyPage(
          [
            historyItemFixture({
              communication_id: sharedId,
              subject: "Shared History Report",
              status: "approved",
            }),
          ],
          { total: 2, has_more: true },
        );
      }
      return historyPage(
        [
          historyItemFixture({
            communication_id: sharedId,
            subject: "Shared History Report",
            status: "sent",
            sent_at: "2026-07-16T16:00:00Z",
            history_at: "2026-07-16T16:00:00Z",
          }),
        ],
        { offset: params.offset ?? 1, total: 2, has_more: false },
      );
    });
    renderDashboard();
    const table = await screen.findByRole("table", { name: "Authorized client projects" });
    await user.click(within(table).getByRole("button", { name: "View Atlas Delivery" }));
    expect(await screen.findByText("Shared History Report")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Load more report history" }));
    await waitFor(() =>
      expect(
        mockedFetchReportHistory.mock.calls.some(([, params]) => (params?.offset ?? 0) > 0),
      ).toBe(true),
    );
    const historySection = screen.getByLabelText("Approved and sent report history");
    expect(
      within(historySection).getAllByRole("button", {
        name: "Expand report Shared History Report",
      }),
    ).toHaveLength(1);
  });

  it("applies All/Approved/Sent filters and resets pagination", async () => {
    const user = userEvent.setup();
    mockedFetchReportHistory.mockImplementation(async (_projectId, params = {}) => {
      if (params.status === "approved") {
        return historyPage([], {
          total: 0,
          status_filter: "approved",
        });
      }
      if (params.status === "sent") {
        return historyPage(
          [
            historyItemFixture({
              subject: "Sent Only Report",
              status: "sent",
              sent_at: "2026-07-16T14:00:00Z",
              history_at: "2026-07-16T14:00:00Z",
            }),
          ],
          { status_filter: "sent", total: 1 },
        );
      }
      return historyPage([historyItemFixture({ subject: "All Filter Report" })], { total: 1 });
    });
    renderDashboard();
    const table = await screen.findByRole("table", { name: "Authorized client projects" });
    await user.click(within(table).getByRole("button", { name: "View Atlas Delivery" }));
    expect(await screen.findByText("All Filter Report")).toBeInTheDocument();
    expect(mockedFetchReportHistory).toHaveBeenCalledWith(
      projects[0].id,
      expect.objectContaining({ status: "all", offset: 0 }),
    );

    await user.click(screen.getByRole("button", { name: "Show approved reports" }));
    expect(await screen.findByText("No approved reports for this project.")).toBeInTheDocument();
    expect(mockedFetchReportHistory).toHaveBeenCalledWith(
      projects[0].id,
      expect.objectContaining({ status: "approved", offset: 0 }),
    );

    await user.click(screen.getByRole("button", { name: "Show sent reports" }));
    expect(await screen.findByText("Sent Only Report")).toBeInTheDocument();
    expect(screen.queryByText("All Filter Report")).not.toBeInTheDocument();
    expect(mockedFetchReportHistory).toHaveBeenCalledWith(
      projects[0].id,
      expect.objectContaining({ status: "sent", offset: 0 }),
    );

    await user.click(screen.getByRole("button", { name: "Show all reports" }));
    expect(await screen.findByText("All Filter Report")).toBeInTheDocument();
  });

  it("appends load-more pages, prevents duplicate requests, and hides load more when done", async () => {
    const user = userEvent.setup();
    const secondPage = deferred<ClientIntelligenceReportHistory>();
    mockedFetchReportHistory.mockImplementation(async (_projectId, params = {}) => {
      if ((params.offset ?? 0) === 0) {
        return historyPage(
          [
            historyItemFixture({
              subject: "Page One Report",
              communication_id: "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa",
            }),
          ],
          { total: 2, has_more: true },
        );
      }
      return secondPage.promise;
    });
    renderDashboard();
    const table = await screen.findByRole("table", { name: "Authorized client projects" });
    await user.click(within(table).getByRole("button", { name: "View Atlas Delivery" }));
    expect(await screen.findByText("Page One Report")).toBeInTheDocument();
    const loadMore = screen.getByRole("button", { name: "Load more report history" });
    await user.click(loadMore);
    expect(screen.getByRole("button", { name: "Load more report history" })).toBeDisabled();
    await user.click(screen.getByRole("button", { name: "Load more report history" }));
    expect(
      mockedFetchReportHistory.mock.calls.filter(([, params]) => (params?.offset ?? 0) > 0),
    ).toHaveLength(1);
    secondPage.resolve(
      historyPage(
        [
          historyItemFixture({
            subject: "Page Two Report",
            communication_id: "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb",
          }),
        ],
        { offset: 1, total: 2, has_more: false },
      ),
    );
    expect(await screen.findByText("Page Two Report")).toBeInTheDocument();
    expect(screen.getByText("Page One Report")).toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: "Load more report history" }),
    ).not.toBeInTheDocument();
  });

  it("keeps Draft Queue usable when report history fails and restores on retry", async () => {
    const user = userEvent.setup();
    mockedListCommunications.mockResolvedValue([
      communicationFixture({ subject: "Queue Survives History Error" }),
    ]);
    mockedFetchReportHistory.mockRejectedValueOnce(
      new ApiError(500, "INTERNAL_ERROR", "History unavailable."),
    );
    renderDashboard();
    const table = await screen.findByRole("table", { name: "Authorized client projects" });
    await user.click(within(table).getByRole("button", { name: "View Atlas Delivery" }));
    expect(await screen.findByText("Queue Survives History Error")).toBeInTheDocument();
    expect(await screen.findByText("Report history could not be loaded.")).toBeInTheDocument();
    expect(screen.getByText("Draft Reports Queue")).toBeInTheDocument();
    expect(screen.getAllByText("87.50%").length).toBeGreaterThan(0);

    mockedFetchReportHistory.mockResolvedValue(
      historyPage([historyItemFixture({ subject: "Restored History Report" })]),
    );
    await user.click(screen.getByRole("button", { name: "Retry report history" }));
    expect(await screen.findByText("Restored History Report")).toBeInTheDocument();
    expect(screen.getByText("Queue Survives History Error")).toBeInTheDocument();
  });

  it("selected-project refresh reloads only that project history and hides stale cache on failure", async () => {
    const user = userEvent.setup();
    mockedFetchReportHistory.mockResolvedValue(
      historyPage([historyItemFixture({ subject: "Cached History Report" })]),
    );
    renderDashboard();
    const table = await screen.findByRole("table", { name: "Authorized client projects" });
    await user.click(within(table).getByRole("button", { name: "View Atlas Delivery" }));
    expect(await screen.findByText("Cached History Report")).toBeInTheDocument();
    const callsBeforeRefresh = mockedFetchReportHistory.mock.calls.length;

    mockedFetchReportHistory.mockRejectedValue(
      new ApiError(500, "INTERNAL_ERROR", "Refresh failed."),
    );
    await user.click(screen.getByRole("button", { name: "Refresh overview" }));
    expect(await screen.findByText("Report history could not be loaded.")).toBeInTheDocument();
    expect(screen.queryByText("Cached History Report")).not.toBeInTheDocument();
    expect(screen.getByText("Draft Reports Queue")).toBeInTheDocument();
    expect(screen.getAllByText("87.50%").length).toBeGreaterThan(0);
    await waitFor(() =>
      expect(mockedFetchReportHistory.mock.calls.length).toBeGreaterThan(callsBeforeRefresh),
    );
    expect(mockedFetchReportHistory.mock.calls.every(([id]) => id === projects[0].id)).toBe(true);
    expect(mockedFetchReportHistory.mock.calls.some(([id]) => id === projects[1].id)).toBe(false);
  });

  it("approve shows the same communication in history without unrelated project requests", async () => {
    const user = userEvent.setup();
    const inReview = communicationFixture({
      status: "in_review",
      body_approved: "Approved body",
      reviewed_at: "2026-07-16T13:00:00Z",
      reviewed_by: "99999999-9999-9999-9999-999999999999",
    });
    const approved = communicationFixture({
      status: "approved",
      body_approved: "Approved body",
      approved_at: "2026-07-16T14:00:00Z",
      approved_by: "99999999-9999-9999-9999-999999999999",
      reviewed_at: "2026-07-16T13:00:00Z",
      reviewed_by: "99999999-9999-9999-9999-999999999999",
    });
    mockedListCommunications.mockResolvedValue([inReview]);
    mockedApproveCommunication.mockResolvedValue(approved);
    mockedFetchReportHistory.mockResolvedValue(historyPage([]));
    renderDashboard();
    await openQueueItem(user, "Weekly Client Update");
    const historySection = screen.getByLabelText("Approved and sent report history");
    expect(
      within(historySection).queryByRole("button", {
        name: "Expand report Weekly Client Update",
      }),
    ).not.toBeInTheDocument();
    const historyCallsBefore = mockedFetchReportHistory.mock.calls.length;
    mockedListCommunications.mockResolvedValue([approved]);
    mockedFetchReportHistory.mockResolvedValue(
      historyPage([
        historyItemFixture({
          communication_id: approved.id,
          subject: "Weekly Client Update",
          approved_body: "Approved body",
          status: "approved",
          approved_at: approved.approved_at,
          approved_by: approved.approved_by,
          history_at: approved.approved_at,
          evidence_links: approved.evidence_links,
        }),
      ]),
    );
    await user.click(screen.getByRole("button", { name: "Approve Weekly Client Update" }));
    expect(
      await screen.findByRole("button", { name: "Send Weekly Client Update" }),
    ).toBeInTheDocument();
    await waitFor(() =>
      expect(mockedFetchReportHistory.mock.calls.length).toBeGreaterThan(historyCallsBefore),
    );
    expect(
      within(historySection).getByRole("button", { name: "Expand report Weekly Client Update" }),
    ).toBeInTheDocument();
    expect(mockedApproveCommunication).toHaveBeenCalledWith(approved.id);
    expect(mockedFetchReportHistory.mock.calls.every(([id]) => id === projects[0].id)).toBe(true);
    expect(mockedFetchReportHistory.mock.calls.some(([id]) => id === projects[1].id)).toBe(false);
  });

  it("send reconciles the same communication to Sent in history and announces success", async () => {
    const user = userEvent.setup();
    const approved = communicationFixture({
      status: "approved",
      body_approved: "Approved body",
      approved_at: "2026-07-16T14:00:00Z",
      approved_by: "99999999-9999-9999-9999-999999999999",
    });
    const sent = communicationFixture({
      status: "sent",
      body_approved: "Approved body",
      approved_at: "2026-07-16T14:00:00Z",
      approved_by: "99999999-9999-9999-9999-999999999999",
      sent_at: "2026-07-16T16:00:00Z",
    });
    mockedListCommunications.mockResolvedValue([approved]);
    mockedFetchReportHistory.mockResolvedValue(
      historyPage([
        historyItemFixture({
          communication_id: approved.id,
          subject: "Weekly Client Update",
          approved_body: "Approved body",
          status: "approved",
          approved_at: approved.approved_at,
          approved_by: approved.approved_by,
          history_at: approved.approved_at,
          evidence_links: approved.evidence_links,
        }),
      ]),
    );
    mockedSendCommunication.mockResolvedValue(sent);
    renderDashboard();
    await openQueueItem(user, "Weekly Client Update");
    const historySection = screen.getByLabelText("Approved and sent report history");
    expect(
      within(historySection).getByRole("button", { name: "Expand report Weekly Client Update" }),
    ).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Send Weekly Client Update" })).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Send Weekly Client Update" }));
    mockedListCommunications.mockResolvedValue([]);
    mockedFetchReportHistory.mockResolvedValue(
      historyPage([
        historyItemFixture({
          communication_id: approved.id,
          subject: "Weekly Client Update",
          approved_body: "Approved body",
          status: "sent",
          approved_at: approved.approved_at,
          approved_by: approved.approved_by,
          sent_at: sent.sent_at,
          history_at: sent.sent_at,
          evidence_links: approved.evidence_links,
        }),
      ]),
    );
    await user.click(screen.getByRole("button", { name: "Confirm send Weekly Client Update" }));

    expect(await screen.findByText("Sent: Weekly Client Update")).toBeInTheDocument();
    expect(screen.getByText("No draft reports for this project.")).toBeInTheDocument();
    await waitFor(() => {
      expect(
        within(historySection).getAllByRole("button", {
          name: "Expand report Weekly Client Update",
        }),
      ).toHaveLength(1);
    });
    await user.click(
      within(historySection).getByRole("button", { name: "Expand report Weekly Client Update" }),
    );
    expect(
      within(historySection).getByText((content, element) => {
        return element?.tagName === "P" && content.startsWith("Sent ");
      }),
    ).toBeInTheDocument();
    expect(mockedSendCommunication).toHaveBeenCalledWith(approved.id);
  });

  it("presents partial and unavailable provenance without fabricating actors or draft bodies", async () => {
    const user = userEvent.setup();
    mockedFetchReportHistory.mockResolvedValue(
      historyPage([
        historyItemFixture({
          communication_id: "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa",
          subject: "Partial Provenance Report",
          provenance_availability: "partial",
          limitations: ["REPORT_REVIEW_PROVENANCE_INCOMPLETE", "REPORT_APPROVER_MISSING"],
          approved_by: null,
          reviewed_by: null,
          reviewed_at: null,
          approved_at: "2026-07-16T13:00:00Z",
          sent_at: null,
        }),
        historyItemFixture({
          communication_id: "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb",
          subject: "Unavailable Provenance Report",
          approved_body: null,
          provenance_availability: "unavailable",
          limitations: ["REPORT_APPROVED_BODY_MISSING"],
          approved_at: null,
          approved_by: null,
          sent_at: null,
          history_at: null,
          evidence_links: [
            {
              id: "cccccccc-cccc-4ccc-8ccc-cccccccccccc",
              source_table: "throughput_snapshots",
              source_row_id: "dddddddd-dddd-4ddd-8ddd-dddddddddddd",
              description: "Unavailable-row evidence.",
              created_at: "2026-07-16T12:00:00Z",
            },
          ],
        }),
      ]),
    );
    renderDashboard();
    const table = await screen.findByRole("table", { name: "Authorized client projects" });
    await user.click(within(table).getByRole("button", { name: "View Atlas Delivery" }));
    expect(await screen.findByText("Partial Provenance Report")).toBeInTheDocument();
    expect(screen.getByText("Unavailable Provenance Report")).toBeInTheDocument();

    await user.click(
      screen.getByRole("button", { name: "Expand report Partial Provenance Report" }),
    );
    expect(screen.getByText("Report Review Provenance Incomplete")).toBeInTheDocument();
    expect(screen.getByText("Report Approver Missing")).toBeInTheDocument();
    expect(screen.getByText(/Approved Jul/)).toBeInTheDocument();
    expect(screen.queryByText("99999999-9999-9999-9999-999999999999")).not.toBeInTheDocument();

    await user.click(
      screen.getByRole("button", { name: "Expand report Unavailable Provenance Report" }),
    );
    expect(
      screen.getByText("Approved body unavailable for this legacy record."),
    ).toBeInTheDocument();
    expect(screen.queryByText("Evidence-backed delivery update.")).not.toBeInTheDocument();
    expect(screen.getByText(/Unavailable-row evidence/)).toBeInTheDocument();
  });

  it("clears accumulated history pages and filter when switching projects", async () => {
    const user = userEvent.setup();
    mockedFetchReportHistory.mockImplementation(async (projectId) =>
      historyPage(
        [
          historyItemFixture({
            project_id: projectId,
            communication_id:
              projectId === projects[0].id
                ? "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
                : "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb",
            subject:
              projectId === projects[0].id ? "Atlas History Report" : "Borealis History Report",
            status: projectId === projects[0].id ? "sent" : "approved",
            sent_at: projectId === projects[0].id ? "2026-07-16T14:00:00Z" : null,
            history_at:
              projectId === projects[0].id ? "2026-07-16T14:00:00Z" : "2026-07-16T13:00:00Z",
          }),
        ],
        { project_id: projectId, total: 1 },
      ),
    );
    renderDashboard();
    const table = await screen.findByRole("table", { name: "Authorized client projects" });
    await user.click(within(table).getByRole("button", { name: "View Atlas Delivery" }));
    expect(await screen.findByText("Atlas History Report")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Show sent reports" }));
    await user.click(within(table).getByRole("button", { name: "View Borealis Review" }));
    expect(await screen.findByText("Borealis History Report")).toBeInTheDocument();
    expect(screen.queryByText("Atlas History Report")).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Show all reports" })).toBeDisabled();
  });
});

describe("ClientIntelligenceDashboard Q&A", () => {
  it("does not request question history or ask before project selection", async () => {
    renderDashboard();
    await waitFor(() => expect(mockedFetchSummary).toHaveBeenCalled());
    expect(mockedFetchQueryHistory).not.toHaveBeenCalled();
    expect(mockedCreateQuery).not.toHaveBeenCalled();
  });

  it("loads question history scoped to the selected project", async () => {
    const user = userEvent.setup();
    mockedFetchQueryHistory.mockResolvedValue(
      queryHistoryPage([queryItemFixture({ question: "What is the delivery confidence trend?" })]),
    );
    renderDashboard();
    const table = await screen.findByRole("table", { name: "Authorized client projects" });
    await user.click(within(table).getByRole("button", { name: "View Atlas Delivery" }));
    expect(await screen.findByText("What is the delivery confidence trend?")).toBeInTheDocument();
    await waitFor(() =>
      expect(mockedFetchQueryHistory).toHaveBeenCalledWith(
        projects[0].id,
        expect.objectContaining({ offset: 0 }),
      ),
    );
    expect(mockedFetchQueryHistory.mock.calls.every(([id]) => id === projects[0].id)).toBe(true);
  });

  it("submits a trimmed question to the create endpoint for the selected project", async () => {
    const user = userEvent.setup();
    mockedCreateQuery.mockResolvedValue(queryItemFixture());
    renderDashboard();
    const table = await screen.findByRole("table", { name: "Authorized client projects" });
    await user.click(within(table).getByRole("button", { name: "View Atlas Delivery" }));
    const qaSection = await screen.findByLabelText("Client Intelligence Q&A");
    const textarea = within(qaSection).getByLabelText("Client Intelligence question");
    await user.type(textarea, "  What is the delivery confidence?  ");
    await user.click(within(qaSection).getByRole("button", { name: "Ask Client Intelligence" }));
    await waitFor(() =>
      expect(mockedCreateQuery).toHaveBeenCalledWith(
        projects[0].id,
        "What is the delivery confidence?",
      ),
    );
  });

  it("blocks a blank question submission without calling the API", async () => {
    const user = userEvent.setup();
    renderDashboard();
    const table = await screen.findByRole("table", { name: "Authorized client projects" });
    await user.click(within(table).getByRole("button", { name: "View Atlas Delivery" }));
    const qaSection = await screen.findByLabelText("Client Intelligence Q&A");
    await user.click(within(qaSection).getByRole("button", { name: "Ask Client Intelligence" }));
    expect(
      await within(qaSection).findByText("Enter a question before asking."),
    ).toBeInTheDocument();
    expect(mockedCreateQuery).not.toHaveBeenCalled();
  });

  it("prevents duplicate ask submissions while a request is pending", async () => {
    const user = userEvent.setup();
    const pending = deferred<ClientIntelligenceQueryRead>();
    mockedCreateQuery.mockReturnValue(pending.promise);
    renderDashboard();
    const table = await screen.findByRole("table", { name: "Authorized client projects" });
    await user.click(within(table).getByRole("button", { name: "View Atlas Delivery" }));
    const qaSection = await screen.findByLabelText("Client Intelligence Q&A");
    const textarea = within(qaSection).getByLabelText("Client Intelligence question");
    await user.type(textarea, "What is the delivery confidence?");
    const askButton = within(qaSection).getByRole("button", {
      name: "Ask Client Intelligence",
    });
    await user.click(askButton);
    expect(
      within(qaSection).getByRole("button", { name: "Ask Client Intelligence" }),
    ).toBeDisabled();
    await user.click(within(qaSection).getByRole("button", { name: "Ask Client Intelligence" }));
    expect(mockedCreateQuery).toHaveBeenCalledTimes(1);
    pending.resolve(queryItemFixture());
    await waitFor(() =>
      expect(
        within(qaSection).getByRole("button", { name: "Ask Client Intelligence" }),
      ).not.toBeDisabled(),
    );
  });

  it("shows a single success notice and the new question after the ask succeeds", async () => {
    const user = userEvent.setup();
    const created = queryItemFixture({
      query_id: "abababab-abab-4bab-8bab-abababababab",
      question: "What is the delivery confidence?",
    });
    mockedCreateQuery.mockResolvedValue(created);
    renderDashboard();
    const table = await screen.findByRole("table", { name: "Authorized client projects" });
    await user.click(within(table).getByRole("button", { name: "View Atlas Delivery" }));
    const qaSection = await screen.findByLabelText("Client Intelligence Q&A");
    mockedFetchQueryHistory.mockResolvedValue(queryHistoryPage([created]));
    const textarea = within(qaSection).getByLabelText("Client Intelligence question");
    await user.type(textarea, "What is the delivery confidence?");
    await user.click(within(qaSection).getByRole("button", { name: "Ask Client Intelligence" }));
    expect(await within(qaSection).findAllByText("Answer ready.")).toHaveLength(1);
    expect(mockedCreateQuery).toHaveBeenCalledTimes(1);
    expect(
      await within(qaSection).findByText("What is the delivery confidence?"),
    ).toBeInTheDocument();
    expect(textarea).toHaveValue("");
  });

  it("shows formatted latency in the collapsed question row", async () => {
    mockedFetchQueryHistory.mockResolvedValue(
      queryHistoryPage([queryItemFixture({ latency_ms: 1500, question: "Latency test question" })]),
    );
    const user = userEvent.setup();
    renderDashboard();
    const table = await screen.findByRole("table", { name: "Authorized client projects" });
    await user.click(within(table).getByRole("button", { name: "View Atlas Delivery" }));
    expect(await screen.findByText("Latency test question")).toBeInTheDocument();
    expect(screen.getByText(/1\.5 s/)).toBeInTheDocument();
  });

  it("surfaces insufficient evidence and escalation guidance when expanded", async () => {
    const user = userEvent.setup();
    const question = "Is the project at risk of missing the milestone?";
    mockedFetchQueryHistory.mockResolvedValue(
      queryHistoryPage([
        queryItemFixture({
          query_id: "cccccccc-cccc-4ccc-8ccc-cccccccccccc",
          question,
          answer_availability: "insufficient_evidence",
          confidence_level: "insufficient",
          insufficient_evidence: true,
          escalation_required: true,
          next_step: "Escalate to the delivery manager for a milestone review.",
          limitations: ["MILESTONE_EVIDENCE_UNAVAILABLE"],
          evidence_links: [],
        }),
      ]),
    );
    renderDashboard();
    const table = await screen.findByRole("table", { name: "Authorized client projects" });
    await user.click(within(table).getByRole("button", { name: "View Atlas Delivery" }));
    expect(await screen.findByText(question)).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: `Expand answer for ${question}` }));
    expect(screen.getByText("Insufficient evidence to answer this question.")).toBeInTheDocument();
    expect(screen.getByText("Escalation required")).toBeInTheDocument();
    expect(
      screen.getByText("Escalate to the delivery manager for a milestone review."),
    ).toBeInTheDocument();
    expect(screen.getByText("Milestone Evidence Unavailable")).toBeInTheDocument();
  });

  it("shows an ask error scoped to the Q&A section without affecting other sections", async () => {
    const user = userEvent.setup();
    mockedListCommunications.mockResolvedValue([
      communicationFixture({ subject: "Untouched Draft" }),
    ]);
    mockedCreateQuery.mockRejectedValue(
      new ApiError(500, "INTERNAL_ERROR", "The Q&A provider is unavailable."),
    );
    renderDashboard();
    const table = await screen.findByRole("table", { name: "Authorized client projects" });
    await user.click(within(table).getByRole("button", { name: "View Atlas Delivery" }));
    expect(await screen.findByText("Untouched Draft")).toBeInTheDocument();
    const qaSection = await screen.findByLabelText("Client Intelligence Q&A");
    const textarea = within(qaSection).getByLabelText("Client Intelligence question");
    await user.type(textarea, "What is the delivery confidence?");
    await user.click(within(qaSection).getByRole("button", { name: "Ask Client Intelligence" }));
    expect(
      await within(qaSection).findByText("Client Intelligence could not answer this question."),
    ).toBeInTheDocument();
    expect(screen.getByText("Untouched Draft")).toBeInTheDocument();
    expect(screen.getByText("Draft Reports Queue")).toBeInTheDocument();
  });

  it("refetches Avg Query Response summary after a successful ask", async () => {
    const user = userEvent.setup();
    mockedCreateQuery.mockResolvedValue(queryItemFixture());
    renderDashboard();
    const table = await screen.findByRole("table", { name: "Authorized client projects" });
    await user.click(within(table).getByRole("button", { name: "View Atlas Delivery" }));
    const qaSection = await screen.findByLabelText("Client Intelligence Q&A");
    const summaryCallsBefore = mockedFetchSummary.mock.calls.length;
    const textarea = within(qaSection).getByLabelText("Client Intelligence question");
    await user.type(textarea, "What is the delivery confidence?");
    await user.click(within(qaSection).getByRole("button", { name: "Ask Client Intelligence" }));
    expect(await within(qaSection).findByText("Answer ready.")).toBeInTheDocument();
    await waitFor(() =>
      expect(mockedFetchSummary.mock.calls.length).toBeGreaterThan(summaryCallsBefore),
    );
  });

  it("does not show provider_unavailable as a successful grounded answer", async () => {
    const user = userEvent.setup();
    const question = "What is project health while the provider is offline?";
    mockedFetchQueryHistory.mockResolvedValue(
      queryHistoryPage([
        queryItemFixture({
          query_id: "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb",
          question,
          answer_availability: "provider_unavailable",
          confidence_level: "insufficient",
          insufficient_evidence: false,
          answer_text: "The language model provider is unavailable; no fluent answer was invented.",
          limitations: ["LLM_PROVIDER_UNAVAILABLE"],
          next_step: "Retry when the provider is available, or rely on deterministic facts.",
          evidence_links: [],
        }),
      ]),
    );
    renderDashboard();
    const table = await screen.findByRole("table", { name: "Authorized client projects" });
    await user.click(within(table).getByRole("button", { name: "View Atlas Delivery" }));
    expect(await screen.findByText(question)).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: `Expand answer for ${question}` }));
    expect(screen.getByText(/Answer unavailable: Provider Unavailable/i)).toBeInTheDocument();
    expect(
      screen.queryByText("Insufficient evidence to answer this question."),
    ).not.toBeInTheDocument();
  });

  it("clears Q&A when project selection is lost", async () => {
    const user = userEvent.setup();
    mockedFetchQueryHistory.mockResolvedValue(
      queryHistoryPage([queryItemFixture({ question: "Atlas-only question" })]),
    );
    renderDashboard();
    const table = await screen.findByRole("table", { name: "Authorized client projects" });
    await user.click(within(table).getByRole("button", { name: "View Atlas Delivery" }));
    expect(await screen.findByText("Atlas-only question")).toBeInTheDocument();
    expect(screen.getByLabelText("Client Intelligence Q&A")).toBeInTheDocument();

    mockedListProjects.mockResolvedValue([projects[1]]);
    mockedFetchMaster.mockResolvedValue([masterRows[1]]);
    await user.click(screen.getByRole("button", { name: "Refresh projects" }));
    await waitFor(() => {
      expect(screen.queryByLabelText("Client Intelligence Q&A")).not.toBeInTheDocument();
    });
    expect(screen.queryByText("Atlas-only question")).not.toBeInTheDocument();
    expect(
      screen.getByText("Select a project row to view governed Client Intelligence."),
    ).toBeInTheDocument();
  });

  it("hides retained query history while a refresh error is shown", async () => {
    const user = userEvent.setup();
    mockedFetchQueryHistory.mockResolvedValue(
      queryHistoryPage([queryItemFixture({ question: "Cached question" })]),
    );
    renderDashboard();
    const table = await screen.findByRole("table", { name: "Authorized client projects" });
    await user.click(within(table).getByRole("button", { name: "View Atlas Delivery" }));
    expect(await screen.findByText("Cached question")).toBeInTheDocument();
    const callsBefore = mockedFetchQueryHistory.mock.calls.length;

    mockedFetchQueryHistory.mockRejectedValue(new Error("history offline"));
    await user.click(screen.getByRole("button", { name: "Refresh overview" }));
    expect(
      await screen.findByText(/Client Intelligence query history could not be loaded/i),
    ).toBeInTheDocument();
    expect(screen.queryByText("Cached question")).not.toBeInTheDocument();
    await waitFor(() =>
      expect(mockedFetchQueryHistory.mock.calls.length).toBeGreaterThan(callsBefore),
    );
    expect(mockedFetchQueryHistory.mock.calls.every(([id]) => id === projects[0].id)).toBe(true);
  });

  it("deduplicates overlapping question history pages by query_id", async () => {
    const user = userEvent.setup();
    const sharedId = "dddddddd-dddd-4ddd-8ddd-dddddddddddd";
    mockedFetchQueryHistory.mockImplementation(async (_projectId, params = {}) => {
      if ((params.offset ?? 0) === 0) {
        return queryHistoryPage(
          [queryItemFixture({ query_id: sharedId, question: "Shared question" })],
          { total: 2, has_more: true },
        );
      }
      return queryHistoryPage(
        [queryItemFixture({ query_id: sharedId, question: "Shared question" })],
        { offset: params.offset ?? 1, total: 2, has_more: false },
      );
    });
    renderDashboard();
    const table = await screen.findByRole("table", { name: "Authorized client projects" });
    await user.click(within(table).getByRole("button", { name: "View Atlas Delivery" }));
    expect(await screen.findByText("Shared question")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Load more Client Intelligence queries" }));
    await waitFor(() =>
      expect(
        mockedFetchQueryHistory.mock.calls.some(([, params]) => (params?.offset ?? 0) > 0),
      ).toBe(true),
    );
    const qaSection = screen.getByLabelText("Client Intelligence Q&A");
    expect(
      within(qaSection).getAllByRole("button", { name: "Expand answer for Shared question" }),
    ).toHaveLength(1);
  });

  it("clears accumulated question history when switching projects", async () => {
    const user = userEvent.setup();
    mockedFetchQueryHistory.mockImplementation(async (projectId) =>
      queryHistoryPage(
        [
          queryItemFixture({
            project_id: projectId,
            query_id:
              projectId === projects[0].id
                ? "eeeeeeee-eeee-4eee-8eee-eeeeeeeeeeee"
                : "ffffffff-ffff-4fff-8fff-ffffffffffff",
            question: projectId === projects[0].id ? "Atlas question" : "Borealis question",
          }),
        ],
        { project_id: projectId, total: 1 },
      ),
    );
    renderDashboard();
    const table = await screen.findByRole("table", { name: "Authorized client projects" });
    await user.click(within(table).getByRole("button", { name: "View Atlas Delivery" }));
    expect(await screen.findByText("Atlas question")).toBeInTheDocument();
    await user.click(within(table).getByRole("button", { name: "View Borealis Review" }));
    expect(await screen.findByText("Borealis question")).toBeInTheDocument();
    expect(screen.queryByText("Atlas question")).not.toBeInTheDocument();
  });

  it("renders Not measured for null latency and 0 ms for genuine zero", async () => {
    const user = userEvent.setup();
    mockedFetchQueryHistory.mockResolvedValue(
      queryHistoryPage([
        queryItemFixture({
          query_id: "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa",
          question: "Null latency question",
          latency_ms: null,
        }),
        queryItemFixture({
          query_id: "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb",
          question: "Zero latency question",
          latency_ms: 0,
        }),
      ]),
    );
    renderDashboard();
    const table = await screen.findByRole("table", { name: "Authorized client projects" });
    await user.click(within(table).getByRole("button", { name: "View Atlas Delivery" }));
    expect(await screen.findByText("Null latency question")).toBeInTheDocument();
    expect(screen.getByText(/Not measured/)).toBeInTheDocument();
    expect(screen.getByText("Zero latency question")).toBeInTheDocument();
    expect(screen.getByText(/0 ms/)).toBeInTheDocument();
  });

  it("ignores a late Project A ask result after switching to Project B", async () => {
    const user = userEvent.setup();
    const pending = deferred<ClientIntelligenceQueryRead>();
    mockedCreateQuery.mockReturnValue(pending.promise);
    mockedFetchQueryHistory.mockImplementation(async (projectId) =>
      queryHistoryPage(
        [
          queryItemFixture({
            project_id: projectId,
            query_id:
              projectId === projects[0].id
                ? "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
                : "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb",
            question: projectId === projects[0].id ? "Atlas history" : "Borealis history",
          }),
        ],
        { project_id: projectId },
      ),
    );
    renderDashboard();
    const table = await screen.findByRole("table", { name: "Authorized client projects" });
    await user.click(within(table).getByRole("button", { name: "View Atlas Delivery" }));
    const qaAtlas = await screen.findByLabelText("Client Intelligence Q&A");
    await user.type(
      within(qaAtlas).getByLabelText("Client Intelligence question"),
      "Late Atlas question",
    );
    await user.click(within(qaAtlas).getByRole("button", { name: "Ask Client Intelligence" }));
    await user.click(within(table).getByRole("button", { name: "View Borealis Review" }));
    expect(await screen.findByText("Borealis history")).toBeInTheDocument();
    const qaBorealis = screen.getByLabelText("Client Intelligence Q&A");
    pending.resolve(
      queryItemFixture({
        project_id: projects[0].id,
        query_id: "cccccccc-cccc-4ccc-8ccc-cccccccccccc",
        question: "Late Atlas question",
      }),
    );
    await waitFor(() => expect(mockedCreateQuery).toHaveBeenCalledTimes(1));
    expect(within(qaBorealis).queryByText("Answer ready.")).not.toBeInTheDocument();
    expect(within(qaBorealis).queryByText("Late Atlas question")).not.toBeInTheDocument();
    expect(screen.getByText("Borealis history")).toBeInTheDocument();
  });

  it("shows the returned persisted query once after ask success", async () => {
    const user = userEvent.setup();
    const created = queryItemFixture({
      query_id: "dddddddd-dddd-4ddd-8ddd-dddddddddddd",
      question: "What is the delivery confidence?",
    });
    mockedCreateQuery.mockResolvedValue(created);
    mockedFetchQueryHistory.mockResolvedValue(queryHistoryPage([]));
    renderDashboard();
    const table = await screen.findByRole("table", { name: "Authorized client projects" });
    await user.click(within(table).getByRole("button", { name: "View Atlas Delivery" }));
    const qaSection = await screen.findByLabelText("Client Intelligence Q&A");
    await user.type(
      within(qaSection).getByLabelText("Client Intelligence question"),
      "What is the delivery confidence?",
    );
    await user.click(within(qaSection).getByRole("button", { name: "Ask Client Intelligence" }));
    expect(await within(qaSection).findByText("Answer ready.")).toBeInTheDocument();
    expect(
      within(qaSection).getAllByRole("button", {
        name: "Expand answer for What is the delivery confidence?",
      }),
    ).toHaveLength(1);
  });

  it("keeps first query history page at 20 and loads displaced item at offset 20", async () => {
    const user = userEvent.setup();
    const firstPageItems = Array.from({ length: 20 }, (_, index) =>
      queryItemFixture({
        query_id: `aaaaaaaa-aaaa-4aaa-8aaa-${String(index).padStart(12, "0")}`,
        question: `Cached question ${index}`,
      }),
    );
    const twentieth = firstPageItems[19]!;
    const created = queryItemFixture({
      query_id: "dddddddd-dddd-4ddd-8ddd-dddddddddddd",
      question: "Fresh question after full page",
    });
    mockedFetchQueryHistory.mockImplementation(async (projectId, params = {}) => {
      const offset = params.offset ?? 0;
      if (offset === 0) {
        return queryHistoryPage(firstPageItems, { total: 21, has_more: true });
      }
      return queryHistoryPage([twentieth], {
        offset,
        total: 22,
        has_more: false,
      });
    });
    mockedCreateQuery.mockResolvedValue(created);

    const { queryClient } = renderDashboard();
    const table = await screen.findByRole("table", { name: "Authorized client projects" });
    await user.click(within(table).getByRole("button", { name: "View Atlas Delivery" }));
    const qaSection = await screen.findByLabelText("Client Intelligence Q&A");
    await within(qaSection).findByText("Cached question 0");

    await user.type(
      within(qaSection).getByLabelText("Client Intelligence question"),
      "Fresh question after full page",
    );
    await user.click(within(qaSection).getByRole("button", { name: "Ask Client Intelligence" }));
    expect(await within(qaSection).findByText("Answer ready.")).toBeInTheDocument();

    const historyKey = queryKeys.clientIntelligenceQueryHistory(projects[0].id);
    await waitFor(() => {
      const cached = queryClient.getQueryData<{
        pages: ClientIntelligenceQueryHistory[];
        pageParams: number[];
      }>(historyKey);
      expect(cached?.pages).toHaveLength(1);
      expect(cached?.pageParams).toEqual([0]);
      expect(cached?.pages[0]?.items).toHaveLength(20);
      expect(cached?.pages[0]?.total).toBe(22);
      expect(cached?.pages[0]?.has_more).toBe(true);
      expect(cached?.pages[0]?.items[0]?.query_id).toBe(created.query_id);
      expect(cached?.pages[0]?.items.some((item) => item.query_id === twentieth.query_id)).toBe(
        false,
      );
    });

    await user.click(
      within(qaSection).getByRole("button", { name: "Load more Client Intelligence queries" }),
    );
    await waitFor(() => {
      const loadMoreCalls = mockedFetchQueryHistory.mock.calls.filter(
        (call) => (call[1]?.offset ?? 0) > 0,
      );
      expect(loadMoreCalls.length).toBeGreaterThan(0);
      expect(loadMoreCalls[0]?.[1]?.offset).toBe(20);
    });
    expect(await within(qaSection).findByText(twentieth.question)).toBeInTheDocument();
    expect(
      within(qaSection).getAllByRole("button", {
        name: `Expand answer for ${created.question}`,
      }),
    ).toHaveLength(1);
  });

  it("keeps persisted answer visible when post-success history fetch fails without fabricating total=1", async () => {
    const user = userEvent.setup();
    const created = queryItemFixture({
      query_id: "ffffffff-ffff-4fff-8fff-ffffffffffff",
      question: "Visible without authoritative total",
    });
    mockedCreateQuery.mockResolvedValue(created);
    mockedFetchQueryHistory.mockRejectedValue(new Error("history down"));

    const { queryClient } = renderDashboard();
    const table = await screen.findByRole("table", { name: "Authorized client projects" });
    await user.click(within(table).getByRole("button", { name: "View Atlas Delivery" }));
    const qaSection = await screen.findByLabelText("Client Intelligence Q&A");
    expect(
      await within(qaSection).findByText(/query history could not be loaded/i),
    ).toBeInTheDocument();

    await user.type(
      within(qaSection).getByLabelText("Client Intelligence question"),
      "Visible without authoritative total",
    );
    await user.click(within(qaSection).getByRole("button", { name: "Ask Client Intelligence" }));
    expect(await within(qaSection).findByText("Answer ready.")).toBeInTheDocument();
    expect(
      await within(qaSection).findByText("Visible without authoritative total"),
    ).toBeInTheDocument();

    await waitFor(() => {
      const cached = queryClient.getQueryData<{
        pages: ClientIntelligenceQueryHistory[];
      }>(queryKeys.clientIntelligenceQueryHistory(projects[0].id));
      expect(cached?.pages[0]?.items[0]?.query_id).toBe(created.query_id);
      expect(cached?.pages[0]?.total).not.toBe(1);
      expect(
        cached?.pages[0]?.history_source === "unavailable" ||
          cached?.pages[0]?.history_source === "local_pending",
      ).toBe(true);
    });
  });

  it("leaves Project Health overview reads unchanged after a successful ask", async () => {
    const user = userEvent.setup();
    mockedCreateQuery.mockResolvedValue(queryItemFixture());
    renderDashboard();
    const table = await screen.findByRole("table", { name: "Authorized client projects" });
    await user.click(within(table).getByRole("button", { name: "View Atlas Delivery" }));
    const qaSection = await screen.findByLabelText("Client Intelligence Q&A");
    await screen.findByText("Project Health");
    const overviewCallsBefore = mockedFetchOverview.mock.calls.length;
    const healthStatusBefore = screen.getAllByText("Insufficient").length;
    const textarea = within(qaSection).getByLabelText("Client Intelligence question");
    await user.type(textarea, "What is the delivery confidence?");
    await user.click(within(qaSection).getByRole("button", { name: "Ask Client Intelligence" }));
    expect(await within(qaSection).findByText("Answer ready.")).toBeInTheDocument();
    expect(mockedFetchOverview.mock.calls.length).toBe(overviewCallsBefore);
    expect(screen.getAllByText("Insufficient").length).toBe(healthStatusBefore);
  });
});

describe("Client Intelligence role navigation", () => {
  it.each(["delivery_manager", "bsg_leadership", "super_admin"] as const)(
    "allows and exposes Client Intelligence for %s",
    (role) => {
      expect(canAccessPath(role, "/client-intelligence")).toBe(true);
      const labels = navForUser(userFor(role)).flatMap((section) =>
        section.items.map((item) => item.label),
      );
      expect(labels).toContain("Client Intelligence");
    },
  );

  it("does not allow or expose Client Intelligence for clients", () => {
    expect(canAccessPath("client", "/client-intelligence")).toBe(false);
    const labels = navForUser(userFor("client")).flatMap((section) =>
      section.items.map((item) => item.label),
    );
    expect(labels).not.toContain("Client Intelligence");
  });
});
