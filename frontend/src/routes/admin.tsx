import { createFileRoute, Outlet } from "@tanstack/react-router";
import { createFileRoute } from "@tanstack/react-router";
import { useEffect, useMemo, useState } from "react";
import { Mail, Pencil, Plus, RefreshCw, Search, Users } from "lucide-react";

import { useAuthStore } from "@/stores/useAuthStore";

export const Route = createFileRoute("/admin")({ component: AdminLayout });

function AdminLayout() {
  const user = useAuthStore((s) => s.user);
  const canManageUsers = user?.permissions.can_manage_users ?? false;
const USERS_PER_PAGE = 12;
const roles: AppRole[] = ["client", "delivery_manager", "bsg_leadership", "super_admin"];
type StatusFilter = "all" | "active" | "inactive";
type RoleFilter = "all" | AppRole;
const editControlClass =
  "h-10 rounded-md border border-input bg-background px-3 text-sm shadow-none transition-colors focus:outline-none focus:ring-1 focus:ring-ring";
const toolbarIconButtonClass =
  "h-9 w-9 rounded-full border border-[color:var(--brand)] bg-[color:var(--brand)] text-[color:var(--brand-foreground)] shadow-none transition-colors hover:bg-[color:var(--brand)]/90 hover:text-[color:var(--brand-foreground)]";

function formatRole(role: AppRole): string {
  return role
    .split("_")
    .map((part) => part.charAt(0).toUpperCase() + part.slice(1))
    .join(" ");
}

function visiblePages(currentPage: number, totalPages: number): number[] {
  const pages = new Set([1, totalPages, currentPage - 1, currentPage, currentPage + 1]);
  return [...pages].filter((page) => page >= 1 && page <= totalPages).sort((a, b) => a - b);
}

function AdminConsole() {
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
  const activeUsers = users.filter((row) => row.is_active).length;
  const inactiveUsers = users.length - activeUsers;

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

  if (!canManageUsers) {
    return (
      <div className="rounded-md border border-border bg-card p-6 text-sm text-muted-foreground">
        Super admin access is required to manage users and platform configuration.
      </div>
    );
  }

  return <Outlet />;
}
