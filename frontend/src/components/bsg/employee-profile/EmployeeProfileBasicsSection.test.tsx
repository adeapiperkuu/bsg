import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { EmployeeProfileBasicsSection } from "@/components/bsg/employee-profile/EmployeeProfileBasicsSection";
import { deleteAnnotator, updateAnnotator } from "@/lib/api";
import { queryKeys } from "@/lib/queries/keys";
import {
  ANNOTATOR_ID,
  makeAnnotator,
  makeTeam,
  makeTeamB,
  PROJECT_ID,
  TEAM_A_ID,
  TEAM_B_ID,
} from "@/test/workforce/fixtures";
import { renderWithQueryClient } from "@/test/workforce/render";

vi.mock("@/lib/api", () => ({
  updateAnnotator: vi.fn(),
  deleteAnnotator: vi.fn(),
}));

function renderBasicsSection(
  options: {
    onAnnotatorUpdated?: ReturnType<typeof vi.fn>;
    onAnnotatorRemoved?: ReturnType<typeof vi.fn>;
  } = {},
) {
  const onAnnotatorUpdated = options.onAnnotatorUpdated ?? vi.fn();
  const onAnnotatorRemoved = options.onAnnotatorRemoved ?? vi.fn();

  const result = renderWithQueryClient(
    <EmployeeProfileBasicsSection
      annotator={makeAnnotator()}
      teams={[makeTeam(), makeTeamB()]}
      projectId={PROJECT_ID}
      canManage
      onAnnotatorUpdated={onAnnotatorUpdated}
      onAnnotatorRemoved={onAnnotatorRemoved}
    />,
  );

  return { ...result, onAnnotatorUpdated, onAnnotatorRemoved };
}

describe("EmployeeProfileBasicsSection", () => {
  beforeEach(() => {
    vi.mocked(updateAnnotator).mockReset();
    vi.mocked(deleteAnnotator).mockReset();
  });

  it("sends only dirty updateAnnotator fields", async () => {
    const user = userEvent.setup();
    vi.mocked(updateAnnotator).mockResolvedValue(makeAnnotator({ full_name: "Janet Doe" }));

    renderBasicsSection();

    const nameInput = screen.getByDisplayValue("Jane Doe");
    await user.clear(nameInput);
    await user.type(nameInput, "Janet Doe");
    await user.click(screen.getByRole("button", { name: "Save changes" }));

    await waitFor(() => {
      expect(updateAnnotator).toHaveBeenCalledWith(ANNOTATOR_ID, {
        full_name: "Janet Doe",
      });
    });
  });

  it("sends team_id when moving annotator to another team", async () => {
    const user = userEvent.setup();
    vi.mocked(updateAnnotator).mockResolvedValue(
      makeAnnotator({ team_id: TEAM_B_ID, site: "kosovo" }),
    );

    const { queryClient } = renderBasicsSection();
    const invalidateSpy = vi.spyOn(queryClient, "invalidateQueries");

    await user.selectOptions(screen.getByLabelText("Team"), TEAM_B_ID);
    await user.click(screen.getByRole("button", { name: "Save changes" }));

    await waitFor(() => {
      expect(updateAnnotator).toHaveBeenCalledWith(ANNOTATOR_ID, {
        team_id: TEAM_B_ID,
      });
    });

    expect(invalidateSpy).toHaveBeenCalledWith({
      queryKey: queryKeys.teamAnnotators(TEAM_A_ID),
    });
    expect(invalidateSpy).toHaveBeenCalledWith({
      queryKey: queryKeys.teamAnnotators(TEAM_B_ID),
    });
  });

  it("requires confirmation before deleteAnnotator", async () => {
    const user = userEvent.setup();
    vi.mocked(deleteAnnotator).mockResolvedValue(undefined);
    const onAnnotatorRemoved = vi.fn();

    const { queryClient } = renderBasicsSection({ onAnnotatorRemoved });
    const invalidateSpy = vi.spyOn(queryClient, "invalidateQueries");

    await user.click(screen.getByRole("button", { name: "Remove annotator" }));
    expect(deleteAnnotator).not.toHaveBeenCalled();

    await user.click(screen.getByRole("button", { name: "Confirm remove" }));

    await waitFor(() => {
      expect(deleteAnnotator).toHaveBeenCalledWith(ANNOTATOR_ID);
    });

    expect(invalidateSpy).toHaveBeenCalledWith({
      queryKey: queryKeys.projectWorkforceSummary(PROJECT_ID),
    });
    expect(invalidateSpy).toHaveBeenCalledWith({
      queryKey: queryKeys.teamAnnotators(TEAM_A_ID),
    });
    expect(onAnnotatorRemoved).toHaveBeenCalledTimes(1);
  });
});
