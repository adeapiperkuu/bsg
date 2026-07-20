import { useEffect } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { Navigate, useNavigate, useRouterState } from "@tanstack/react-router";

import { canAccessPath, defaultRouteForRole } from "@/lib/api";
import { projectsQueryOptions } from "@/lib/queries/delivery";
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
  const queryClient = useQueryClient();
  const pathname = useRouterState({ select: (s) => s.location.pathname });
  const { bootstrap, isLoading, isAuthenticated, user } = useAuthStore();
  const isPublicPath = PUBLIC_PATHS.includes(pathname);

  useEffect(() => {
    void bootstrap();
  }, [bootstrap]);

  // Warm the projects cache the moment auth resolves (not on navigation to
  // any particular project-scoped route), so /quality and similar routes
  // are already warm by the time the user gets there
  // (PERF_IMPLEMENTATION_PLAN.md Phase 1B). This only ever fires once per
  // page load: `isAuthenticated` flips false->true a single time because
  // `bootstrap()` itself only runs once (see above) and AuthProvider never
  // remounts on client-side navigation (it wraps the router's Outlet).
  useEffect(() => {
    if (!isAuthenticated) return;
    void queryClient.prefetchQuery(projectsQueryOptions);
  }, [isAuthenticated, queryClient]);

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

    if (
      isAuthenticated &&
      user &&
      !PUBLIC_PATHS.includes(pathname) &&
      !canAccessPath(user.role, pathname)
    ) {
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
