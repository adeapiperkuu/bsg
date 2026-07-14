import { create } from "zustand";

import { fetchMe, login as apiLogin, logout as apiLogout, resetAuthSession } from "@/lib/api";
import type { LoginResult, MeUser } from "@/types/auth";

type AuthState = {
  user: MeUser | null;
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

let sessionRequestId = 0;
let bootstrapPromise: Promise<void> | null = null;

function hasSessionHint() {
  if (typeof document === "undefined") return false;
  return /(?:^|; )csrf_token=/.test(document.cookie);
}

export const useAuthStore = create<AuthState>((set) => ({
  user: null,
  isLoading: true,
  isAuthenticated: false,

  bootstrap: async () => {
    if (bootstrapPromise) return bootstrapPromise;
    if (typeof window === "undefined") return;
    bootstrapPromise = (async () => {
      const requestId = ++sessionRequestId;
      if (!hasSessionHint()) {
        set({ user: null, isAuthenticated: false, isLoading: false });
        return;
      }
      set({ isLoading: true });
      try {
        const user = await fetchMe();
        if (requestId !== sessionRequestId) return;
        set({ user, isAuthenticated: true, isLoading: false });
      } catch {
        if (requestId !== sessionRequestId) return;
        resetAuthSession();
        set({ user: null, isAuthenticated: false, isLoading: false });
      }
    })().finally(() => {
      bootstrapPromise = null;
    });
    return bootstrapPromise;
  },

  login: async (email, password) => {
    const requestId = ++sessionRequestId;
    set({ isLoading: true });
    try {
      const result = await apiLogin(email, password);
      if (result.status === "mfa_required") {
        if (requestId === sessionRequestId) set({ isLoading: false });
        return result;
      }
      const user = await fetchMe();
      if (requestId === sessionRequestId) {
        set({ user, isAuthenticated: true, isLoading: false });
      }
      return result;
    } catch (err) {
      if (requestId === sessionRequestId) {
        set({ isLoading: false });
      }
      throw err;
    }
  },

  completeMfaLogin: async () => {
    const requestId = ++sessionRequestId;
    set({ isLoading: true });
    try {
      const user = await fetchMe();
      if (requestId === sessionRequestId) {
        set({ user, isAuthenticated: true, isLoading: false });
      }
      return user;
    } catch (err) {
      if (requestId === sessionRequestId) {
        set({ isLoading: false });
      }
      throw err;
    }
  },

  logout: async () => {
    ++sessionRequestId;
    try {
      await apiLogout();
    } finally {
      set({ user: null, isAuthenticated: false, isLoading: false });
    }
  },

  setUser: (user) => set({ user, isAuthenticated: user !== null }),
}));
