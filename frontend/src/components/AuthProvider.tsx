import { useEffect } from "react";
import { useNavigate, useRouterState } from "@tanstack/react-router";

import { canAccessPath, defaultRouteForRole } from "@/lib/api";
import { useAuthStore } from "@/stores/useAuthStore";

const PUBLIC_PATHS = ["/login", "/unauthorized"];

export function AuthProvider({ children }: { children: React.ReactNode }) {
  const navigate = useNavigate();
  const pathname = useRouterState({ select: (s) => s.location.pathname });
  const { bootstrap, isLoading, isAuthenticated, user } = useAuthStore();

  useEffect(() => {
    void bootstrap();
  }, [bootstrap]);

  useEffect(() => {
    if (isLoading) return;

    if (!isAuthenticated && !PUBLIC_PATHS.includes(pathname)) {
      void navigate({ to: "/login", replace: true });
      return;
    }

    if (isAuthenticated && user && pathname === "/login") {
      void navigate({ to: defaultRouteForRole(user.role), replace: true });
      return;
    }

    if (isAuthenticated && user && !PUBLIC_PATHS.includes(pathname) && !canAccessPath(user.role, pathname)) {
      void navigate({ to: "/unauthorized", replace: true });
    }
  }, [isLoading, isAuthenticated, pathname, user, navigate]);

  if (!PUBLIC_PATHS.includes(pathname) && (isLoading || !isAuthenticated)) {
    return (
      <div className="flex min-h-screen items-center justify-center bg-background text-sm text-muted-foreground">
        Loading session...
      </div>
    );
  }

  return <>{children}</>;
}
