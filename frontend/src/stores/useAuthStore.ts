import { create } from "zustand";

import { fetchMe, login as apiLogin, logout as apiLogout } from "@/lib/api";
import type { MeUser } from "@/types/auth";

type AuthState = {
  user: MeUser | null;
  isLoading: boolean;
  isAuthenticated: boolean;
  bootstrap: () => Promise<void>;
  login: (email: string, password: string) => Promise<void>;
  logout: () => Promise<void>;
  setUser: (user: MeUser | null) => void;
};

export const useAuthStore = create<AuthState>((set, get) => ({
  user: null,
  isLoading: true,
  isAuthenticated: false,

  bootstrap: async () => {
    if (typeof window === "undefined") return;
    set({ isLoading: true });
    try {
      const user = await fetchMe();
      set({ user, isAuthenticated: true, isLoading: false });
    } catch {
      set({ user: null, isAuthenticated: false, isLoading: false });
    }
  },

  login: async (email, password) => {
    await apiLogin(email, password);
    await get().bootstrap();
  },

  logout: async () => {
    try {
      await apiLogout();
    } finally {
      set({ user: null, isAuthenticated: false, isLoading: false });
    }
  },

  setUser: (user) => set({ user, isAuthenticated: user !== null }),
}));
