import { useEffect } from "react";
import { Navigate, useNavigate, useRouterState } from "@tanstack/react-router";

import { canAccessPath, defaultRouteForRole } from "@/lib/api";
import { useAuthStore } from "@/stores/useAuthStore";

const PUBLIC_PATHS = ["/login", "/unauthorized"];

function SessionLoadingScreen() {
  return (
    <div className="flex min-h-screen items-center justify-center bg-background text-sm text-muted-foreground">
      Loading session...
    </div>
  );
}

export function AuthProvider({ children }: { children: React.ReactNode }) {
  const navigate = useNavigate();
  const pathname = useRouterState({ select: (s) => s.location.pathname });
  const { bootstrap, isLoading, isAuthenticated, user } = useAuthStore();
  const isPublicPath = PUBLIC_PATHS.includes(pathname);

  useEffect(() => {
    void bootstrap();
  }, [bootstrap]);

  useEffect(() => {
    if (isLoading) return;

    if (!isAuthenticated && !isPublicPath) {
      void navigate({ to: "/login", replace: true });
      return;
    }

    if (isAuthenticated && user && pathname === "/login") {
      void navigate({ to: defaultRouteForRole(user.role), replace: true });
      return;
    }

    if (isAuthenticated && user && !isPublicPath && !canAccessPath(user.role, pathname)) {
      void navigate({ to: "/unauthorized", replace: true });
    }
  }, [isLoading, isAuthenticated, isPublicPath, pathname, user, navigate]);

  if (!isPublicPath && isLoading) {
    return <SessionLoadingScreen />;
  }

  if (!isPublicPath && !isAuthenticated) {
    return <Navigate to="/login" replace />;
  }

  return <>{children}</>;
}
