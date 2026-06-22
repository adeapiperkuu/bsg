import { createFileRoute } from "@tanstack/react-router";
import { useEffect, useState } from "react";

import { Card, SectionHeader } from "@/components/bsg/widgets";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { createUser, listOrganisations, listUsers } from "@/lib/api";
import { useAuthStore } from "@/stores/useAuthStore";
import type { AppRole, OrganisationRead, UserRead } from "@/types/auth";
import { cn } from "@/lib/utils";

export const Route = createFileRoute("/admin")({ component: AdminConsole });

const tabs = ["Users & Roles", "Metrics"] as const;

function AdminConsole() {
  const user = useAuthStore((s) => s.user);
  const [tab, setTab] = useState<(typeof tabs)[number]>("Users & Roles");
  const [users, setUsers] = useState<UserRead[]>([]);
  const [orgs, setOrgs] = useState<OrganisationRead[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [form, setForm] = useState({
    email: "",
    password: "",
    full_name: "",
    role: "delivery_manager" as AppRole,
    org_id: "",
  });

  const canManageUsers = user?.permissions.can_manage_users ?? false;

  const load = async () => {
    if (!canManageUsers) return;
    setLoading(true);
    setError(null);
    try {
      const [userRows, orgRows] = await Promise.all([listUsers(), listOrganisations()]);
      setUsers(userRows);
      setOrgs(orgRows);
      if (!form.org_id && orgRows[0]) setForm((f) => ({ ...f, org_id: orgRows[0].id }));
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load admin data.");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    void load();
  }, [canManageUsers]);

  const onCreateUser = async (event: React.FormEvent) => {
    event.preventDefault();
    setError(null);
    try {
      await createUser({
        email: form.email,
        password: form.password,
        full_name: form.full_name || undefined,
        role: form.role,
        org_id: form.org_id,
      });
      setForm((f) => ({ ...f, email: "", password: "", full_name: "" }));
      await load();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to create user.");
    }
  };

  if (!canManageUsers) {
    return (
      <div className="rounded-md border border-border bg-card p-6 text-sm text-muted-foreground">
        Super admin access is required to manage users and platform configuration.
      </div>
    );
  }

  return (
    <div className="space-y-5">
      <div className="flex flex-wrap gap-1 rounded-md border border-border bg-card p-1 text-xs">
        {tabs.map((t) => (
          <button key={t} onClick={() => setTab(t)} className={cn("rounded px-3 py-1.5", tab === t ? "bg-elevated font-medium" : "text-muted-foreground hover:bg-elevated")}>{t}</button>
        ))}
      </div>

      {error && <p className="text-sm text-destructive">{error}</p>}

      {tab === "Users & Roles" && (
        <div className="grid gap-5 lg:grid-cols-2">
          <Card>
            <SectionHeader title="Users" sub={loading ? "Loading…" : `${users.length} accounts`} />
            <div className="max-h-80 overflow-auto">
              <table className="w-full text-xs">
                <thead className="text-left text-muted-foreground">
                  <tr className="border-b border-border">
                    <th className="py-2 pr-3 font-medium">Name</th>
                    <th className="py-2 pr-3 font-medium">Email</th>
                    <th className="py-2 pr-3 font-medium">Role</th>
                    <th className="py-2 pr-3 font-medium">Status</th>
                  </tr>
                </thead>
                <tbody>
                  {users.map((u) => (
                    <tr key={u.id} className="border-b border-border/50">
                      <td className="py-2 pr-3">{u.full_name ?? "—"}</td>
                      <td className="py-2 pr-3">{u.email}</td>
                      <td className="py-2 pr-3">{u.role}</td>
                      <td className="py-2 pr-3">{u.is_active ? "Active" : "Inactive"}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </Card>

          <Card>
            <SectionHeader title="Create user" sub="Provision Supabase Auth + platform profile" />
            <form onSubmit={onCreateUser} className="space-y-3 text-sm">
              <div className="space-y-1">
                <Label htmlFor="email">Email</Label>
                <Input id="email" type="email" value={form.email} onChange={(e) => setForm({ ...form, email: e.target.value })} required />
              </div>
              <div className="space-y-1">
                <Label htmlFor="password">Password</Label>
                <Input id="password" type="password" value={form.password} onChange={(e) => setForm({ ...form, password: e.target.value })} required />
              </div>
              <div className="space-y-1">
                <Label htmlFor="full_name">Full name</Label>
                <Input id="full_name" value={form.full_name} onChange={(e) => setForm({ ...form, full_name: e.target.value })} />
              </div>
              <div className="space-y-1">
                <Label htmlFor="role">Role</Label>
                <select
                  id="role"
                  className="flex h-9 w-full rounded-md border border-input bg-background px-3 text-sm"
                  value={form.role}
                  onChange={(e) => setForm({ ...form, role: e.target.value as AppRole })}
                >
                  <option value="client">client</option>
                  <option value="delivery_manager">delivery_manager</option>
                  <option value="bsg_leadership">bsg_leadership</option>
                  <option value="super_admin">super_admin</option>
                </select>
              </div>
              <div className="space-y-1">
                <Label htmlFor="org_id">Organisation</Label>
                <select
                  id="org_id"
                  className="flex h-9 w-full rounded-md border border-input bg-background px-3 text-sm"
                  value={form.org_id}
                  onChange={(e) => setForm({ ...form, org_id: e.target.value })}
                  required
                >
                  {orgs.map((o) => (
                    <option key={o.id} value={o.id}>{o.name}</option>
                  ))}
                </select>
              </div>
              <Button type="submit">Create user</Button>
            </form>
          </Card>
        </div>
      )}

      {tab === "Metrics" && (
        <Card>
          <SectionHeader title="Metric configuration" sub="Use API /metric-configurations for CRUD" />
          <p className="text-sm text-muted-foreground">Metric configuration UI can be extended here. Super admins manage metrics via the API in this MVP.</p>
        </Card>
      )}
    </div>
  );
}
