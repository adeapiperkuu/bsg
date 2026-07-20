import { createFileRoute } from "@tanstack/react-router";
import { Fragment, useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import {
  AlertTriangle,
  ChevronDown,
  ChevronRight,
  FolderKanban,
  PauseCircle,
  RefreshCw,
  Search,
} from "lucide-react";

import { Card } from "@/components/bsg/widgets";
import { PageLoadingScreen } from "@/components/bsg/PageLoadingScreen";
import { TablePagination } from "@/components/bsg/TablePagination";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { usePagination } from "@/hooks/usePagination";
import { editControlClass } from "@/lib/admin-shared";
import type { AdminProject } from "@/lib/api";
import { adminProjectsQueryOptions } from "@/lib/queries/delivery";
import { cn } from "@/lib/utils";

export const Route = createFileRoute("/admin/projects")({ component: AdminProjectsPage });

type StatusFilter = "all" | "active" | "ramping" | "paused" | "completed" | "cancelled";

type ProjectGroup = {
  key: string;
  name: string;
  org_id: string;
  org_name: string;
  vertical: string;
  status: string;
  start_date: string;
  active_drift_alerts: number;
  data_gap_teams: string[];
  latest_iso_year: number | null;
  latest_iso_week: number | null;
  sprints: AdminProject[];
};

const STATUS_RANK: Record<string, number> = {
  active: 0,
  ramping: 1,
  paused: 2,
  completed: 3,
  cancelled: 4,
};

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

function rollupStatus(sprints: AdminProject[]): string {
  if (sprints.length === 0) return "completed";
  return [...sprints].sort(
    (a, b) => (STATUS_RANK[a.status] ?? 99) - (STATUS_RANK[b.status] ?? 99),
  )[0]!.status;
}

function sprintLabel(sprint: AdminProject, projectName: string): string {
  const prefix = `${projectName} · `;
  if (sprint.name.startsWith(prefix)) return sprint.name.slice(prefix.length);
  return sprint.name;
}

function groupScopesIntoProjects(scopes: AdminProject[]): ProjectGroup[] {
  const groups = new Map<string, ProjectGroup>();

  for (const scope of scopes) {
    const key = scope.program_id ?? `scope:${scope.id}`;
    const name = scope.program_name ?? scope.name;
    const existing = groups.get(key);
    if (existing) {
      existing.sprints.push(scope);
      continue;
    }
    groups.set(key, {
      key,
      name,
      org_id: scope.org_id,
      org_name: scope.org_name,
      vertical: scope.vertical,
      status: scope.status,
      start_date: scope.start_date,
      active_drift_alerts: scope.active_drift_alerts,
      data_gap_teams: [...scope.data_gap_teams],
      latest_iso_year: scope.latest_iso_year,
      latest_iso_week: scope.latest_iso_week,
      sprints: [scope],
    });
  }

  return [...groups.values()]
    .map((group) => {
      const sprints = [...group.sprints].sort((a, b) => a.name.localeCompare(b.name));
      const drift = sprints.reduce((sum, s) => sum + s.active_drift_alerts, 0);
      const gaps = [...new Set(sprints.flatMap((s) => s.data_gap_teams))];
      const startDates = sprints.map((s) => s.start_date).sort();
      const withQa = sprints.filter((s) => s.latest_iso_year != null && s.latest_iso_week != null);
      const latestQa = withQa.sort((a, b) => {
        const ay = a.latest_iso_year ?? 0;
        const by = b.latest_iso_year ?? 0;
        if (ay !== by) return by - ay;
        return (b.latest_iso_week ?? 0) - (a.latest_iso_week ?? 0);
      })[0];

      return {
        ...group,
        sprints,
        status: rollupStatus(sprints),
        start_date: startDates[0] ?? group.start_date,
        active_drift_alerts: drift,
        data_gap_teams: gaps,
        latest_iso_year: latestQa?.latest_iso_year ?? null,
        latest_iso_week: latestQa?.latest_iso_week ?? null,
        vertical: sprints[0]?.vertical ?? group.vertical,
      };
    })
    .sort((a, b) => a.name.localeCompare(b.name, undefined, { sensitivity: "base" }));
}

function AdminProjectsPage() {
  const projectsQuery = useQuery(adminProjectsQueryOptions);
  const scopes = useMemo(() => projectsQuery.data ?? [], [projectsQuery.data]);
  const loading = projectsQuery.isFetching;
  const error = projectsQuery.error
    ? projectsQuery.error instanceof Error
      ? projectsQuery.error.message
      : "Failed to load projects."
    : null;
  const [search, setSearch] = useState("");
  const [statusFilter, setStatusFilter] = useState<StatusFilter>("all");
  const [organisationFilter, setOrganisationFilter] = useState<string>("all");
  const [expanded, setExpanded] = useState<Set<string>>(() => new Set());

  const projectGroups = useMemo(() => groupScopesIntoProjects(scopes), [scopes]);

  const organisations = useMemo(() => {
    const byId = new Map<string, string>();
    for (const p of projectGroups) byId.set(p.org_id, p.org_name);
    return [...byId]
      .map(([id, name]) => ({ id, name }))
      .sort((a, b) => a.name.localeCompare(b.name, undefined, { sensitivity: "base" }));
  }, [projectGroups]);

  const filtered = useMemo(() => {
    const q = search.trim().toLowerCase();
    return projectGroups.filter((p) => {
      if (
        q &&
        ![p.name, p.org_name, p.vertical, ...p.sprints.map((s) => s.name)].some((v) =>
          v.toLowerCase().includes(q),
        )
      ) {
        return false;
      }
      if (statusFilter !== "all" && p.status !== statusFilter) return false;
      if (organisationFilter !== "all" && p.org_id !== organisationFilter) return false;
      return true;
    });
  }, [projectGroups, search, statusFilter, organisationFilter]);

  const { activeCount, rampingPaused, withDrift } = useMemo(
    () => ({
      activeCount: projectGroups.filter((p) => p.status === "active").length,
      rampingPaused: projectGroups.filter((p) => p.status === "ramping" || p.status === "paused")
        .length,
      withDrift: projectGroups.filter((p) => p.active_drift_alerts > 0).length,
    }),
    [projectGroups],
  );

  const {
    currentPage,
    totalPages,
    setPage,
    pageItems: pageRows,
    rangeStart,
    rangeEnd,
    total,
  } = usePagination(filtered, `${search}|${statusFilter}|${organisationFilter}`);

  const toggleExpanded = (key: string) => {
    setExpanded((prev) => {
      const next = new Set(prev);
      if (next.has(key)) next.delete(key);
      else next.add(key);
      return next;
    });
  };

  if (projectsQuery.isLoading && scopes.length === 0 && !error) {
    return <PageLoadingScreen />;
  }

  return (
    <div className="space-y-5">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <p className="text-sm text-muted-foreground">Cross-org project health and quality posture.</p>
        <Button
          variant="outline"
          size="sm"
          onClick={() => void projectsQuery.refetch()}
          disabled={loading}
        >
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
          <p className="text-xs font-medium uppercase tracking-wide text-muted-foreground">
            Total Projects
          </p>
          <p className="mt-2 text-2xl font-semibold">{projectGroups.length}</p>
        </Card>
        <Card>
          <div className="flex items-center justify-between">
            <div>
              <p className="text-xs font-medium uppercase tracking-wide text-muted-foreground">
                Active
              </p>
              <p className="mt-2 text-2xl font-semibold">{activeCount}</p>
            </div>
            <FolderKanban className="h-5 w-5 text-primary" />
          </div>
        </Card>
        <Card>
          <div className="flex items-center justify-between">
            <div>
              <p className="text-xs font-medium uppercase tracking-wide text-muted-foreground">
                Ramping / Paused
              </p>
              <p className="mt-2 text-2xl font-semibold">{rampingPaused}</p>
            </div>
            <PauseCircle className="h-5 w-5 text-muted-foreground" />
          </div>
        </Card>
        <Card>
          <div className="flex items-center justify-between">
            <div>
              <p className="text-xs font-medium uppercase tracking-wide text-muted-foreground">
                With Drift Alerts
              </p>
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
              {`Showing ${rangeStart}-${rangeEnd} of ${total} projects`}
            </p>
          </div>
          <div className="flex flex-col gap-2 lg:flex-row lg:flex-wrap lg:items-center">
            <div className="relative min-w-0 flex-1 lg:min-w-[220px] lg:max-w-sm">
              <Search className="pointer-events-none absolute left-3.5 top-1/2 h-4 w-4 -translate-y-1/2 text-[color:var(--brand)]" />
              <Input
                aria-label="Search projects"
                className="h-10 rounded-full border-[color:var(--brand)]/25 bg-[color:var(--brand)]/5 pl-10 text-[color:var(--brand)] shadow-none placeholder:text-[color:var(--brand)]/55 focus-visible:border-[color:var(--brand)] focus-visible:ring-2 focus-visible:ring-[color:var(--brand)]/20"
                placeholder="Search name, org, vertical, sprint…"
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
              <TableHead className="w-10 pl-3" />
              <TableHead>Project</TableHead>
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
                <TableCell colSpan={9} className="h-28 text-center text-muted-foreground">
                  Loading projects…
                </TableCell>
              </TableRow>
            )}
            {!loading && pageRows.length === 0 && (
              <TableRow>
                <TableCell colSpan={9} className="h-28 text-center text-muted-foreground">
                  No projects match your filters.
                </TableCell>
              </TableRow>
            )}
            {pageRows.map((p) => {
              const isOpen = expanded.has(p.key);
              const hasSprints = p.sprints.length > 0;
              return (
                <Fragment key={p.key}>
                  <TableRow className={isOpen ? "bg-elevated/40" : undefined}>
                    <TableCell className="pl-3">
                      {hasSprints ? (
                        <button
                          type="button"
                          aria-label={isOpen ? `Collapse sprints for ${p.name}` : `Expand sprints for ${p.name}`}
                          aria-expanded={isOpen}
                          className="inline-flex h-7 w-7 items-center justify-center rounded border border-border text-muted-foreground hover:bg-elevated hover:text-foreground"
                          onClick={() => toggleExpanded(p.key)}
                        >
                          {isOpen ? (
                            <ChevronDown className="h-4 w-4" />
                          ) : (
                            <ChevronRight className="h-4 w-4" />
                          )}
                        </button>
                      ) : null}
                    </TableCell>
                    <TableCell className="min-w-36 font-medium text-foreground">
                      <button
                        type="button"
                        className="text-left hover:underline"
                        onClick={() => hasSprints && toggleExpanded(p.key)}
                      >
                        {p.name}
                      </button>
                      <div className="mt-0.5 text-xs font-normal text-muted-foreground">
                        {p.sprints.length} sprint{p.sprints.length === 1 ? "" : "s"}
                        <span className="md:hidden"> · {p.org_name}</span>
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
                          {p.data_gap_teams.length} team
                          {p.data_gap_teams.length !== 1 ? "s" : ""}
                        </span>
                      ) : (
                        <span className="text-muted-foreground">—</span>
                      )}
                    </TableCell>
                  </TableRow>
                  {isOpen &&
                    p.sprints.map((sprint) => (
                      <TableRow key={sprint.id} className="bg-card/40">
                        <TableCell className="pl-3" />
                        <TableCell className="pl-8 text-sm text-foreground">
                          {sprintLabel(sprint, p.name)}
                        </TableCell>
                        <TableCell className="hidden text-muted-foreground md:table-cell">
                          {sprint.org_name}
                        </TableCell>
                        <TableCell>
                          <span
                            className={cn(
                              "inline-flex whitespace-nowrap rounded-full border px-2 py-0.5 text-xs font-medium",
                              statusBadgeClass(sprint.status),
                            )}
                          >
                            {formatStatus(sprint.status)}
                          </span>
                        </TableCell>
                        <TableCell className="hidden text-muted-foreground xl:table-cell">
                          {sprint.vertical}
                        </TableCell>
                        <TableCell className="hidden whitespace-nowrap text-muted-foreground xl:table-cell">
                          {sprint.start_date}
                        </TableCell>
                        <TableCell className="hidden whitespace-nowrap tabular-nums text-muted-foreground lg:table-cell">
                          {sprint.latest_iso_week != null
                            ? `W${sprint.latest_iso_week}/${sprint.latest_iso_year}`
                            : "—"}
                        </TableCell>
                        <TableCell className="hidden sm:table-cell">
                          {sprint.active_drift_alerts > 0 ? (
                            <span className="inline-flex items-center gap-1 rounded-full border border-destructive/30 bg-destructive/10 px-2 py-0.5 text-xs font-medium tabular-nums text-destructive">
                              <AlertTriangle className="h-3 w-3" />
                              {sprint.active_drift_alerts}
                            </span>
                          ) : (
                            <span className="tabular-nums text-muted-foreground">0</span>
                          )}
                        </TableCell>
                        <TableCell className="hidden pr-5 lg:table-cell">
                          {sprint.data_gap_teams.length > 0 ? (
                            <span
                              className="inline-flex whitespace-nowrap rounded-full border border-amber-500/30 bg-amber-500/15 px-2 py-0.5 text-xs font-medium text-amber-600"
                              title={sprint.data_gap_teams.join(", ")}
                            >
                              {sprint.data_gap_teams.length} team
                              {sprint.data_gap_teams.length !== 1 ? "s" : ""}
                            </span>
                          ) : (
                            <span className="text-muted-foreground">—</span>
                          )}
                        </TableCell>
                      </TableRow>
                    ))}
                </Fragment>
              );
            })}
          </TableBody>
        </Table>

        {totalPages > 1 && (
          <TablePagination
            currentPage={currentPage}
            totalPages={totalPages}
            onPageChange={setPage}
          />
        )}
      </Card>
    </div>
  );
}
