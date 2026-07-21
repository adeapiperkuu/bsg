import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { renderHook, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { prefetchDefaultQualityPage } from "@/lib/queries/quality";
import { useAuthStore } from "@/stores/useAuthStore";
import type { MeUser } from "@/types/auth";
import { usePrefetchQualityIntelligence } from "./usePrefetchQualityIntelligence";

vi.mock("@/lib/queries/quality", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/lib/queries/quality")>();
  return { ...actual, prefetchDefaultQualityPage: vi.fn().mockResolvedValue(undefined) };
});

const mockedPrefetch = vi.mocked(prefetchDefaultQualityPage);

function pmUser(): MeUser {
  return {
    id: "user-1",
    email: "pm@bsg.dev",
    full_name: "Dev PM",
    role: "delivery_manager",
    org_id: "org-1",
    is_active: true,
    organisation: {
      id: "org-1",
      name: "Northwind Analytics",
      vertical: "retail",
      region: "north_america",
    },
    permissions: {
      can_manage_projects: true,
      can_approve_communications: true,
      can_manage_metric_configurations: false,
      can_view_cross_client_portfolio: false,
      can_manage_users: false,
      can_manage_organisations: false,
    },
  };
}

function createWrapper(queryClient: QueryClient) {
  return function Wrapper({ children }: { children: ReactNode }) {
    return <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>;
  };
}

afterEach(() => {
  vi.clearAllMocks();
  vi.useRealTimers();
  useAuthStore.setState({ user: null, isAuthenticated: false, isLoading: false });
});

describe("usePrefetchQualityIntelligence", () => {
  it("schedules the prefetch (via the setTimeout fallback, since jsdom has no requestIdleCallback) when a QI-capable user is present", async () => {
    useAuthStore.setState({ user: pmUser(), isAuthenticated: true, isLoading: false });
    const queryClient = new QueryClient();

    renderHook(() => usePrefetchQualityIntelligence(), { wrapper: createWrapper(queryClient) });

    expect(mockedPrefetch).not.toHaveBeenCalled();
    await waitFor(() => expect(mockedPrefetch).toHaveBeenCalledTimes(1));
    expect(mockedPrefetch).toHaveBeenCalledWith(queryClient);
  });

  it("uses requestIdleCallback when the browser supports it, instead of the setTimeout fallback", async () => {
    const idleCallbacks: Array<() => void> = [];
    const requestIdleCallback = vi.fn((cb: () => void) => {
      idleCallbacks.push(cb);
      return 1;
    });
    const cancelIdleCallback = vi.fn();
    (window as unknown as { requestIdleCallback: typeof requestIdleCallback }).requestIdleCallback =
      requestIdleCallback;
    (window as unknown as { cancelIdleCallback: typeof cancelIdleCallback }).cancelIdleCallback =
      cancelIdleCallback;

    try {
      useAuthStore.setState({ user: pmUser(), isAuthenticated: true, isLoading: false });
      const queryClient = new QueryClient();

      renderHook(() => usePrefetchQualityIntelligence(), { wrapper: createWrapper(queryClient) });

      expect(requestIdleCallback).toHaveBeenCalledTimes(1);
      expect(mockedPrefetch).not.toHaveBeenCalled();

      idleCallbacks.forEach((cb) => cb());
      await waitFor(() => expect(mockedPrefetch).toHaveBeenCalledTimes(1));
    } finally {
      delete (window as { requestIdleCallback?: unknown }).requestIdleCallback;
      delete (window as { cancelIdleCallback?: unknown }).cancelIdleCallback;
    }
  });

  it("does not schedule anything when there is no authenticated user yet", async () => {
    useAuthStore.setState({ user: null, isAuthenticated: false, isLoading: false });
    const queryClient = new QueryClient();

    renderHook(() => usePrefetchQualityIntelligence(), { wrapper: createWrapper(queryClient) });

    await new Promise((resolve) => setTimeout(resolve, 250));
    expect(mockedPrefetch).not.toHaveBeenCalled();
  });

  it("does not schedule anything for a role that cannot access /quality (e.g. client)", async () => {
    useAuthStore.setState({
      user: { ...pmUser(), role: "client" },
      isAuthenticated: true,
      isLoading: false,
    });
    const queryClient = new QueryClient();

    renderHook(() => usePrefetchQualityIntelligence(), { wrapper: createWrapper(queryClient) });

    await new Promise((resolve) => setTimeout(resolve, 250));
    expect(mockedPrefetch).not.toHaveBeenCalled();
  });

  it("cancels the pending prefetch if the component unmounts before it fires", async () => {
    useAuthStore.setState({ user: pmUser(), isAuthenticated: true, isLoading: false });
    const queryClient = new QueryClient();

    const { unmount } = renderHook(() => usePrefetchQualityIntelligence(), {
      wrapper: createWrapper(queryClient),
    });
    unmount();

    await new Promise((resolve) => setTimeout(resolve, 250));
    expect(mockedPrefetch).not.toHaveBeenCalled();
  });
});
