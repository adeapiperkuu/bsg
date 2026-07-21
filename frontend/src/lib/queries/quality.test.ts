import { QueryClient } from "@tanstack/react-query";
import { describe, expect, it, vi } from "vitest";

import { loadQualityRouteData, prefetchDefaultQualityPage } from "@/lib/queries/quality";
import { queryKeys } from "@/lib/queries/keys";

describe("loadQualityRouteData", () => {
  it("starts the projects and quality-page fetches together, not one-after-the-other", async () => {
    const queryClient = new QueryClient();
    const events: string[] = [];
    const releasers: Array<() => void> = [];

    vi.spyOn(queryClient, "ensureQueryData").mockImplementation(async (options) => {
      const key = JSON.stringify((options as { queryKey: unknown }).queryKey);
      events.push(`start:${key}`);
      await new Promise<void>((resolve) => releasers.push(resolve));
      events.push(`end:${key}`);
      return undefined;
    });

    const done = loadQualityRouteData(queryClient, "project-1");

    // Flush microtasks without letting either fetch resolve yet. If the two
    // calls were awaited sequentially (a waterfall), only the first "start"
    // would be recorded at this point.
    await Promise.resolve();
    await Promise.resolve();
    await Promise.resolve();

    expect(events).toEqual([
      `start:${JSON.stringify(queryKeys.projects)}`,
      `start:${JSON.stringify(queryKeys.qualityPage("project-1"))}`,
    ]);

    releasers.forEach((release) => release());
    await done;

    expect(events).toHaveLength(4);
  });

  it("only prefetches projects when no projectId is known yet (no /projects/undefined/quality-page)", async () => {
    const queryClient = new QueryClient();
    const ensureQueryData = vi.spyOn(queryClient, "ensureQueryData").mockResolvedValue(undefined);

    await loadQualityRouteData(queryClient, undefined);

    expect(ensureQueryData).toHaveBeenCalledTimes(1);
    expect(ensureQueryData.mock.calls[0]?.[0]?.queryKey).toEqual(queryKeys.projects);
  });

  it("swallows failures so the route loader never rejects (would otherwise break the login redirect)", async () => {
    const queryClient = new QueryClient();
    vi.spyOn(queryClient, "ensureQueryData").mockRejectedValue(new Error("boom"));

    await expect(loadQualityRouteData(queryClient, "project-1")).resolves.toBeUndefined();
  });
});

describe("prefetchDefaultQualityPage", () => {
  it("resolves the first project from the projects cache, then prefetches only that project's quality-page", async () => {
    const queryClient = new QueryClient();
    vi.spyOn(queryClient, "ensureQueryData").mockResolvedValue([
      { id: "project-1", name: "First" },
      { id: "project-2", name: "Second" },
    ]);
    const prefetchQuery = vi.spyOn(queryClient, "prefetchQuery").mockResolvedValue(undefined);

    await prefetchDefaultQualityPage(queryClient);

    expect(prefetchQuery).toHaveBeenCalledTimes(1);
    expect(prefetchQuery.mock.calls[0]?.[0]?.queryKey).toEqual(queryKeys.qualityPage("project-1"));
  });

  it("does not prefetch anything when there are no projects", async () => {
    const queryClient = new QueryClient();
    vi.spyOn(queryClient, "ensureQueryData").mockResolvedValue([]);
    const prefetchQuery = vi.spyOn(queryClient, "prefetchQuery").mockResolvedValue(undefined);

    await prefetchDefaultQualityPage(queryClient);

    expect(prefetchQuery).not.toHaveBeenCalled();
  });

  it("swallows a rejected projects fetch instead of throwing", async () => {
    const queryClient = new QueryClient();
    vi.spyOn(queryClient, "ensureQueryData").mockRejectedValue(new Error("boom"));
    const prefetchQuery = vi.spyOn(queryClient, "prefetchQuery").mockResolvedValue(undefined);

    await expect(prefetchDefaultQualityPage(queryClient)).resolves.toBeUndefined();
    expect(prefetchQuery).not.toHaveBeenCalled();
  });

  it("swallows a rejected quality-page prefetch instead of throwing", async () => {
    const queryClient = new QueryClient();
    vi.spyOn(queryClient, "ensureQueryData").mockResolvedValue([
      { id: "project-1", name: "First" },
    ]);
    vi.spyOn(queryClient, "prefetchQuery").mockRejectedValue(new Error("boom"));

    await expect(prefetchDefaultQualityPage(queryClient)).resolves.toBeUndefined();
  });
});
