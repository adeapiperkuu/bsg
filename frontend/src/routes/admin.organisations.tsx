import { createFileRoute } from "@tanstack/react-router";
import { useEffect, useMemo, useState, useCallback } from "react";
import { Building2, Pencil, Plus, RefreshCw, Search } from "lucide-react";

import { Card } from "@/components/bsg/widgets";
import { PageLoadingScreen } from "@/components/bsg/PageLoadingScreen";
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
import { editControlClass, toolbarIconButtonClass, USERS_PER_PAGE, visiblePages } from "@/lib/admin-shared";
import { createOrganisation, listOrganisations, updateOrganisation } from "@/lib/api";
import { useAuthStore } from "@/stores/useAuthStore";
import type { OrganisationRead } from "@/types/auth";
import { cn } from "@/lib/utils";

export const Route = createFileRoute("/admin/organisations")({ component: AdminOrganisationsPage });

const VERTICALS = ["life_sciences", "finance", "logistics", "other"] as const;

function formatVertical(vertical: string): string {
  return vertical
    .split("_")
    .map((part) => part.charAt(0).toUpperCase() + part.slice(1))
    .join(" ");
}

type StatusFilter = "all" | "active" | "inactive";

function AdminOrganisationsPage() {
  const user = useAuthStore((s) => s.user);
  const [orgs, setOrgs] = useState<OrganisationRead[]>([]);
  const [loading, setLoading] = useState(true);
  const [creating, setCreating] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [search, setSearch] = useState("");
  const [statusFilter, setStatusFilter] = useState<StatusFilter>("all");
  const [createOpen, setCreateOpen] = useState(false);
  const [editOpen, setEditOpen] = useState(false);
  const [editingOrg, setEditingOrg] = useState<OrganisationRead | null>(null);
  const [savingEdit, setSavingEdit] = useState(false);
  const [page, setPage] = useState(1);
  const [form, setForm] = useState({
    name: "",
    slug: "",
    vertical: VERTICALS[0] as string,
    region: "",
  });
  const [editForm, setEditForm] = useState({
    name: "",
    slug: "",
    vertical: VERTICALS[0] as string,
    region: "",
    is_active: true,
  });

  const canManageOrganisations = user?.permissions.can_manage_organisations ?? false;

  const filteredOrgs = useMemo(() => {
    const query = search.trim().toLowerCase();
    const filtered = orgs.filter((row) => {
      if (query) {
        const matches = [row.name, row.slug].some((value) => value.toLowerCase().includes(query));
        if (!matches) return false;
      }
      if (statusFilter === "active" && !row.is_active) return false;
      if (statusFilter === "inactive" && row.is_active) return false;
      return true;
    });
    return [...filtered].sort((a, b) => a.name.localeCompare(b.name, undefined, { sensitivity: "base" }));
  }, [orgs, search, statusFilter]);

  const totalPages = Math.max(1, Math.ceil(filteredOrgs.length / USERS_PER_PAGE));
  const currentPage = Math.min(page, totalPages);
  const pageStart = (currentPage - 1) * USERS_PER_PAGE;
  const pageOrgs = filteredOrgs.slice(pageStart, pageStart + USERS_PER_PAGE);

  const load = useCallback(async () => {
    if (!canManageOrganisations) return;
    setLoading(true);
    setError(null);
    try {
      setOrgs(await listOrganisations());
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load organisations.");
    } finally {
      setLoading(false);
    }
  }, [canManageOrganisations]);

  useEffect(() => {
    void load();
  }, [load]);

  useEffect(() => {
    setPage(1);
  }, [search, statusFilter]);

  useEffect(() => {
    if (page > totalPages) setPage(totalPages);
  }, [page, totalPages]);

  const clearFilters = () => {
    setSearch("");
    setStatusFilter("all");
  };

  const onCreateOrg = async (event: React.FormEvent) => {
    event.preventDefault();
    setError(null);
    setCreating(true);
    try {
      await createOrganisation(form);
      setForm({ name: "", slug: "", vertical: VERTICALS[0], region: "" });
      setCreateOpen(false);
      await load();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to create organisation.");
    } finally {
      setCreating(false);
    }
  };

  const openEditOrg = (target: OrganisationRead) => {
    setEditingOrg(target);
    setEditForm({
      name: target.name,
      slug: target.slug,
      vertical: target.vertical,
      region: target.region,
      is_active: target.is_active,
    });
    setEditOpen(true);
  };

  const onUpdateOrg = async (event: React.FormEvent) => {
    event.preventDefault();
    if (!editingOrg) return;
    setError(null);
    setSavingEdit(true);
    try {
      await updateOrganisation(editingOrg.id, editForm);
      setEditOpen(false);
      setEditingOrg(null);
      await load();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to update organisation.");
    } finally {
      setSavingEdit(false);
    }
  };

  return (
    <div className="space-y-5">
      <div className="flex justify-end">
        <Button className="w-full sm:w-auto" onClick={() => setCreateOpen(true)}>
          <Plus className="h-4 w-4" />
          Create Organisation
        </Button>
      </div>

      {error && !loading && (
        <div className="rounded-md border border-destructive/30 bg-destructive/10 px-3 py-2 text-sm text-destructive">
          {error}
        </div>
      )}

      {loading ? (
        <PageLoadingScreen />
      ) : (
      <Card className="overflow-hidden p-0">
        <div className="space-y-4 border-b border-border p-4 sm:p-5">
          <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
            <div className="min-w-0">
              <h3 className="text-sm font-semibold tracking-tight text-foreground">All Organisations</h3>
              <p className="mt-0.5 text-xs text-muted-foreground">
                {`Showing ${pageOrgs.length ? pageStart + 1 : 0}-${Math.min(pageStart + pageOrgs.length, filteredOrgs.length)} of ${filteredOrgs.length} organisations`}
              </p>
            </div>
            <div className="flex w-full items-center gap-2 sm:w-auto">
              <Button
                variant="outline"
                size="icon"
                className={cn(toolbarIconButtonClass, "shrink-0")}
                onClick={() => void load()}
                disabled={loading}
                aria-label="Refresh organisations"
                title="Refresh organisations"
              >
                <RefreshCw className={cn("h-4 w-4", loading && "animate-spin")} />
              </Button>
            </div>
          </div>
          <div className="flex flex-col gap-2 lg:flex-row lg:flex-wrap lg:items-center">
            <div className="relative min-w-0 flex-1 lg:min-w-[220px] lg:max-w-sm">
              <Search className="pointer-events-none absolute left-3.5 top-1/2 h-4 w-4 -translate-y-1/2 text-[color:var(--brand)]" />
              <Input
                aria-label="Search organisations"
                className="h-10 rounded-full border-[color:var(--brand)]/25 bg-[color:var(--brand)]/5 pl-10 text-[color:var(--brand)] shadow-none placeholder:text-[color:var(--brand)]/55 focus-visible:border-[color:var(--brand)] focus-visible:ring-2 focus-visible:ring-[color:var(--brand)]/20"
                placeholder="Search by name or slug"
                value={search}
                onChange={(e) => setSearch(e.target.value)}
              />
            </div>
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
            <Button type="button" variant="outline" className="h-10 w-full lg:w-auto" onClick={clearFilters}>
              Clear Filters
            </Button>
          </div>
        </div>

        <Table>
          <TableHeader>
            <TableRow className="hover:bg-transparent">
              <TableHead className="pl-5">Name</TableHead>
              <TableHead className="hidden sm:table-cell">Slug</TableHead>
              <TableHead className="hidden md:table-cell">Vertical</TableHead>
              <TableHead className="hidden lg:table-cell">Region</TableHead>
              <TableHead className="hidden sm:table-cell">Status</TableHead>
              <TableHead className="pr-5 text-right">Actions</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {pageOrgs.map((org) => (
              <TableRow key={org.id}>
                <TableCell className="min-w-36 pl-5 font-medium text-foreground">
                  <div className="flex items-center gap-2">
                    <Building2 className="h-4 w-4 shrink-0 text-muted-foreground" />
                    <span>{org.name}</span>
                  </div>
                  <div className="mt-1 text-xs font-normal text-muted-foreground sm:hidden">{org.slug}</div>
                </TableCell>
                <TableCell className="hidden text-muted-foreground sm:table-cell">{org.slug}</TableCell>
                <TableCell className="hidden md:table-cell">{formatVertical(org.vertical)}</TableCell>
                <TableCell className="hidden text-muted-foreground lg:table-cell">{org.region}</TableCell>
                <TableCell className="hidden sm:table-cell">
                  <span
                    className={cn(
                      "inline-flex rounded-full border px-2 py-0.5 text-xs font-medium",
                      org.is_active
                        ? "border-[color:var(--success)]/30 bg-[color:var(--success)]/15 text-[color:var(--success)]"
                        : "border-border bg-secondary text-muted-foreground",
                    )}
                  >
                    {org.is_active ? "Active" : "Inactive"}
                  </span>
                </TableCell>
                <TableCell className="pr-5 text-right">
                  <Button
                    type="button"
                    variant="ghost"
                    size="icon"
                    onClick={() => openEditOrg(org)}
                    aria-label={`Edit ${org.name}`}
                    title="Edit organisation"
                  >
                    <Pencil className="h-4 w-4" />
                  </Button>
                </TableCell>
              </TableRow>
            ))}
            {pageOrgs.length === 0 && (
              <TableRow>
                <TableCell colSpan={6} className="h-28 text-center text-muted-foreground">
                  No organisations match this search.
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
      )}

      <Dialog open={createOpen} onOpenChange={setCreateOpen}>
        <DialogContent className="max-h-[calc(100svh-1rem)] w-[calc(100vw-1rem)] max-w-2xl gap-0 overflow-hidden p-0 sm:w-full">
          <DialogHeader className="border-b border-border bg-elevated/60 px-4 py-4 sm:px-6 sm:py-5">
            <div className="flex items-start gap-3 pr-8">
              <div className="grid h-11 w-11 shrink-0 place-items-center rounded-full bg-[color:var(--brand)] text-[color:var(--brand-foreground)]">
                <Building2 className="h-5 w-5" />
              </div>
              <div className="min-w-0 flex-1">
                <DialogTitle>Create Organisation</DialogTitle>
                <DialogDescription className="mt-1">
                  Provision a new tenant. Users can then be assigned to it.
                </DialogDescription>
              </div>
            </div>
          </DialogHeader>
          <form onSubmit={onCreateOrg}>
            <div className="max-h-[calc(100svh-14rem)] space-y-5 overflow-y-auto px-4 py-4 sm:max-h-[70vh] sm:px-6 sm:py-5">
              <section className="space-y-3">
                <div className="grid gap-4 sm:grid-cols-2">
                  <div className="space-y-1.5 sm:col-span-2">
                    <Label htmlFor="name">Name</Label>
                    <Input
                      id="name"
                      placeholder="Acme Life Sciences"
                      value={form.name}
                      onChange={(e) => setForm({ ...form, name: e.target.value })}
                      className="h-10 shadow-none"
                      required
                    />
                  </div>
                  <div className="space-y-1.5 sm:col-span-2">
                    <Label htmlFor="slug">Slug</Label>
                    <Input
                      id="slug"
                      placeholder="acme-lifesci"
                      value={form.slug}
                      onChange={(e) => setForm({ ...form, slug: e.target.value })}
                      className="h-10 shadow-none"
                      required
                    />
                    <p className="text-xs text-muted-foreground">URL-safe identifier, must be unique.</p>
                  </div>
                  <div className="grid gap-1.5">
                    <Label htmlFor="vertical">Vertical</Label>
                    <select
                      id="vertical"
                      className={`${editControlClass} w-full`}
                      value={form.vertical}
                      onChange={(e) => setForm({ ...form, vertical: e.target.value })}
                    >
                      {VERTICALS.map((v) => (
                        <option key={v} value={v}>
                          {formatVertical(v)}
                        </option>
                      ))}
                    </select>
                  </div>
                  <div className="space-y-1.5">
                    <Label htmlFor="region">Region</Label>
                    <Input
                      id="region"
                      placeholder="EU"
                      value={form.region}
                      onChange={(e) => setForm({ ...form, region: e.target.value })}
                      className="h-10 shadow-none"
                      required
                    />
                    <p className="text-xs text-muted-foreground">For data-residency tracking, e.g. "EU" or "US".</p>
                  </div>
                </div>
              </section>
            </div>
            <DialogFooter className="gap-2 border-t border-border bg-elevated/60 px-4 py-4 sm:px-6">
              <Button type="button" variant="outline" className="w-full sm:w-auto" onClick={() => setCreateOpen(false)}>
                Cancel
              </Button>
              <Button type="submit" className="w-full sm:w-auto" disabled={creating}>
                {creating ? "Creating..." : "Create Organisation"}
              </Button>
            </DialogFooter>
          </form>
        </DialogContent>
      </Dialog>

      <Dialog open={editOpen} onOpenChange={setEditOpen}>
        <DialogContent className="max-h-[calc(100svh-1rem)] w-[calc(100vw-1rem)] max-w-2xl gap-0 overflow-hidden p-0 sm:w-full">
          <DialogHeader className="border-b border-border bg-elevated/60 px-4 py-4 sm:px-6 sm:py-5">
            <div className="flex items-start gap-3 pr-8">
              <div className="grid h-11 w-11 shrink-0 place-items-center rounded-full bg-[color:var(--brand)] text-[color:var(--brand-foreground)]">
                <Building2 className="h-5 w-5" />
              </div>
              <div className="min-w-0 flex-1">
                <DialogTitle>Edit Organisation</DialogTitle>
                <DialogDescription className="mt-1">Update tenant details or deactivate access.</DialogDescription>
                <div className="mt-3 flex flex-wrap items-center gap-2 text-xs">
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
          <form onSubmit={onUpdateOrg}>
            <div className="max-h-[calc(100svh-14rem)] space-y-5 overflow-y-auto px-4 py-4 sm:max-h-[70vh] sm:px-6 sm:py-5">
              <section className="space-y-3">
                <div className="grid gap-4 sm:grid-cols-2">
                  <div className="space-y-1.5 sm:col-span-2">
                    <Label htmlFor="edit_name">Name</Label>
                    <Input
                      id="edit_name"
                      value={editForm.name}
                      onChange={(e) => setEditForm({ ...editForm, name: e.target.value })}
                      className="h-10 shadow-none"
                      required
                    />
                  </div>
                  <div className="space-y-1.5 sm:col-span-2">
                    <Label htmlFor="edit_slug">Slug</Label>
                    <Input
                      id="edit_slug"
                      value={editForm.slug}
                      onChange={(e) => setEditForm({ ...editForm, slug: e.target.value })}
                      className="h-10 shadow-none"
                      required
                    />
                  </div>
                  <div className="grid gap-1.5">
                    <Label htmlFor="edit_vertical">Vertical</Label>
                    <select
                      id="edit_vertical"
                      className={`${editControlClass} w-full`}
                      value={editForm.vertical}
                      onChange={(e) => setEditForm({ ...editForm, vertical: e.target.value })}
                    >
                      {VERTICALS.map((v) => (
                        <option key={v} value={v}>
                          {formatVertical(v)}
                        </option>
                      ))}
                    </select>
                  </div>
                  <div className="space-y-1.5">
                    <Label htmlFor="edit_region">Region</Label>
                    <Input
                      id="edit_region"
                      value={editForm.region}
                      onChange={(e) => setEditForm({ ...editForm, region: e.target.value })}
                      className="h-10 shadow-none"
                      required
                    />
                  </div>
                </div>
              </section>

              <section className="space-y-3">
                <div className="flex flex-col gap-3 rounded-md border border-border bg-background px-4 py-3 sm:flex-row sm:items-center sm:justify-between sm:gap-4">
                  <div className="min-w-0">
                    <div className="text-sm font-medium">
                      {editForm.is_active ? "Active organisation" : "Inactive organisation"}
                    </div>
                    <div className="mt-0.5 text-xs text-muted-foreground">
                      Inactive organisations' users cannot access the platform.
                    </div>
                  </div>
                  <div className="flex shrink-0 items-center justify-between gap-2 sm:justify-start">
                    <span className="text-xs text-muted-foreground">{editForm.is_active ? "Active" : "Inactive"}</span>
                    <Switch
                      checked={editForm.is_active}
                      onCheckedChange={(checked) => setEditForm({ ...editForm, is_active: checked })}
                      aria-label="Toggle organisation status"
                    />
                  </div>
                </div>
              </section>
            </div>
            <DialogFooter className="gap-2 border-t border-border bg-elevated/60 px-4 py-4 sm:px-6">
              <Button type="button" variant="outline" className="w-full sm:w-auto" onClick={() => setEditOpen(false)}>
                Cancel
              </Button>
              <Button type="submit" className="w-full sm:w-auto" disabled={savingEdit}>
                {savingEdit ? "Saving..." : "Save Changes"}
              </Button>
            </DialogFooter>
          </form>
        </DialogContent>
      </Dialog>
    </div>
  );
}
