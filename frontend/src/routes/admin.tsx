import { createFileRoute, Outlet } from "@tanstack/react-router";

import { useAuthStore } from "@/stores/useAuthStore";

export const Route = createFileRoute("/admin")({ component: AdminLayout });

function AdminLayout() {
  const user = useAuthStore((s) => s.user);
  const canManageUsers = user?.permissions.can_manage_users ?? false;

  if (!canManageUsers) {
    return (
      <div className="rounded-md border border-border bg-card p-6 text-sm text-muted-foreground">
        Super admin access is required to manage users and platform configuration.
      </div>
    );
  }

  return <Outlet />;
}
