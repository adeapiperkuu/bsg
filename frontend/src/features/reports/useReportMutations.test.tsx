import type { ReactNode } from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { renderHook, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { useDraftCommunicationMutation } from "@/features/reports/useReportMutations";
import { reportQueryKeys } from "@/features/reports/useReportsQueries";
import type { CommunicationDetail } from "@/types/communications";

const mocks = vi.hoisted(() => ({
  createCommunicationDraft: vi.fn(),
}));

vi.mock("@/lib/api", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/lib/api")>();
  return {
    ...actual,
    createCommunicationDraft: mocks.createCommunicationDraft,
  };
});

const detail: CommunicationDetail = {
  id: "comm-new",
  project_id: "proj-1",
  project_name: "Project Alpha",
  comm_type: "weekly_summary",
  subject: "Weekly Delivery Summary — Project Alpha",
  body_draft: "Generated body",
  body_approved: null,
  status: "draft",
  drafted_by_agent: "client_interaction_agent",
  reviewed_by: null,
  reviewed_at: null,
  approved_by: null,
  approved_at: null,
  sent_at: null,
  created_at: "2026-07-16T10:00:00Z",
  updated_at: "2026-07-16T10:00:00Z",
  evidence_links: [
    {
      source_table: "throughput_snapshots",
      source_row_id: "e1",
      description: "Throughput",
    },
  ],
  generation_mode: "fallback",
  generation_warning: "The AI provider was unavailable. A temporary evidence-backed draft was created.",
};

describe("useDraftCommunicationMutation", () => {
  it("seeds detail cache and does not require a second detail fetch", async () => {
    mocks.createCommunicationDraft.mockResolvedValue(detail);
    const queryClient = new QueryClient({
      defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
    });
    queryClient.setQueryData(reportQueryKeys.list({ limit: 30, offset: 0 }), {
      data: [],
      pagination: { limit: 30, offset: 0, total: 0, items: 0, has_more: false },
    });

    const wrapper = ({ children }: { children: ReactNode }) => (
      <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>
    );

    const { result } = renderHook(() => useDraftCommunicationMutation(), { wrapper });
    await result.current.mutateAsync({
      projectId: "proj-1",
      projectName: "Project Alpha",
      payload: {
        comm_type: "weekly_summary",
        subject: detail.subject,
        instructions: "Focus on blockers.",
      },
    });

    await waitFor(() => {
      expect(queryClient.getQueryData(reportQueryKeys.detail("comm-new"))).toMatchObject({
        id: "comm-new",
        body_draft: "Generated body",
        generation_mode: "fallback",
      });
    });

    expect(mocks.createCommunicationDraft).toHaveBeenCalledTimes(1);
    expect(mocks.createCommunicationDraft).toHaveBeenCalledWith("proj-1", {
      comm_type: "weekly_summary",
      subject: detail.subject,
      instructions: "Focus on blockers.",
    });

    const list = queryClient.getQueryData(reportQueryKeys.list({ limit: 30, offset: 0 })) as {
      data: Array<{ id: string }>;
    };
    expect(list.data[0]?.id).toBe("comm-new");
  });
});
