import type { ComponentProps, ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

import { ProjectChartersPanel } from "@/features/governance/ProjectChartersPanel";
import {
  getProjectChartersPanel,
  listProjectCharterPublicationVersions,
  publishProjectCharter,
  republishProjectCharter,
  unpublishProjectCharter,
} from "@/lib/queries/governance";

const fixtures = vi.hoisted(() => {
  const listRow = {
    id: "11111111-1111-1111-1111-111111111111",
    org_id: "22222222-2222-2222-2222-222222222222",
    project_id: "33333333-3333-3333-3333-333333333333",
    version: "v1",
    status: "approved",
    generated_text: "",
    generated_by_ai: true,
    previous_version_id: null,
    knowledge_document_id: "44444444-4444-4444-4444-444444444444",
    knowledge_version_id: "55555555-5555-5555-5555-555555555555",
    visibility: "internal_only",
    approved_by: "66666666-6666-6666-6666-666666666666",
    approved_at: "2026-07-13T10:00:00Z",
    publication_status: "published",
    published_at: "2026-07-13T10:05:00Z",
    published_by: "66666666-6666-6666-6666-666666666666",
    published_by_name: "Alex Leader",
    publication_error: null,
    publication_attempt_count: 1,
    created_at: "2026-07-13T09:00:00Z",
    updated_at: "2026-07-13T10:05:00Z",
    evidence_links: [],
    project_name: "Helios",
    knowledge_url: "/knowledge?documentId=44444444-4444-4444-4444-444444444444",
  } as const;

  return {
    listRow,
    detail: {
      ...listRow,
      generated_text: "## Executive Summary\nTest charter",
      evidence_links: [
        {
          id: "77777777-7777-7777-7777-777777777777",
          org_id: listRow.org_id,
          charter_id: listRow.id,
          source_type: "dependency",
          source_id: "88888888-8888-8888-8888-888888888888",
          created_at: "2026-07-13T09:01:00Z",
          label: "Data dependency",
          detail: "blocking, due null",
          project_name: "Helios",
        },
      ],
    },
  };
});

vi.mock("@/lib/queries/governance", () => {
  const getProjectChartersPanel = vi.fn(async () => ({
    charters: [fixtures.listRow],
    selected_charter: fixtures.detail,
    limit: 5,
    offset: 0,
    has_more: false,
  }));
  return {
    getProjectChartersPanel,
    governanceProjectChartersPanelQueryOptions: (params: Record<string, unknown> = {}) => ({
      queryKey: ["governance", "project-charters-panel", params],
      queryFn: () => getProjectChartersPanel(params),
    }),
    listProjectCharterPublicationVersions: vi.fn(async () => [
      {
        charter_id: "11111111-1111-1111-1111-111111111111",
        charter_version: "v1",
        charter_status: "approved",
        publication_status: "published",
        knowledge_document_id: "44444444-4444-4444-4444-444444444444",
        knowledge_version_id: "55555555-5555-5555-5555-555555555555",
        knowledge_version: "v1",
        created_at: "2026-07-13T09:00:00Z",
        published_at: "2026-07-13T10:05:00Z",
        published_by: "66666666-6666-6666-6666-666666666666",
        published_by_name: "Alex Leader",
        approval_date: "2026-07-13T10:00:00Z",
        knowledge_url: "/knowledge?documentId=44444444-4444-4444-4444-444444444444",
      },
    ]),
    generateProjectCharter: vi.fn(),
    updateProjectCharter: vi.fn(),
    approveProjectCharter: vi.fn(),
    archiveProjectCharter: vi.fn(),
    exportProjectCharter: vi.fn(),
    publishProjectCharter: vi.fn(async () => fixtures.detail),
    republishProjectCharter: vi.fn(async () => fixtures.detail),
    retryProjectCharterPublication: vi.fn(),
    unpublishProjectCharter: vi.fn(async () => ({
      ...fixtures.detail,
      publication_status: "not_published",
    })),
    governanceJobsQueryOptions: (params: Record<string, unknown> = {}) => ({
      queryKey: ["governance", "jobs", params],
      queryFn: async () => [],
    }),
    governanceJobQueryOptions: (jobId: string) => ({
      queryKey: ["governance", "jobs", jobId],
      queryFn: async () => null,
    }),
    cancelGovernanceJob: vi.fn(),
    retryGovernanceJob: vi.fn(),
  };
});

vi.mock("@tanstack/react-router", () => ({
  Link: ({
    children,
    to,
    search,
  }: {
    children: ReactNode;
    to: string;
    search?: { documentId?: string };
  }) => (
    <a href={`${to}${search?.documentId ? `?documentId=${search.documentId}` : ""}`}>{children}</a>
  ),
}));

function renderPanel(props: Partial<ComponentProps<typeof ProjectChartersPanel>> = {}) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  const view = render(
    <QueryClientProvider client={client}>
      <ProjectChartersPanel
        projects={[{ value: "33333333-3333-3333-3333-333333333333", label: "Helios" }]}
        canWrite={false}
        canPublish
        isClient={false}
        isReadOnly
        {...props}
      />
    </QueryClientProvider>,
  );
  return { ...view, client };
}

function expectCharterInvalidations(invalidateSpy: ReturnType<typeof vi.spyOn>) {
  expect(invalidateSpy).toHaveBeenCalledWith({
    queryKey: ["governance", "project-charters"],
  });
  expect(invalidateSpy).toHaveBeenCalledWith({
    queryKey: ["governance", "project-charters-panel"],
  });
  expect(invalidateSpy).toHaveBeenCalledWith({
    queryKey: ["governance", "project-charter", fixtures.detail.id],
  });
  expect(invalidateSpy).toHaveBeenCalledWith({
    queryKey: ["governance", "project-charter-versions", fixtures.detail.id],
  });
}

describe("ProjectChartersPanel Knowledge publication", () => {
  beforeEach(() => {
    vi.mocked(getProjectChartersPanel).mockClear();
    vi.mocked(listProjectCharterPublicationVersions).mockClear();
    vi.mocked(publishProjectCharter).mockClear();
    vi.mocked(republishProjectCharter).mockClear();
    vi.mocked(unpublishProjectCharter).mockClear();
  });

  it("shows publish status, knowledge link, and republish for leadership", async () => {
    renderPanel();
    expect(await screen.findByText("Knowledge publication")).toBeInTheDocument();
    expect(screen.getAllByText("Published").length).toBeGreaterThan(0);
    expect(screen.getByRole("link", { name: "View Knowledge" })).toHaveAttribute(
      "href",
      expect.stringContaining("documentId=44444444-4444-4444-4444-444444444444"),
    );
    expect(screen.getByRole("button", { name: /Republish/i })).toBeInTheDocument();
    await waitFor(() =>
      expect(getProjectChartersPanel).toHaveBeenCalledWith({
        projectId: "33333333-3333-3333-3333-333333333333",
        selectedCharterId: null,
        limit: 5,
        offset: 0,
      }),
    );
    expect(listProjectCharterPublicationVersions).not.toHaveBeenCalled();
  });

  it("loads publication version history only after explicit expansion", async () => {
    renderPanel();
    expect(await screen.findByText("Knowledge publication")).toBeInTheDocument();
    expect(listProjectCharterPublicationVersions).not.toHaveBeenCalled();

    fireEvent.click(screen.getByRole("button", { name: /Show version history/i }));

    expect(screen.getAllByText(/Version history/i).length).toBeGreaterThan(0);
    await waitFor(() => expect(listProjectCharterPublicationVersions).toHaveBeenCalledTimes(1));

    fireEvent.click(screen.getByRole("button", { name: /Hide version history/i }));
    fireEvent.click(screen.getByRole("button", { name: /Show version history/i }));
    expect(listProjectCharterPublicationVersions).toHaveBeenCalledTimes(1);
  });

  it("loads full selected charter detail and evidence once while fresh", async () => {
    renderPanel();

    expect(await screen.findByText("Test charter")).toBeInTheDocument();
    await waitFor(() => expect(getProjectChartersPanel).toHaveBeenCalledTimes(1));

    fireEvent.click(screen.getByRole("button", { name: /Review draft/i }));
    expect(await screen.findByText("Evidence")).toBeInTheDocument();
    expect(screen.getByText(/Data dependency/)).toBeInTheDocument();

    fireEvent.click(screen.getAllByRole("button", { name: "Close" })[0]);
    await waitFor(() => expect(screen.queryByText("Evidence")).not.toBeInTheDocument());
    fireEvent.click(screen.getByRole("button", { name: /Review draft/i }));

    expect(screen.getByText(/Data dependency/)).toBeInTheDocument();
  });

  it("invalidates list, detail, and history after publish", async () => {
    const unpublished = {
      ...fixtures.detail,
      publication_status: "not_published",
      knowledge_document_id: null,
      knowledge_version_id: null,
      published_at: null,
      published_by: null,
      published_by_name: null,
      knowledge_url: null,
    };
    vi.mocked(getProjectChartersPanel).mockResolvedValueOnce({
      charters: [{ ...unpublished, generated_text: "", evidence_links: [] }],
      selected_charter: unpublished,
      limit: 5,
      offset: 0,
      has_more: false,
    });
    vi.mocked(publishProjectCharter).mockResolvedValueOnce(fixtures.detail);

    const { client } = renderPanel();
    const invalidateSpy = vi.spyOn(client, "invalidateQueries");

    fireEvent.click(await screen.findByRole("button", { name: /^Publish$/i }));

    await waitFor(() => expect(publishProjectCharter).toHaveBeenCalledWith(fixtures.detail.id));
    expectCharterInvalidations(invalidateSpy);
  });

  it("invalidates list, detail, and history after republish and unpublish", async () => {
    const { client } = renderPanel();
    const invalidateSpy = vi.spyOn(client, "invalidateQueries");

    fireEvent.click(await screen.findByRole("button", { name: /Republish/i }));
    await waitFor(() => expect(republishProjectCharter).toHaveBeenCalledWith(fixtures.detail.id));
    expectCharterInvalidations(invalidateSpy);

    invalidateSpy.mockClear();
    fireEvent.click(screen.getByRole("button", { name: /Unpublish/i }));
    await waitFor(() => expect(unpublishProjectCharter).toHaveBeenCalledWith(fixtures.detail.id));
    expectCharterInvalidations(invalidateSpy);
  });

  it("hides publish actions for non-publish roles", async () => {
    renderPanel({ canPublish: false });
    expect(await screen.findByText("Knowledge publication")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Republish/i })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /^Publish$/i })).not.toBeInTheDocument();
  });
});
