import { afterEach, describe, expect, it, vi } from "vitest";

import { apiFetch, ApiError } from "./api";

function jsonResponse(status: number, body = {}) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

function clearCsrfCookie() {
  document.cookie = "csrf_token=; Max-Age=0; path=/";
}

describe("apiFetch auth refresh", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
    clearCsrfCookie();
  });

  it("does not call refresh when there is no client session hint", async () => {
    const fetchMock = vi.fn(async () =>
      jsonResponse(401, { error: { code: "AUTH_REQUIRED", message: "Authentication required." } }),
    );
    vi.stubGlobal("fetch", fetchMock);

    await expect(apiFetch("/me")).rejects.toBeInstanceOf(ApiError);

    expect(fetchMock).toHaveBeenCalledTimes(1);
    expect(fetchMock).toHaveBeenCalledWith("/api/v1/me", expect.any(Object));
  });

  it("shares one refresh request across concurrent 401 responses", async () => {
    document.cookie = "csrf_token=test-token; path=/";
    let refreshCount = 0;
    const fetchMock = vi.fn(async (url: string | URL | Request) => {
      const requestUrl = String(url);
      if (requestUrl.endsWith("/auth/refresh")) {
        refreshCount += 1;
        await new Promise((resolve) => setTimeout(resolve, 0));
        return jsonResponse(401, {
          error: { code: "AUTH_REQUIRED", message: "Missing refresh token." },
        });
      }
      return jsonResponse(401, {
        error: { code: "AUTH_REQUIRED", message: "Authentication required." },
      });
    });
    vi.stubGlobal("fetch", fetchMock);

    await Promise.allSettled([apiFetch("/me"), apiFetch("/projects")]);

    expect(refreshCount).toBe(1);
  });

  it("retries the original request after a successful refresh", async () => {
    document.cookie = "csrf_token=test-token; path=/";
    const fetchMock = vi.fn(async (url: string | URL | Request) => {
      const requestUrl = String(url);
      if (requestUrl.endsWith("/auth/refresh")) {
        return jsonResponse(200, { data: { id: "user-1" } });
      }
      const meCallCount = fetchMock.mock.calls.filter(([calledUrl]) =>
        String(calledUrl).endsWith("/me"),
      ).length;
      if (meCallCount === 1) {
        return jsonResponse(401, {
          error: { code: "AUTH_REQUIRED", message: "Authentication required." },
        });
      }
      return jsonResponse(200, { data: { id: "user-1", email: "user@example.com" } });
    });
    vi.stubGlobal("fetch", fetchMock);

    await expect(apiFetch("/me")).resolves.toEqual({
      data: { id: "user-1", email: "user@example.com" },
    });

    expect(fetchMock).toHaveBeenCalledTimes(3);
  });
});

describe("createAgentQuery", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
    clearCsrfCookie();
  });

  it("rejects malformed agent responses instead of returning undefined", async () => {
    const fetchMock = vi.fn(async () => jsonResponse(200, { data: { id: "query-1" } }));
    vi.stubGlobal("fetch", fetchMock);

    const { createAgentQuery } = await import("./api");

    await expect(
      createAgentQuery({
        agent_name: "workforce_capability_agent",
        project_id: "project-1",
        query_text: "Which teams are overloaded?",
      }),
    ).rejects.toMatchObject({
      status: 500,
      code: "INVALID_RESPONSE",
    });
  });
});
