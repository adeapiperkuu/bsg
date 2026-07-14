import type { ComponentProps, ReactNode } from "react";
import { describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

import { ProjectChartersPanel } from "@/features/governance/ProjectChartersPanel";

vi.mock("@/lib/queries/governance", () => ({
  listProjectCharters: vi.fn(async () => [
    {
      id: "11111111-1111-1111-1111-111111111111",
      org_id: "22222222-2222-2222-2222-222222222222",
      project_id: "33333333-3333-3333-3333-333333333333",
      version: "v1",
      status: "approved",
      generated_text: "## Executive Summary\nTest charter",
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
    },
  ]),
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
  publishProjectCharter: vi.fn(),
  republishProjectCharter: vi.fn(),
  retryProjectCharterPublication: vi.fn(),
}));

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
  return render(
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
}

describe("ProjectChartersPanel Knowledge publication", () => {
  it("shows publish status, knowledge link, and republish for leadership", async () => {
    renderPanel();
    expect(await screen.findByText("Knowledge publication")).toBeInTheDocument();
    expect(screen.getAllByText("Published").length).toBeGreaterThan(0);
    expect(screen.getByRole("link", { name: "View Knowledge" })).toHaveAttribute(
      "href",
      expect.stringContaining("documentId=44444444-4444-4444-4444-444444444444"),
    );
    expect(screen.getByRole("button", { name: /Republish/i })).toBeInTheDocument();
    expect(screen.getByText(/Version history/i)).toBeInTheDocument();
  });

  it("hides publish actions for non-publish roles", async () => {
    renderPanel({ canPublish: false });
    expect(await screen.findByText("Knowledge publication")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Republish/i })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /^Publish$/i })).not.toBeInTheDocument();
  });
});
