import type { ComponentProps } from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import {
  GenerateReportDialog,
  suggestReportSubject,
} from "@/features/reports/GenerateReportDialog";
import { ApiError } from "@/lib/api";
import type { ProgramRead, ProjectRead } from "@/lib/api";
import type { OrganisationRead } from "@/types/auth";

const mocks = vi.hoisted(() => ({
  listProjects: vi.fn(),
  listOrganisations: vi.fn(),
  listPrograms: vi.fn(),
}));

vi.mock("@/lib/api", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/lib/api")>();
  return {
    ...actual,
    listProjects: mocks.listProjects,
    listOrganisations: mocks.listOrganisations,
    listPrograms: mocks.listPrograms,
  };
});

const orgNorthwind: OrganisationRead = {
  id: "org1",
  name: "Northwind Analytics",
  slug: "northwind",
  vertical: "annotation",
  region: "eu",
  is_active: true,
};

const programAnnotation: ProgramRead = {
  id: "prog-1",
  org_id: "org1",
  name: "Annotation",
  description: null,
  created_at: "2026-01-01T00:00:00Z",
  updated_at: "2026-01-01T00:00:00Z",
  scope_count: 1,
};

const scopeA: ProjectRead = {
  id: "proj-a",
  org_id: "org1",
  program_id: "prog-1",
  name: "Sprint 13",
  description: null,
  vertical: "banking",
  status: "active",
  start_date: "2026-01-01",
  target_end_date: "2026-12-31",
  actual_end_date: null,
  daily_target_units: null,
  created_at: "2026-01-01T00:00:00Z",
  updated_at: "2026-01-01T00:00:00Z",
};

function renderDialog(
  props: Partial<ComponentProps<typeof GenerateReportDialog>> = {},
) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  const onGenerate = props.onGenerate ?? vi.fn().mockResolvedValue(undefined);
  const onClose = props.onClose ?? vi.fn();
  render(
    <QueryClientProvider client={client}>
      <GenerateReportDialog
        open
        onClose={onClose}
        onGenerate={onGenerate}
        isPending={props.isPending}
        canGenerate={props.canGenerate}
        initialProjectId={props.initialProjectId}
        initialCommType={props.initialCommType}
      />
    </QueryClientProvider>,
  );
  return { onGenerate, onClose };
}

describe("suggestReportSubject", () => {
  it("formats subjects by report type", () => {
    expect(suggestReportSubject("Alpha", "weekly_summary")).toBe(
      "Weekly Delivery Summary — Alpha",
    );
  });
});

describe("GenerateReportDialog", () => {
  beforeEach(() => {
    mocks.listProjects.mockReset();
    mocks.listOrganisations.mockReset();
    mocks.listPrograms.mockReset();
    mocks.listProjects.mockResolvedValue([scopeA]);
    mocks.listOrganisations.mockResolvedValue([orgNorthwind]);
    mocks.listPrograms.mockResolvedValue([programAnnotation]);
  });

  it("cascades client → project → scope", async () => {
    const user = userEvent.setup();
    const { onGenerate } = renderDialog();
    await waitFor(() => expect(screen.getByText("Annotation")).toBeInTheDocument());

    // Single client is auto-selected.
    expect(screen.getByDisplayValue("Northwind Analytics")).toBeInTheDocument();
    await user.selectOptions(screen.getByDisplayValue("Select a project"), "prog-1");
    expect(screen.getByText("Sprint 13")).toBeInTheDocument();

    await user.selectOptions(screen.getByDisplayValue("Select a scope"), "proj-a");
    await user.click(screen.getByRole("button", { name: "Generate" }));
    await waitFor(() => expect(onGenerate).toHaveBeenCalledTimes(1));
    expect(onGenerate.mock.calls[0][0]).toMatchObject({
      projectId: "proj-a",
      programId: "prog-1",
      orgId: "org1",
    });
  });

  it("maps 409 EVIDENCE_REQUIRED", async () => {
    const user = userEvent.setup();
    const onGenerate = vi
      .fn()
      .mockRejectedValue(new ApiError(409, "EVIDENCE_REQUIRED", "needs evidence"));
    renderDialog({ onGenerate });
    await waitFor(() => expect(screen.getByText("Annotation")).toBeInTheDocument());
    await user.selectOptions(screen.getByDisplayValue("Select a project"), "prog-1");
    await user.selectOptions(screen.getByDisplayValue("Select a scope"), "proj-a");
    await user.click(screen.getByRole("button", { name: "Generate" }));
    expect(
      await screen.findByText("Scope needs delivery data before a report can be generated."),
    ).toBeInTheDocument();
  });
});
