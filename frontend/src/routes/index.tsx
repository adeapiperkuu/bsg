import { createFileRoute, Navigate } from "@tanstack/react-router";

import { defaultRouteForRole } from "@/lib/api";
import { useAuthStore } from "@/stores/useAuthStore";

export const Route = createFileRoute("/")({
  component: IndexRedirect,
});

function IndexRedirect() {
  const user = useAuthStore((s) => s.user);
  const isAuthenticated = useAuthStore((s) => s.isAuthenticated);
  const isLoading = useAuthStore((s) => s.isLoading);

  if (isLoading) return null;
  if (!isAuthenticated || !user) return <Navigate to="/login" replace />;
  return <Navigate to={defaultRouteForRole(user.role)} replace />;
}
