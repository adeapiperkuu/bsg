import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { GovernanceJobProgress } from "@/features/governance/GovernanceJobProgress";
import { useGovernanceJob } from "@/features/governance/useGovernanceJob";
import type { GovernanceJob } from "@/types/governance";

const discoveryMock = vi.fn();
const jobMock = vi.fn();

vi.mock("@/lib/queries/governance", () => ({
  governanceJobsQueryOptions: (params: Record<string, unknown>) => ({
    queryKey: ["governance", "jobs", params],
    queryFn: () => discoveryMock(params),
  }),
  governanceJobQueryOptions: (jobId: string) => ({
    queryKey: ["governance", "jobs", jobId],
    queryFn: () => jobMock(jobId),
  }),
  cancelGovernanceJob: vi.fn(),
  retryGovernanceJob: vi.fn(),
}));

function job(
  status: GovernanceJob["status"],
  overrides: Partial<GovernanceJob> = {},
): GovernanceJob {
  return {
    id: "job-1",
    org_id: "org-1",
    project_id: null,
    job_type: "weekly_summary_generate",
    status,
    progress_stage: status === "running" ? "generating" : status,
    progress_percent: status === "succeeded" ? 100 : 45,
    attempt_count: 1,
    max_attempts: 3,
    requested_at: "2026-07-15T08:00:00Z",
    started_at: "2026-07-15T08:00:01Z",
    completed_at: null,
    next_attempt_at: null,
    retryable: false,
    cancellable: status === "running" || status === "queued",
    error_code: null,
    error_message: null,
    result_record_type: null,
    result_record_id: null,
    result: null,
    ...overrides,
  };
}

function Harness({ enabled = true, onSucceeded = vi.fn() }) {
  const tracker = useGovernanceJob({
    jobType: "weekly_summary_generate",
    enabled,
    pollIntervalMs: 20,
    onSucceeded,
  });
  return (
    <GovernanceJobProgress
      job={tracker.job}
      onCancel={tracker.cancel}
      onRetry={tracker.retry}
      busy={tracker.controlBusy}
    />
  );
}

function renderHarness(props?: { enabled?: boolean; onSucceeded?: (job: GovernanceJob) => void }) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return render(
    <QueryClientProvider client={client}>
      <Harness {...props} />
    </QueryClientProvider>,
  );
}

describe("useGovernanceJob Phase F", () => {
  beforeEach(() => {
    discoveryMock.mockReset();
    jobMock.mockReset();
  });

  it("discovers an active job after refresh, polls, and stops after success", async () => {
    const onSucceeded = vi.fn();
    discoveryMock.mockResolvedValue([job("running")]);
    jobMock.mockResolvedValueOnce(job("running")).mockResolvedValue(job("succeeded"));

    renderHarness({ onSucceeded });
    await waitFor(() => expect(jobMock).toHaveBeenCalledTimes(1));
    expect(screen.getByText("Generating")).toBeInTheDocument();

    await waitFor(() => expect(onSucceeded).toHaveBeenCalledTimes(1));
    const callsAtSuccess = jobMock.mock.calls.length;
    await new Promise((resolve) => setTimeout(resolve, 80));
    expect(jobMock).toHaveBeenCalledTimes(callsAtSuccess);
  });

  it("renders safe failure information and retry availability", async () => {
    discoveryMock.mockResolvedValue([job("running")]);
    jobMock.mockResolvedValue(
      job("failed", {
        progress_stage: "failed",
        cancellable: false,
        retryable: true,
        error_code: "AI_TIMEOUT",
        error_message: "The AI provider timed out.",
      }),
    );

    renderHarness();
    expect(await screen.findByText("Failed")).toBeInTheDocument();
    expect(screen.getByText("The AI provider timed out.")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Retry" })).toBeInTheDocument();
  });

  it("does not discover or inspect jobs for a disabled role", async () => {
    discoveryMock.mockResolvedValue([]);
    renderHarness({ enabled: false });
    await Promise.resolve();
    expect(discoveryMock).not.toHaveBeenCalled();
    expect(jobMock).not.toHaveBeenCalled();
  });
});
