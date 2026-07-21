import { QueryClient } from "@tanstack/react-query";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { prefetchReportsNav } from "@/features/reports/reports-prefetch";
import { queryKeys } from "@/lib/queries/keys";

const listCommunications = vi.hoisted(() => vi.fn());

vi.mock("@/lib/api", () => ({
  listCommunications: listCommunications,
  getCommunication: vi.fn(),
}));

describe("reports-prefetch", () => {
  beforeEach(() => {
    listCommunications.mockReset();
    listCommunications.mockResolvedValue({
      data: [],
      pagination: { limit: 30, offset: 0, total: 0, items: 0, has_more: false },
    });
  });

  it("warms only the lightweight list query", async () => {
    const queryClient = new QueryClient();
    const prefetchSpy = vi.spyOn(queryClient, "prefetchQuery");

    await prefetchReportsNav(queryClient);

    expect(listCommunications).toHaveBeenCalledTimes(1);
    expect(listCommunications).toHaveBeenCalledWith(
      expect.objectContaining({ limit: 30, offset: 0 }),
    );
    expect(prefetchSpy).toHaveBeenCalledTimes(1);
    const key = prefetchSpy.mock.calls[0]?.[0];
    const queryKey =
      key && typeof key === "object" && "queryKey" in key
        ? (key as { queryKey: unknown }).queryKey
        : key;
    expect(queryKey).toEqual(
      queryKeys.communicationsList({ status: null, projectId: null, limit: 30, offset: 0 }),
    );
  });
});
