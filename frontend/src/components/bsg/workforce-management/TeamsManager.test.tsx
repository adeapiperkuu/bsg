import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { TeamsManager } from "@/components/bsg/workforce-management/TeamsManager";
import { createProjectTeam } from "@/lib/api";
import { queryKeys } from "@/lib/queries/keys";
import { PROJECT_ID } from "@/test/workforce/fixtures";
import { renderWithQueryClient } from "@/test/workforce/render";

vi.mock("@/lib/api", () => ({
  createProjectTeam: vi.fn(),
  updateTeam: vi.fn(),
  deleteTeam: vi.fn(),
}));

describe("TeamsManager", () => {
  beforeEach(() => {
    vi.mocked(createProjectTeam).mockReset();
  });

  it("returns null when canManage is false", () => {
    const { container } = renderWithQueryClient(
      <TeamsManager projectId={PROJECT_ID} teams={[]} canManage={false} />,
    );

    expect(container).toBeEmptyDOMElement();
  });

  it("creates a team and invalidates workforce queries", async () => {
    const user = userEvent.setup();
    vi.mocked(createProjectTeam).mockResolvedValue({
      id: "team-new",
      project_id: PROJECT_ID,
      org_id: "org-1",
      name: "Radiology QA",
      site: "india",
      domain: "Life Sciences",
      is_active: true,
      created_at: "2026-01-01T00:00:00.000Z",
      updated_at: "2026-01-01T00:00:00.000Z",
    });

    const { queryClient } = renderWithQueryClient(
      <TeamsManager projectId={PROJECT_ID} teams={[]} canManage />,
    );
    const invalidateSpy = vi.spyOn(queryClient, "invalidateQueries");

    await user.type(screen.getByPlaceholderText("e.g. Radiology QA"), "Radiology QA");
    await user.type(screen.getByPlaceholderText("e.g. Life Sciences"), "Life Sciences");
    await user.click(screen.getByRole("button", { name: "Add team" }));

    await waitFor(() => {
      expect(createProjectTeam).toHaveBeenCalledWith(PROJECT_ID, {
        name: "Radiology QA",
        site: "india",
        domain: "Life Sciences",
        is_active: true,
      });
    });

    expect(invalidateSpy).toHaveBeenCalledWith({
      queryKey: queryKeys.projectTeams(PROJECT_ID),
    });
    expect(invalidateSpy).toHaveBeenCalledWith({
      queryKey: queryKeys.projectWorkforceSummary(PROJECT_ID),
    });
  });
});
