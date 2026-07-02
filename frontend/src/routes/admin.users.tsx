import { createFileRoute } from "@tanstack/react-router";
import { useEffect, useMemo, useState, useCallback } from "react";
import { Mail, Pencil, Plus, RefreshCw, Search } from "lucide-react";

import { Card } from "@/components/bsg/widgets";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Switch } from "@/components/ui/switch";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import {
  editControlClass,
  formatRole,
  initials,
  roles,
  toolbarIconButtonClass,
  USERS_PER_PAGE,
  visiblePages,
} from "@/lib/admin-shared";
import { ApiError, createUser, listOrganisations, listUsers, updateUser } from "@/lib/api";
import { useAuthStore } from "@/stores/useAuthStore";
import type { AppRole, OrganisationRead, UserRead } from "@/types/auth";
import { cn } from "@/lib/utils";

export const Route = createFileRoute("/admin/users")({ component: AdminUsersPage });

type StatusFilter = "all" | "active" | "inactive";
type RoleFilter = "all" | AppRole;

function AdminUsersPage() {
  const user = useAuthStore((s) => s.user);
  const [users, setUsers] = useState<UserRead[]>([]);
  const [orgs, setOrgs] = useState<OrganisationRead[]>([]);
  const [loading, setLoading] = useState(false);
  const [creating, setCreating] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [userSearch, setUserSearch] = useState("");
  const [roleFilter, setRoleFilter] = useState<RoleFilter>("all");
  const [statusFilter, setStatusFilter] = useState<StatusFilter>("all");
  const [organisationFilter, setOrganisationFilter] = useState<string>("all");
  const [createOpen, setCreateOpen] = useState(false);
  const [editOpen, setEditOpen] = useState(false);
  const [editingUser, setEditingUser] = useState<UserRead | null>(null);
  const [savingEdit, setSavingEdit] = useState(false);
  const [page, setPage] = useState(1);
  const [form, setForm] = useState({
    email: "",
    password: "",
    full_name: "",
    role: "delivery_manager" as AppRole,
    org_id: "",
  });
  const [editForm, setEditForm] = useState({
    full_name: "",
    password: "",
    role: "delivery_manager" as AppRole,
    org_id: "",
    is_active: true,
  });

  const canManageUsers = user?.permissions.can_manage_users ?? false;
  const filteredUsers = useMemo(() => {
    const query = userSearch.trim().toLowerCase();
    const filtered = users.filter((row) => {
      if (query) {
        const matchesSearch = [row.email, row.full_name ?? ""].some((value) =>
          value.toLowerCase().includes(query),
        );
        if (!matchesSearch) return false;
      }
      if (roleFilter !== "all" && row.role !== roleFilter) return false;
      if (statusFilter === "active" && !row.is_active) return false;
      if (statusFilter === "inactive" && row.is_active) return false;
      if (organisationFilter !== "all" && row.org_id !== organisationFilter) return false;
      return true;
    });
    return [...filtered].sort((a, b) => {
      const nameA = a.full_name?.trim() || a.email;
      const nameB = b.full_name?.trim() || b.email;
      return nameA.localeCompare(nameB, undefined, { sensitivity: "base" });
    });
  }, [users, userSearch, roleFilter, statusFilter, organisationFilter]);
  const totalPages = Math.max(1, Math.ceil(filteredUsers.length / USERS_PER_PAGE));
  const currentPage = Math.min(page, totalPages);
  const pageStart = (currentPage - 1) * USERS_PER_PAGE;
  const pageUsers = filteredUsers.slice(pageStart, pageStart + USERS_PER_PAGE);

  const load = useCallback(async () => {
    if (!canManageUsers) return;
    setLoading(true);
    setError(null);
    try {
      const [userRows, orgRows] = await Promise.all([listUsers(), listOrganisations()]);
      setUsers(userRows);
      setOrgs(orgRows);
      if (orgRows[0]) setForm((f) => (f.org_id ? f : { ...f, org_id: orgRows[0].id }));
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load users.");
    } finally {
      setLoading(false);
    }
  }, [canManageUsers]);

  useEffect(() => {
    void load();
  }, [load]);

  useEffect(() => {
    setPage(1);
  }, [userSearch, roleFilter, statusFilter, organisationFilter]);

  const clearFilters = () => {
    setUserSearch("");
    setRoleFilter("all");
    setStatusFilter("all");
    setOrganisationFilter("all");
  };

  useEffect(() => {
    if (page > totalPages) setPage(totalPages);
  }, [page, totalPages]);

  const onCreateUser = async (event: React.FormEvent) => {
    event.preventDefault();
    setError(null);
    setCreating(true);
    try {
      await createUser({
        email: form.email,
        password: form.password,
        full_name: form.full_name || undefined,
        role: form.role,
        org_id: form.org_id,
      });
      setForm((f) => ({ ...f, email: "", password: "", full_name: "" }));
      setCreateOpen(false);
      await load();
    } catch (err) {
      if (err instanceof ApiError && err.code === "EMAIL_ALREADY_EXISTS") {
        setUserSearch(form.email);
        setPage(1);
        setCreateOpen(false);
        await load();
      }
      setError(err instanceof Error ? err.message : "Failed to create user.");
    } finally {
      setCreating(false);
    }
  };

  const openEditUser = (target: UserRead) => {
    setEditingUser(target);
    setEditForm({
      full_name: target.full_name ?? "",
      password: "",
      role: target.role,
      org_id: target.org_id,
      is_active: target.is_active,
    });
    setEditOpen(true);
  };

  const onUpdateUser = async (event: React.FormEvent) => {
    event.preventDefault();
    if (!editingUser) return;
    setError(null);
    setSavingEdit(true);
    try {
      await updateUser(editingUser.id, {
        full_name: editForm.full_name || null,
        role: editForm.role,
        org_id: editForm.org_id,
        is_active: editForm.is_active,
        ...(editForm.password ? { password: editForm.password } : {}),
      });
      setEditOpen(false);
      setEditingUser(null);
      await load();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to update user.");
    } finally {
      setSavingEdit(false);
    }
  };

  return (
    <div className="space-y-5">
      <div className="flex justify-end">
        <Button className="w-full sm:w-auto" onClick={() => setCreateOpen(true)}>
          <Plus className="h-4 w-4" />
          Create User
        </Button>
      </div>

      {error && (
        <div className="rounded-md border border-destructive/30 bg-destructive/10 px-3 py-2 text-sm text-destructive">
          {error}
        </div>
      )}

      <Card className="overflow-hidden p-0">
        <div className="space-y-4 border-b border-border p-4 sm:p-5">
          <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
            <div className="min-w-0">
              <h3 className="text-sm font-semibold tracking-tight text-foreground">All Users</h3>
              <p className="mt-0.5 text-xs text-muted-foreground">
                {loading
                  ? "Loading accounts..."
                  : `Showing ${pageUsers.length ? pageStart + 1 : 0}-${Math.min(pageStart + pageUsers.length, filteredUsers.length)} of ${filteredUsers.length} users`}
              </p>
            </div>
            <div className="flex w-full items-center gap-2 sm:w-auto">
              <Button
                variant="outline"
                size="icon"
                className={cn(toolbarIconButtonClass, "shrink-0")}
                onClick={() => void load()}
                disabled={loading}
                aria-label="Refresh users"
                title="Refresh users"
              >
                <RefreshCw className={cn("h-4 w-4", loading && "animate-spin")} />
              </Button>
            </div>
          </div>
          <div className="flex flex-col gap-2 lg:flex-row lg:flex-wrap lg:items-center">
            <div className="relative min-w-0 flex-1 lg:min-w-[220px] lg:max-w-sm">
              <Search className="pointer-events-none absolute left-3.5 top-1/2 h-4 w-4 -translate-y-1/2 text-[color:var(--brand)]" />
              <Input
                aria-label="Search users"
                className="h-10 rounded-full border-[color:var(--brand)]/25 bg-[color:var(--brand)]/5 pl-10 text-[color:var(--brand)] shadow-none placeholder:text-[color:var(--brand)]/55 focus-visible:border-[color:var(--brand)] focus-visible:ring-2 focus-visible:ring-[color:var(--brand)]/20"
                placeholder="Search by name or email"
                value={userSearch}
                onChange={(e) => setUserSearch(e.target.value)}
              />
            </div>
            <select
              aria-label="Filter by role"
              className={cn(editControlClass, "w-full lg:w-auto lg:min-w-[160px]")}
              value={roleFilter}
              onChange={(e) => setRoleFilter(e.target.value as RoleFilter)}
            >
              <option value="all">All Roles</option>
              {roles.map((role) => (
                <option key={role} value={role}>
                  {formatRole(role)}
                </option>
              ))}
            </select>
            <select
              aria-label="Filter by status"
              className={cn(editControlClass, "w-full lg:w-auto lg:min-w-[140px]")}
              value={statusFilter}
              onChange={(e) => setStatusFilter(e.target.value as StatusFilter)}
            >
              <option value="all">Status</option>
              <option value="active">Active</option>
              <option value="inactive">Inactive</option>
            </select>
            <select
              aria-label="Filter by organisation"
              className={cn(editControlClass, "w-full lg:w-auto lg:min-w-[180px]")}
              value={organisationFilter}
              onChange={(e) => setOrganisationFilter(e.target.value)}
            >
              <option value="all">All Organisations</option>
              {orgs.map((org) => (
                <option key={org.id} value={org.id}>
                  {org.name}
                </option>
              ))}
            </select>
            <Button
              type="button"
              variant="outline"
              className="h-10 w-full lg:w-auto"
              onClick={clearFilters}
            >
              Clear Filters
            </Button>
          </div>
        </div>

        <Table>
          <TableHeader>
            <TableRow className="hover:bg-transparent">
              <TableHead className="pl-5">Name</TableHead>
              <TableHead>Email</TableHead>
              <TableHead className="hidden md:table-cell">Role</TableHead>
              <TableHead className="hidden lg:table-cell">Organisation</TableHead>
              <TableHead className="hidden sm:table-cell">Status</TableHead>
              <TableHead className="pr-5 text-right">Actions</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {pageUsers.map((u) => {
              const org = orgs.find((row) => row.id === u.org_id);
              return (
                <TableRow key={u.id}>
                  <TableCell className="min-w-36 pl-5 font-medium text-foreground">
                    <div>{u.full_name ?? "No name set"}</div>
                    <div className="mt-1 text-xs font-normal text-muted-foreground md:hidden">
                      {formatRole(u.role)}
                    </div>
                  </TableCell>
                  <TableCell className="max-w-[12rem] truncate text-muted-foreground sm:max-w-none">
                    {u.email}
                  </TableCell>
                  <TableCell className="hidden md:table-cell">{formatRole(u.role)}</TableCell>
                  <TableCell className="hidden text-muted-foreground lg:table-cell">
                    {org?.name ?? "Unassigned"}
                  </TableCell>
                  <TableCell className="hidden sm:table-cell">
                    <span
                      className={cn(
                        "inline-flex rounded-full border px-2 py-0.5 text-xs font-medium",
                        u.is_active
                          ? "border-[color:var(--success)]/30 bg-[color:var(--success)]/15 text-[color:var(--success)]"
                          : "border-border bg-secondary text-muted-foreground",
                      )}
                    >
                      {u.is_active ? "Active" : "Inactive"}
                    </span>
                  </TableCell>
                  <TableCell className="pr-5 text-right">
                    <Button
                      type="button"
                      variant="ghost"
                      size="icon"
                      onClick={() => openEditUser(u)}
                      aria-label={`Edit ${u.email}`}
                      title="Edit user"
                    >
                      <Pencil className="h-4 w-4" />
                    </Button>
                  </TableCell>
                </TableRow>
              );
            })}
            {pageUsers.length === 0 && (
              <TableRow>
                <TableCell colSpan={6} className="h-28 text-center text-muted-foreground">
                  {loading ? "Loading users..." : "No users match this search."}
                </TableCell>
              </TableRow>
            )}
          </TableBody>
        </Table>

        <div className="flex flex-col gap-3 border-t border-border p-4 sm:flex-row sm:items-center sm:justify-between">
          <p className="text-center text-xs text-muted-foreground sm:text-left">
            Page {currentPage} of {totalPages}
          </p>
          <div className="flex flex-wrap items-center justify-center gap-2 sm:justify-end">
            <Button
              type="button"
              variant="outline"
              size="sm"
              disabled={currentPage === 1}
              onClick={() => setPage((value) => Math.max(1, value - 1))}
            >
              Previous
            </Button>
            {visiblePages(currentPage, totalPages).map((pageNumber, index, pages) => (
              <div key={pageNumber} className="flex items-center gap-2">
                {index > 0 && pageNumber - pages[index - 1] > 1 && (
                  <span className="px-1 text-xs text-muted-foreground">...</span>
                )}
                <Button
                  type="button"
                  variant={pageNumber === currentPage ? "default" : "outline"}
                  size="sm"
                  className="min-w-8 px-2"
                  onClick={() => setPage(pageNumber)}
                >
                  {pageNumber}
                </Button>
              </div>
            ))}
            <Button
              type="button"
              variant="outline"
              size="sm"
              disabled={currentPage === totalPages}
              onClick={() => setPage((value) => Math.min(totalPages, value + 1))}
            >
              Next
            </Button>
          </div>
        </div>
      </Card>

      <Dialog open={createOpen} onOpenChange={setCreateOpen}>
        <DialogContent className="max-h-[calc(100svh-1rem)] w-[calc(100vw-1rem)] max-w-2xl gap-0 overflow-hidden p-0 sm:w-full">
          <DialogHeader className="border-b border-border bg-elevated/60 px-4 py-4 sm:px-6 sm:py-5">
            <div className="flex items-start gap-3 pr-8">
              <div className="grid h-11 w-11 shrink-0 place-items-center rounded-full bg-[color:var(--brand)] text-sm font-semibold text-[color:var(--brand-foreground)]">
                {initials(form.full_name || null, form.email || "new-user")}
              </div>
              <div className="min-w-0 flex-1">
                <DialogTitle>Create User</DialogTitle>
                <DialogDescription className="mt-1">
                  Provision a Supabase Auth account and connect it to a platform profile.
                </DialogDescription>
                <div className="mt-3 flex flex-wrap items-center gap-2 text-xs">
                  <span className="inline-flex items-center gap-1 rounded-full border border-border bg-background px-2 py-1 text-muted-foreground">
                    <Mail className="h-3.5 w-3.5" />
                    <span className="max-w-[180px] truncate sm:max-w-[260px]">
                      {form.email || "Email not set"}
                    </span>
                  </span>
                  <span className="inline-flex rounded-full border border-[color:var(--brand)]/25 bg-[color:var(--brand)]/10 px-2 py-1 font-medium text-[color:var(--brand)]">
                    New account
                  </span>
                </div>
              </div>
            </div>
          </DialogHeader>
          <form onSubmit={onCreateUser}>
            <div className="max-h-[calc(100svh-14rem)] space-y-5 overflow-y-auto px-4 py-4 sm:max-h-[70vh] sm:px-6 sm:py-5">
              <section className="space-y-3">
                <div className="grid gap-4 sm:grid-cols-2">
                  <div className="space-y-1.5 sm:col-span-2">
                    <Label htmlFor="email">Email</Label>
                    <Input
                      id="email"
                      type="email"
                      autoComplete="username"
                      placeholder="name@company.com"
                      value={form.email}
                      onChange={(e) => setForm({ ...form, email: e.target.value })}
                      className="h-10 shadow-none"
                      required
                    />
                  </div>
                  <div className="space-y-1.5 sm:col-span-2">
                    <Label htmlFor="full_name">Full name</Label>
                    <Input
                      id="full_name"
                      placeholder="Add the user's full name"
                      value={form.full_name}
                      onChange={(e) => setForm({ ...form, full_name: e.target.value })}
                      className="h-10 shadow-none"
                    />
                  </div>
                </div>
              </section>

              <section className="space-y-3">
                <div className="space-y-1.5">
                  <Label htmlFor="password">Temporary password</Label>
                  <Input
                    id="password"
                    type="password"
                    autoComplete="new-password"
                    placeholder="Enter a temporary password"
                    value={form.password}
                    onChange={(e) => setForm({ ...form, password: e.target.value })}
                    className="h-10 shadow-none"
                    required
                  />
                  <p className="text-xs text-muted-foreground">
                    The user can sign in with this password after the account is created.
                  </p>
                </div>
              </section>

              <section className="space-y-3">
                <div className="grid gap-4 sm:grid-cols-2">
                  <div className="grid gap-1.5">
                    <Label htmlFor="role">Role</Label>
                    <select
                      id="role"
                      className={`${editControlClass} w-full`}
                      value={form.role}
                      onChange={(e) => setForm({ ...form, role: e.target.value as AppRole })}
                    >
                      {roles.map((role) => (
                        <option key={role} value={role}>
                          {formatRole(role)}
                        </option>
                      ))}
                    </select>
                  </div>
                  <div className="grid gap-1.5">
                    <Label htmlFor="org_id">Organisation</Label>
                    <select
                      id="org_id"
                      className={`${editControlClass} w-full`}
                      value={form.org_id}
                      onChange={(e) => setForm({ ...form, org_id: e.target.value })}
                      required
                    >
                      {orgs.map((o) => (
                        <option key={o.id} value={o.id}>
                          {o.name}
                        </option>
                      ))}
                    </select>
                  </div>
                </div>
              </section>
            </div>
            <DialogFooter className="gap-2 border-t border-border bg-elevated/60 px-4 py-4 sm:px-6">
              <Button
                type="button"
                variant="outline"
                className="w-full sm:w-auto"
                onClick={() => setCreateOpen(false)}
              >
                Cancel
              </Button>
              <Button
                type="submit"
                className="w-full sm:w-auto"
                disabled={creating || !form.org_id}
              >
                {creating ? "Creating..." : "Create User"}
              </Button>
            </DialogFooter>
          </form>
        </DialogContent>
      </Dialog>

      <Dialog open={editOpen} onOpenChange={setEditOpen}>
        <DialogContent className="max-h-[calc(100svh-1rem)] w-[calc(100vw-1rem)] max-w-2xl gap-0 overflow-hidden p-0 sm:w-full">
          <DialogHeader className="border-b border-border bg-elevated/60 px-4 py-4 sm:px-6 sm:py-5">
            <div className="flex items-start gap-3 pr-8">
              <div className="grid h-11 w-11 shrink-0 place-items-center rounded-full bg-[color:var(--brand)] text-sm font-semibold text-[color:var(--brand-foreground)]">
                {editingUser ? initials(editingUser.full_name, editingUser.email) : "?"}
              </div>
              <div className="min-w-0 flex-1">
                <DialogTitle>Edit User</DialogTitle>
                <DialogDescription className="mt-1">
                  Manage profile details, permissions, account access, and password reset.
                </DialogDescription>
                <div className="mt-3 flex flex-wrap items-center gap-2 text-xs">
                  <span className="inline-flex items-center gap-1 rounded-full border border-border bg-background px-2 py-1 text-muted-foreground">
                    <Mail className="h-3.5 w-3.5" />
                    <span className="max-w-[180px] truncate sm:max-w-[260px]">
                      {editingUser?.email}
                    </span>
                  </span>
                  <span
                    className={cn(
                      "inline-flex rounded-full border px-2 py-1 font-medium",
                      editForm.is_active
                        ? "border-[color:var(--success)]/30 bg-[color:var(--success)]/15 text-[color:var(--success)]"
                        : "border-border bg-secondary text-muted-foreground",
                    )}
                  >
                    {editForm.is_active ? "Active" : "Inactive"}
                  </span>
                </div>
              </div>
            </div>
          </DialogHeader>
          <form onSubmit={onUpdateUser}>
            <div className="max-h-[calc(100svh-14rem)] space-y-5 overflow-y-auto px-4 py-4 sm:max-h-[70vh] sm:px-6 sm:py-5">
              <section className="space-y-3">
                <div className="grid gap-4 sm:grid-cols-2">
                  <div className="space-y-1.5 sm:col-span-2">
                    <Label htmlFor="edit_email">Email</Label>
                    <Input
                      id="edit_email"
                      value={editingUser?.email ?? ""}
                      disabled
                      className="h-10 bg-muted/50 shadow-none"
                    />
                  </div>
                  <div className="space-y-1.5 sm:col-span-2">
                    <Label htmlFor="edit_full_name">Full name</Label>
                    <Input
                      id="edit_full_name"
                      placeholder="Add the user's full name"
                      value={editForm.full_name}
                      onChange={(e) => setEditForm({ ...editForm, full_name: e.target.value })}
                      className="h-10 shadow-none"
                    />
                  </div>
                </div>
              </section>

              <section className="space-y-3">
                <div className="space-y-1.5">
                  <div className="flex items-center justify-between gap-3">
                    <Label htmlFor="edit_password">Reset password</Label>
                    <span className="text-xs text-muted-foreground">Optional</span>
                  </div>
                  <Input
                    id="edit_password"
                    type="password"
                    autoComplete="new-password"
                    placeholder="Enter a new password"
                    value={editForm.password}
                    onChange={(e) => setEditForm({ ...editForm, password: e.target.value })}
                    className="h-10 shadow-none"
                  />
                  <p className="text-xs text-muted-foreground">
                    Leave this empty to keep the current password.
                  </p>
                </div>
              </section>

              <section className="space-y-3">
                <div className="grid gap-4 sm:grid-cols-2">
                  <div className="grid gap-1.5">
                    <Label htmlFor="edit_role">Role</Label>
                    <select
                      id="edit_role"
                      className={`${editControlClass} w-full`}
                      value={editForm.role}
                      onChange={(e) =>
                        setEditForm({ ...editForm, role: e.target.value as AppRole })
                      }
                    >
                      {roles.map((role) => (
                        <option key={role} value={role}>
                          {formatRole(role)}
                        </option>
                      ))}
                    </select>
                  </div>
                  <div className="grid gap-1.5">
                    <Label htmlFor="edit_org_id">Organisation</Label>
                    <select
                      id="edit_org_id"
                      className={`${editControlClass} w-full`}
                      value={editForm.org_id}
                      onChange={(e) => setEditForm({ ...editForm, org_id: e.target.value })}
                      required
                    >
                      {orgs.map((o) => (
                        <option key={o.id} value={o.id}>
                          {o.name}
                        </option>
                      ))}
                    </select>
                  </div>
                </div>
              </section>

              <section className="space-y-3">
                <div className="flex flex-col gap-3 rounded-md border border-border bg-background px-4 py-3 sm:flex-row sm:items-center sm:justify-between sm:gap-4">
                  <div className="min-w-0">
                    <div className="text-sm font-medium">
                      {editForm.is_active ? "Active account" : "Inactive account"}
                    </div>
                    <div className="mt-0.5 text-xs text-muted-foreground">
                      Inactive users cannot sign in or access protected pages.
                    </div>
                  </div>
                  <div className="flex shrink-0 items-center justify-between gap-2 sm:justify-start">
                    <span className="text-xs text-muted-foreground">
                      {editForm.is_active ? "Active" : "Inactive"}
                    </span>
                    <Switch
                      checked={editForm.is_active}
                      onCheckedChange={(checked) =>
                        setEditForm({ ...editForm, is_active: checked })
                      }
                      aria-label="Toggle account status"
                    />
                  </div>
                </div>
              </section>
            </div>
            <DialogFooter className="gap-2 border-t border-border bg-elevated/60 px-4 py-4 sm:px-6">
              <Button
                type="button"
                variant="outline"
                className="w-full sm:w-auto"
                onClick={() => setEditOpen(false)}
              >
                Cancel
              </Button>
              <Button
                type="submit"
                className="w-full sm:w-auto"
                disabled={savingEdit || !editForm.org_id}
              >
                {savingEdit ? "Saving..." : "Save Changes"}
              </Button>
            </DialogFooter>
          </form>
        </DialogContent>
      </Dialog>
    </div>
  );
}
