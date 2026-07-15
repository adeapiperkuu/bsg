import { create } from "zustand";

import {
  currentAuthGeneration,
  nextAuthGeneration,
  setSessionInvalidatedHandler,
} from "@/lib/auth-session";
import { fetchMe, login as apiLogin, logout as apiLogout, resetAuthSession } from "@/lib/api";
import type { LoginResult, MeUser } from "@/types/auth";

export type AuthStatus = "initializing" | "authenticating" | "authenticated" | "anonymous";

type AuthState = {
  user: MeUser | null;
  status: AuthStatus;
  isLoading: boolean;
  isAuthenticated: boolean;
  bootstrap: () => Promise<void>;
  login: (email: string, password: string) => Promise<LoginResult>;
  /** DEVELOPMENT_PLAN.md Workstream E: call after POST /auth/mfa/verify
   * succeeds (which already set the real session cookies) to populate the
   * store the same way a non-MFA login does. */
  completeMfaLogin: () => Promise<MeUser>;
  logout: () => Promise<void>;
  setUser: (user: MeUser | null) => void;
};

let bootstrapPromise: Promise<void> | null = null;

function hasSessionHint() {
  if (typeof document === "undefined") return false;
  return /(?:^|; )csrf_token=/.test(document.cookie);
}

function stateFor(status: AuthStatus, user: MeUser | null) {
  return {
    status,
    user,
    isAuthenticated: status === "authenticated",
    isLoading: status === "initializing" || status === "authenticating",
  };
}

export const useAuthStore = create<AuthState>((set) => ({
  ...stateFor("initializing", null),

  bootstrap: async () => {
    if (bootstrapPromise) return bootstrapPromise;
    if (typeof window === "undefined") return;
    bootstrapPromise = (async () => {
      const generation = nextAuthGeneration();
      if (!hasSessionHint()) {
        set(stateFor("anonymous", null));
        return;
      }
      set(stateFor("initializing", null));
      try {
        const user = await fetchMe();
        if (generation !== currentAuthGeneration()) return;
        set(stateFor("authenticated", user));
      } catch {
        if (generation !== currentAuthGeneration()) return;
        resetAuthSession(generation);
        set(stateFor("anonymous", null));
      }
    })().finally(() => {
      bootstrapPromise = null;
    });
    return bootstrapPromise;
  },

  login: async (email, password) => {
    const generation = nextAuthGeneration();
    set(stateFor("authenticating", null));
    try {
      const result = await apiLogin(email, password);
      if (result.status === "mfa_required") {
        if (generation === currentAuthGeneration()) set(stateFor("anonymous", null));
        return result;
      }
      const user = await fetchMe();
      if (generation === currentAuthGeneration()) set(stateFor("authenticated", user));
      return result;
    } catch (err) {
      if (generation === currentAuthGeneration()) set(stateFor("anonymous", null));
      throw err;
    }
  },

  completeMfaLogin: async () => {
    const generation = nextAuthGeneration();
    set(stateFor("authenticating", null));
    try {
      const user = await fetchMe();
      if (generation === currentAuthGeneration()) set(stateFor("authenticated", user));
      return user;
    } catch (err) {
      if (generation === currentAuthGeneration()) set(stateFor("anonymous", null));
      throw err;
    }
  },

  logout: async () => {
    const generation = nextAuthGeneration();
    set(stateFor("authenticating", null));
    try {
      await apiLogout();
    } finally {
      if (generation === currentAuthGeneration()) set(stateFor("anonymous", null));
    }
  },

  setUser: (user) => set(stateFor(user ? "authenticated" : "anonymous", user)),
}));

setSessionInvalidatedHandler((generation) => {
  if (generation !== currentAuthGeneration()) return;
  useAuthStore.setState(stateFor("anonymous", null));
});
