import { createFileRoute, Navigate } from "@tanstack/react-router";

import { defaultRouteForRole } from "@/lib/api";
import { useAuthStore } from "@/stores/useAuthStore";

export const Route = createFileRoute("/")({
  component: IndexRedirect,
});

function IndexRedirect() {
  const user = useAuthStore((s) => s.user);

  if (!user) return null;
  return <Navigate to={defaultRouteForRole(user.role)} replace />;
}
