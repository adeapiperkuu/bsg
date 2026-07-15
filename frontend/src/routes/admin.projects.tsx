import { createFileRoute } from "@tanstack/react-router";
import { useEffect, useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { AlertTriangle, FolderKanban, PauseCircle, RefreshCw, Search } from "lucide-react";

import { Card } from "@/components/bsg/widgets";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { editControlClass, USERS_PER_PAGE, visiblePages } from "@/lib/admin-shared";
import { adminProjectsQueryOptions } from "@/lib/queries/delivery";
import { cn } from "@/lib/utils";

export const Route = createFileRoute("/admin/projects")({ component: AdminProjectsPage });

type StatusFilter = "all" | "active" | "ramping" | "paused" | "completed" | "cancelled";

function formatStatus(status: string): string {
  return status
    .split("_")
    .map((p) => p.charAt(0).toUpperCase() + p.slice(1))
    .join(" ");
}

function statusBadgeClass(status: string): string {
  switch (status) {
    case "active":
      return "border-[color:var(--success)]/30 bg-[color:var(--success)]/15 text-[color:var(--success)]";
    case "ramping":
      return "border-[color:var(--brand)]/30 bg-[color:var(--brand)]/10 text-[color:var(--brand)]";
    case "paused":
      return "border-amber-500/30 bg-amber-500/15 text-amber-600";
    case "cancelled":
      return "border-destructive/30 bg-destructive/10 text-destructive";
    default:
      return "border-border bg-secondary text-muted-foreground";
  }
}

function AdminProjectsPage() {
  const projectsQuery = useQuery(adminProjectsQueryOptions);
  const projects = useMemo(() => projectsQuery.data ?? [], [projectsQuery.data]);
  const loading = projectsQuery.isFetching;
  const error = projectsQuery.error
    ? projectsQuery.error instanceof Error
      ? projectsQuery.error.message
      : "Failed to load projects."
    : null;
  const [search, setSearch] = useState("");
  const [statusFilter, setStatusFilter] = useState<StatusFilter>("all");
  const [organisationFilter, setOrganisationFilter] = useState<string>("all");
  const [page, setPage] = useState(1);

  /** Options come from the loaded projects, so the list never offers an org with no rows. */
  const organisations = useMemo(() => {
    const byId = new Map<string, string>();
    for (const p of projects) byId.set(p.org_id, p.org_name);
    return [...byId].
      map(([id, name]) => ({ id, name })).
      sort((a, b) => a.name.localeCompare(b.name, undefined, { sensitivity: "base" }));
  }, [projects]);

  const filtered = useMemo(() => {
    const q = search.trim().toLowerCase();
    return projects.filter((p) => {
      if (q && ![p.name, p.org_name, p.vertical].some((v) => v.toLowerCase().includes(q))) return false;
      if (statusFilter !== "all" && p.status !== statusFilter) return false;
      if (organisationFilter !== "all" && p.org_id !== organisationFilter) return false;
      return true;
    });
  }, [projects, search, statusFilter, organisationFilter]);

  const { activeCount, rampingPaused, withDrift } = useMemo(
    () => ({
      activeCount: projects.filter((p) => p.status === "active").length,
      rampingPaused: projects.filter((p) => p.status === "ramping" || p.status === "paused").length,
      withDrift: projects.filter((p) => p.active_drift_alerts > 0).length,
    }),
    [projects],
  );

  const totalPages = Math.max(1, Math.ceil(filtered.length / USERS_PER_PAGE));
  const currentPage = Math.min(page, totalPages);
  const pageStart = (currentPage - 1) * USERS_PER_PAGE;
  const pageRows = filtered.slice(pageStart, pageStart + USERS_PER_PAGE);

  useEffect(() => {
    setPage(1);
  }, [search, statusFilter, organisationFilter]);

  useEffect(() => {
    if (page > totalPages) setPage(totalPages);
  }, [page, totalPages]);

  return (
    <div className="space-y-5">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <p className="text-sm text-muted-foreground">Cross-org project health and quality posture.</p>
        <Button variant="outline" size="sm" onClick={() => void projectsQuery.refetch()} disabled={loading}>
          <RefreshCw className={cn("h-4 w-4", loading && "animate-spin")} />
          Refresh
        </Button>
      </div>

      {error && (
        <div className="rounded-md border border-destructive/30 bg-destructive/10 px-3 py-2 text-sm text-destructive">
          {error}
        </div>
      )}

      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
        <Card>
          <p className="text-xs font-medium uppercase tracking-wide text-muted-foreground">Total Projects</p>
          <p className="mt-2 text-2xl font-semibold">{projects.length}</p>
        </Card>
        <Card>
          <div className="flex items-center justify-between">
            <div>
              <p className="text-xs font-medium uppercase tracking-wide text-muted-foreground">Active</p>
              <p className="mt-2 text-2xl font-semibold">{activeCount}</p>
            </div>
            <FolderKanban className="h-5 w-5 text-primary" />
          </div>
        </Card>
        <Card>
          <div className="flex items-center justify-between">
            <div>
              <p className="text-xs font-medium uppercase tracking-wide text-muted-foreground">Ramping / Paused</p>
              <p className="mt-2 text-2xl font-semibold">{rampingPaused}</p>
            </div>
            <PauseCircle className="h-5 w-5 text-muted-foreground" />
          </div>
        </Card>
        <Card>
          <div className="flex items-center justify-between">
            <div>
              <p className="text-xs font-medium uppercase tracking-wide text-muted-foreground">With Drift Alerts</p>
              <p className="mt-2 text-2xl font-semibold">{withDrift}</p>
            </div>
            <AlertTriangle className="h-5 w-5 text-amber-500" />
          </div>
        </Card>
      </div>

      <Card className="overflow-hidden p-0">
        <div className="space-y-4 border-b border-border p-4 sm:p-5">
          <div className="min-w-0">
            <h3 className="text-sm font-semibold tracking-tight text-foreground">All Projects</h3>
            <p className="mt-0.5 text-xs text-muted-foreground">
              {`Showing ${pageRows.length ? pageStart + 1 : 0}-${Math.min(pageStart + pageRows.length, filtered.length)} of ${filtered.length} projects`}
            </p>
          </div>
          <div className="flex flex-col gap-2 lg:flex-row lg:flex-wrap lg:items-center">
            <div className="relative min-w-0 flex-1 lg:min-w-[220px] lg:max-w-sm">
              <Search className="pointer-events-none absolute left-3.5 top-1/2 h-4 w-4 -translate-y-1/2 text-[color:var(--brand)]" />
              <Input
                aria-label="Search projects"
                className="h-10 rounded-full border-[color:var(--brand)]/25 bg-[color:var(--brand)]/5 pl-10 text-[color:var(--brand)] shadow-none placeholder:text-[color:var(--brand)]/55 focus-visible:border-[color:var(--brand)] focus-visible:ring-2 focus-visible:ring-[color:var(--brand)]/20"
                placeholder="Search name, org, vertical…"
                value={search}
                onChange={(e) => setSearch(e.target.value)}
              />
            </div>
            <select
              aria-label="Filter by status"
              className={cn(editControlClass, "w-full lg:w-auto lg:min-w-[160px]")}
              value={statusFilter}
              onChange={(e) => setStatusFilter(e.target.value as StatusFilter)}
            >
              <option value="all">All statuses</option>
              <option value="active">Active</option>
              <option value="ramping">Ramping</option>
              <option value="paused">Paused</option>
              <option value="completed">Completed</option>
              <option value="cancelled">Cancelled</option>
            </select>
            <select
              aria-label="Filter by organisation"
              className={cn(editControlClass, "w-full lg:w-auto lg:min-w-[180px]")}
              value={organisationFilter}
              onChange={(e) => setOrganisationFilter(e.target.value)}
            >
              <option value="all">All Organisations</option>
              {organisations.map((org) => (
                <option key={org.id} value={org.id}>
                  {org.name}
                </option>
              ))}
            </select>
          </div>
        </div>

        <Table>
          <TableHeader>
            <TableRow className="hover:bg-transparent">
              <TableHead className="pl-5">Project</TableHead>
              <TableHead className="hidden md:table-cell">Organisation</TableHead>
              <TableHead>Status</TableHead>
              <TableHead className="hidden xl:table-cell">Vertical</TableHead>
              <TableHead className="hidden xl:table-cell">Start</TableHead>
              <TableHead className="hidden lg:table-cell">Latest QA</TableHead>
              <TableHead className="hidden sm:table-cell">Drift</TableHead>
              <TableHead className="hidden pr-5 lg:table-cell">Data gaps</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {loading && pageRows.length === 0 && (
              <TableRow>
                <TableCell colSpan={8} className="h-28 text-center text-muted-foreground">
                  Loading projects…
                </TableCell>
              </TableRow>
            )}
            {!loading && pageRows.length === 0 && (
              <TableRow>
                <TableCell colSpan={8} className="h-28 text-center text-muted-foreground">
                  No projects match your filters.
                </TableCell>
              </TableRow>
            )}
            {pageRows.map((p) => (
              <TableRow key={p.id}>
                <TableCell className="min-w-36 pl-5 font-medium text-foreground">
                  <div>{p.name}</div>
                  <div className="mt-1 text-xs font-normal text-muted-foreground md:hidden">
                    {p.org_name}
                  </div>
                </TableCell>
                <TableCell className="hidden text-muted-foreground md:table-cell">
                  {p.org_name}
                </TableCell>
                <TableCell>
                  <span
                    className={cn(
                      "inline-flex whitespace-nowrap rounded-full border px-2 py-0.5 text-xs font-medium",
                      statusBadgeClass(p.status),
                    )}
                  >
                    {formatStatus(p.status)}
                  </span>
                </TableCell>
                <TableCell className="hidden text-muted-foreground xl:table-cell">
                  {p.vertical}
                </TableCell>
                <TableCell className="hidden whitespace-nowrap text-muted-foreground xl:table-cell">
                  {p.start_date}
                </TableCell>
                <TableCell className="hidden whitespace-nowrap tabular-nums text-muted-foreground lg:table-cell">
                  {p.latest_iso_week != null ? `W${p.latest_iso_week}/${p.latest_iso_year}` : "—"}
                </TableCell>
                <TableCell className="hidden sm:table-cell">
                  {p.active_drift_alerts > 0 ? (
                    <span className="inline-flex items-center gap-1 rounded-full border border-destructive/30 bg-destructive/10 px-2 py-0.5 text-xs font-medium tabular-nums text-destructive">
                      <AlertTriangle className="h-3 w-3" />
                      {p.active_drift_alerts}
                    </span>
                  ) : (
                    <span className="tabular-nums text-muted-foreground">0</span>
                  )}
                </TableCell>
                <TableCell className="hidden pr-5 lg:table-cell">
                  {p.data_gap_teams.length > 0 ? (
                    <span
                      className="inline-flex whitespace-nowrap rounded-full border border-amber-500/30 bg-amber-500/15 px-2 py-0.5 text-xs font-medium text-amber-600"
                      title={p.data_gap_teams.join(", ")}
                    >
                      {p.data_gap_teams.length} team{p.data_gap_teams.length !== 1 ? "s" : ""}
                    </span>
                  ) : (
                    <span className="text-muted-foreground">—</span>
                  )}
                </TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>

        {totalPages > 1 && (
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
              {visiblePages(currentPage, totalPages).map((p, i, arr) => (
                <div key={p} className="flex items-center gap-2">
                  {i > 0 && arr[i - 1] !== p - 1 && (
                    <span className="px-1 text-xs text-muted-foreground">…</span>
                  )}
                  <Button
                    type="button"
                    variant={p === currentPage ? "default" : "outline"}
                    size="sm"
                    className="min-w-8 px-2"
                    onClick={() => setPage(p)}
                  >
                    {p}
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
        )}
      </Card>
    </div>
  );
}
