import { createFileRoute, Navigate } from "@tanstack/react-router";

import { defaultRouteForRole } from "@/lib/api";
import { useAuthStore } from "@/stores/useAuthStore";

export const Route = createFileRoute("/")({
  component: IndexRedirect,
});

function IndexRedirect() {
  const user = useAuthStore((s) => s.user);

  // AuthProvider gates this route: it only renders once the session is
  // confirmed, so there is no unauthenticated case to redirect for here.
  if (!user) return null;
  return <Navigate to={defaultRouteForRole(user.role)} replace />;
}
