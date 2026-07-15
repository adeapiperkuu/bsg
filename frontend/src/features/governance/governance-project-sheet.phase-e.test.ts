import { QueryClient } from "@tanstack/react-query";
import { describe, expect, it } from "vitest";

import {
  governanceProjectSheetQueryOptions,
  invalidateGovernanceProjectSheet,
} from "@/lib/queries/governance";
import { queryKeys } from "@/lib/queries/keys";

describe("Phase E project-sheet query ownership", () => {
  it("uses a stable project-scoped query key", () => {
    expect(governanceProjectSheetQueryOptions("project-a").queryKey).toEqual(
      queryKeys.governanceProjectSheet("project-a"),
    );
    expect(governanceProjectSheetQueryOptions("project-a").queryKey).not.toEqual(
      governanceProjectSheetQueryOptions("project-b").queryKey,
    );
  });

  it("invalidates only the affected project sheet after a successful mutation", async () => {
    const queryClient = new QueryClient();
    const projectAKey = queryKeys.governanceProjectSheet("project-a");
    const projectBKey = queryKeys.governanceProjectSheet("project-b");
    queryClient.setQueryData(projectAKey, { project: { id: "project-a" } });
    queryClient.setQueryData(projectBKey, { project: { id: "project-b" } });

    await invalidateGovernanceProjectSheet(queryClient, "project-a");

    expect(queryClient.getQueryState(projectAKey)?.isInvalidated).toBe(true);
    expect(queryClient.getQueryState(projectBKey)?.isInvalidated).toBe(false);
  });
});
