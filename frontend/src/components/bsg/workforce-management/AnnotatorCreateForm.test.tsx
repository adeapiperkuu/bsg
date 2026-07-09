import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { AnnotatorCreateForm } from "@/components/bsg/workforce-management/AnnotatorCreateForm";
import { createTeamAnnotator } from "@/lib/api";
import { queryKeys } from "@/lib/queries/keys";
import { ANNOTATOR_ID, PROJECT_ID, TEAM_A_ID } from "@/test/workforce/fixtures";
import { renderWithQueryClient } from "@/test/workforce/render";

vi.mock("@/lib/api", () => ({
  createTeamAnnotator: vi.fn(),
}));

describe("AnnotatorCreateForm", () => {
  beforeEach(() => {
    vi.mocked(createTeamAnnotator).mockReset();
  });

  it("returns null when canManage is false", () => {
    const { container } = renderWithQueryClient(
      <AnnotatorCreateForm
        projectId={PROJECT_ID}
        teamId={TEAM_A_ID}
        defaultSite="india"
        canManage={false}
      />,
    );

    expect(container).toBeEmptyDOMElement();
  });

  it("creates an annotator and invalidates workforce queries", async () => {
    const user = userEvent.setup();
    vi.mocked(createTeamAnnotator).mockResolvedValue({
      id: ANNOTATOR_ID,
      org_id: "org-1",
      team_id: TEAM_A_ID,
      full_name: "Jane Doe",
      site: "india",
      is_sme_certified: false,
      is_active: true,
      created_at: "2026-01-01T00:00:00.000Z",
      updated_at: "2026-01-01T00:00:00.000Z",
    });

    const { queryClient } = renderWithQueryClient(
      <AnnotatorCreateForm
        projectId={PROJECT_ID}
        teamId={TEAM_A_ID}
        defaultSite="india"
        canManage
      />,
    );
    const invalidateSpy = vi.spyOn(queryClient, "invalidateQueries");

    await user.type(screen.getByPlaceholderText("e.g. Jane Doe"), "Jane Doe");
    await user.click(screen.getByRole("button", { name: "Add annotator" }));

    await waitFor(() => {
      expect(createTeamAnnotator).toHaveBeenCalledWith(TEAM_A_ID, {
        full_name: "Jane Doe",
        site: "india",
        is_sme_certified: false,
        is_active: true,
      });
    });

    expect(invalidateSpy).toHaveBeenCalledWith({
      queryKey: queryKeys.projectWorkforceSummary(PROJECT_ID),
    });
    expect(invalidateSpy).toHaveBeenCalledWith({
      queryKey: queryKeys.teamAnnotators(TEAM_A_ID),
    });
  });
});
