import { createFileRoute } from "@tanstack/react-router";
import { useEffect, useMemo, useState } from "react";
import { UserCheck, UserX, Users } from "lucide-react";

import { Card, SectionHeader } from "@/components/bsg/widgets";
import { formatRole, roles } from "@/lib/admin-shared";
import { listOrganisations, listUsers } from "@/lib/api";
import type { AppRole, OrganisationRead, UserRead } from "@/types/auth";

export const Route = createFileRoute("/admin/")({ component: AdminConsole });

function AdminConsole() {
  const [users, setUsers] = useState<UserRead[]>([]);
  const [orgs, setOrgs] = useState<OrganisationRead[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const activeUsers = users.filter((row) => row.is_active).length;
  const inactiveUsers = users.length - activeUsers;
  const usersByRole = useMemo(() => {
    const counts: Record<AppRole, number> = {
      client: 0,
      delivery_manager: 0,
      bsg_leadership: 0,
      super_admin: 0,
    };
    for (const row of users) counts[row.role] += 1;
    return counts;
  }, [users]);

  const load = async () => {
    setLoading(true);
    setError(null);
    try {
      const [userRows, orgRows] = await Promise.all([listUsers(), listOrganisations()]);
      setUsers(userRows);
      setOrgs(orgRows);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load admin data.");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    void load();
  }, []);

  return (
    <div className="space-y-5">
      {error && (
        <div className="rounded-md border border-destructive/30 bg-destructive/10 px-3 py-2 text-sm text-destructive">
          {error}
        </div>
      )}

      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
        <Card>
          <div className="flex items-center justify-between gap-3">
            <div className="min-w-0">
              <p className="text-xs font-medium uppercase tracking-wide text-muted-foreground">Total Users</p>
              <p className="mt-2 text-2xl font-semibold text-foreground">{users.length}</p>
            </div>
            <div className="grid h-10 w-10 shrink-0 place-items-center rounded-full bg-primary/10 text-primary">
              <Users className="h-5 w-5" />
            </div>
          </div>
          <p className="mt-1 min-h-8 text-xs text-muted-foreground">All registered accounts</p>
        </Card>
        <Card>
          <div className="flex items-center justify-between gap-3">
            <div className="min-w-0">
              <p className="text-xs font-medium uppercase tracking-wide text-muted-foreground">Active</p>
              <p className="mt-2 text-2xl font-semibold text-foreground">{activeUsers}</p>
            </div>
            <div className="grid h-10 w-10 shrink-0 place-items-center rounded-full bg-[color:var(--success)]/15 text-[color:var(--success)]">
              <UserCheck className="h-5 w-5" />
            </div>
          </div>
          <p className="mt-1 min-h-8 text-xs text-muted-foreground">Accounts allowed to sign in</p>
        </Card>
        <Card>
          <div className="flex items-center justify-between gap-3">
            <div className="min-w-0">
              <p className="text-xs font-medium uppercase tracking-wide text-muted-foreground">Inactive</p>
              <p className="mt-2 text-2xl font-semibold text-foreground">{inactiveUsers}</p>
            </div>
            <div className="grid h-10 w-10 shrink-0 place-items-center rounded-full bg-muted text-muted-foreground">
              <UserX className="h-5 w-5" />
            </div>
          </div>
          <p className="mt-1 min-h-8 text-xs text-muted-foreground">Disabled or pending cleanup</p>
        </Card>
      </div>

      <div className="grid gap-5 lg:grid-cols-2">
        <Card>
          <SectionHeader title="Users by role" sub={loading ? "Loading…" : "Distribution across platform roles"} />
          <div className="space-y-3">
            {roles.map((role) => (
              <div key={role} className="flex items-center justify-between gap-3 text-sm">
                <span className="text-muted-foreground">{formatRole(role)}</span>
                <span className="font-semibold text-foreground">{usersByRole[role]}</span>
              </div>
            ))}
          </div>
        </Card>
        <Card>
          <SectionHeader title="Organisations" sub={loading ? "Loading…" : "Tenant organisations on the platform"} />
          <p className="text-3xl font-semibold text-foreground">{orgs.length}</p>
          <p className="mt-2 text-xs text-muted-foreground">
            {orgs.filter((o) => o.is_active).length} active organisations available for user assignment.
          </p>
        </Card>
      </div>
    </div>
  );
}
