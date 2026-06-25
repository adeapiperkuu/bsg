import { createFileRoute } from "@tanstack/react-router";
import { useEffect, useMemo, useState } from "react";
import { AlertTriangle, FolderKanban, PauseCircle, RefreshCw, Search } from "lucide-react";

import { Card } from "@/components/bsg/widgets";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { editControlClass, toolbarIconButtonClass, USERS_PER_PAGE, visiblePages } from "@/lib/admin-shared";
import { listAdminProjects, type AdminProject } from "@/lib/api";
import { cn } from "@/lib/utils";

export const Route = createFileRoute("/admin/projects")({ component: AdminProjectsPage });

type StatusFilter = "all" | "active" | "ramping" | "paused" | "completed" | "cancelled";

function formatStatus(status: string): string {
  return status
    .split("_")
    .map((p) => p.charAt(0).toUpperCase() + p.slice(1))
    .join(" ");
}

function AdminProjectsPage() {
  const [projects, setProjects] = useState<AdminProject[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [search, setSearch] = useState("");
  const [statusFilter, setStatusFilter] = useState<StatusFilter>("all");
  const [page, setPage] = useState(1);

  const load = async () => {
    setLoading(true);
    setError(null);
    try {
      setProjects(await listAdminProjects());
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load projects.");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    void load();
  }, []);

  const filtered = useMemo(() => {
    const q = search.trim().toLowerCase();
    return projects.filter((p) => {
      if (q && ![p.name, p.org_name, p.vertical].some((v) => v.toLowerCase().includes(q))) return false;
      if (statusFilter !== "all" && p.status !== statusFilter) return false;
      return true;
    });
  }, [projects, search, statusFilter]);

  const activeCount = projects.filter((p) => p.status === "active").length;
  const rampingPaused = projects.filter((p) => p.status === "ramping" || p.status === "paused").length;
  const withDrift = projects.filter((p) => p.active_drift_alerts > 0).length;

  const totalPages = Math.max(1, Math.ceil(filtered.length / USERS_PER_PAGE));
  const currentPage = Math.min(page, totalPages);
  const pageStart = (currentPage - 1) * USERS_PER_PAGE;
  const pageRows = filtered.slice(pageStart, pageStart + USERS_PER_PAGE);

  useEffect(() => {
    setPage(1);
  }, [search, statusFilter]);

  useEffect(() => {
    if (page > totalPages) setPage(totalPages);
  }, [page, totalPages]);

  return (
    <div className="space-y-5">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <p className="text-sm text-muted-foreground">Cross-org project health and quality posture.</p>
        <Button variant="outline" size="sm" onClick={() => void load()} disabled={loading}>
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
        <div className="flex flex-wrap items-center gap-2 border-b border-border p-3">
          <div className="relative min-w-[12rem] flex-1">
            <Search className="absolute left-2.5 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-muted-foreground" />
            <Input
              className="h-9 pl-8"
              placeholder="Search name, org, vertical…"
              value={search}
              onChange={(e) => setSearch(e.target.value)}
            />
          </div>
          <select
            className={cn(editControlClass, "h-9 w-auto")}
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
        </div>

        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>Project</TableHead>
              <TableHead>Organisation</TableHead>
              <TableHead>Status</TableHead>
              <TableHead>Vertical</TableHead>
              <TableHead>Start</TableHead>
              <TableHead>Latest QA</TableHead>
              <TableHead>Drift</TableHead>
              <TableHead>Data gaps</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {loading && pageRows.length === 0 && (
              <TableRow>
                <TableCell colSpan={8} className="text-center text-muted-foreground">
                  Loading projects…
                </TableCell>
              </TableRow>
            )}
            {!loading && pageRows.length === 0 && (
              <TableRow>
                <TableCell colSpan={8} className="text-center text-muted-foreground">
                  No projects match your filters.
                </TableCell>
              </TableRow>
            )}
            {pageRows.map((p) => (
              <TableRow key={p.id}>
                <TableCell className="font-medium">{p.name}</TableCell>
                <TableCell>{p.org_name}</TableCell>
                <TableCell>{formatStatus(p.status)}</TableCell>
                <TableCell>{p.vertical}</TableCell>
                <TableCell>{p.start_date}</TableCell>
                <TableCell>
                  {p.latest_iso_week != null ? `W${p.latest_iso_week}/${p.latest_iso_year}` : "—"}
                </TableCell>
                <TableCell>
                  {p.active_drift_alerts > 0 ? (
                    <span className="rounded-full bg-destructive/15 px-2 py-0.5 text-xs font-medium text-destructive">
                      {p.active_drift_alerts}
                    </span>
                  ) : (
                    <span className="text-muted-foreground">0</span>
                  )}
                </TableCell>
                <TableCell>
                  {p.data_gap_teams.length > 0 ? (
                    <span
                      className="rounded-full bg-amber-500/15 px-2 py-0.5 text-xs text-amber-600"
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
          <div className="flex items-center justify-center gap-1 border-t border-border p-3">
            {visiblePages(currentPage, totalPages).map((p, i, arr) => (
              <span key={p} className="flex items-center gap-1">
                {i > 0 && arr[i - 1] !== p - 1 && <span className="px-1 text-muted-foreground">…</span>}
                <button
                  type="button"
                  className={cn(toolbarIconButtonClass, "h-8 w-8 text-xs", currentPage === p && "ring-2 ring-ring")}
                  onClick={() => setPage(p)}
                >
                  {p}
                </button>
              </span>
            ))}
          </div>
        )}
      </Card>
    </div>
  );
}
