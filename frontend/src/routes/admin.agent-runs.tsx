import { createFileRoute } from "@tanstack/react-router";
import { Fragment, useEffect, useState } from "react";
import { ChevronDown, ChevronRight, Clock, Play, RefreshCw, User } from "lucide-react";

import { Card } from "@/components/bsg/widgets";
import { Button } from "@/components/ui/button";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { listQualityScanRuns, triggerQualityScan, type QualityScanRun } from "@/lib/api";
import { cn } from "@/lib/utils";

export const Route = createFileRoute("/admin/agent-runs")({ component: AdminAgentRunsPage });

function formatDuration(started: string, finished: string | null): string {
  if (!finished) return "—";
  const ms = new Date(finished).getTime() - new Date(started).getTime();
  if (ms < 1000) return `${ms}ms`;
  return `${(ms / 1000).toFixed(1)}s`;
}

function statusClass(status: QualityScanRun["status"]): string {
  if (status === "completed") return "bg-[color:var(--success)]/15 text-[color:var(--success)]";
  if (status === "failed") return "bg-destructive/15 text-destructive";
  return "bg-amber-500/15 text-amber-600";
}

function AdminAgentRunsPage() {
  const [runs, setRuns] = useState<QualityScanRun[]>([]);
  const [loading, setLoading] = useState(false);
  const [scanning, setScanning] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [expandedId, setExpandedId] = useState<string | null>(null);

  const load = async () => {
    setLoading(true);
    setError(null);
    try {
      setRuns(await listQualityScanRuns());
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load scan runs.");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    void load();
  }, []);

  const onRunScan = async () => {
    setScanning(true);
    setError(null);
    try {
      await triggerQualityScan();
      await load();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to trigger quality scan.");
    } finally {
      setScanning(false);
    }
  };

  return (
    <div className="space-y-5">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <p className="text-sm text-muted-foreground">
          History of automated and manual Quality Intelligence scan runs.
        </p>
        <div className="flex gap-2">
          <Button variant="outline" size="sm" onClick={() => void load()} disabled={loading || scanning}>
            <RefreshCw className={cn("h-4 w-4", loading && "animate-spin")} />
            Refresh
          </Button>
          <Button size="sm" onClick={() => void onRunScan()} disabled={scanning}>
            <Play className="h-4 w-4" />
            {scanning ? "Running…" : "Run Scan Now"}
          </Button>
        </div>
      </div>

      {error && (
        <div className="rounded-md border border-destructive/30 bg-destructive/10 px-3 py-2 text-sm text-destructive">
          {error}
        </div>
      )}

      <Card className="overflow-hidden p-0">
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead className="w-8" />
              <TableHead>Trigger</TableHead>
              <TableHead>Week</TableHead>
              <TableHead>Status</TableHead>
              <TableHead>Started</TableHead>
              <TableHead>Duration</TableHead>
              <TableHead>Projects</TableHead>
              <TableHead>Snapshots</TableHead>
              <TableHead>Alerts</TableHead>
              <TableHead>Data gaps</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {loading && runs.length === 0 && (
              <TableRow>
                <TableCell colSpan={10} className="text-center text-muted-foreground">
                  Loading scan runs…
                </TableCell>
              </TableRow>
            )}
            {!loading && runs.length === 0 && (
              <TableRow>
                <TableCell colSpan={10} className="text-center text-muted-foreground">
                  No scan runs yet. Trigger one manually or wait for the Monday 02:00 job.
                </TableCell>
              </TableRow>
            )}
            {runs.map((run) => {
              const expanded = expandedId === run.id;
              const hasDetail = (run.per_project_results?.length ?? 0) > 0 || run.error_message;
              return (
                <Fragment key={run.id}>
                  <TableRow>
                    <TableCell>
                      {hasDetail ? (
                        <button
                          type="button"
                          className="grid h-6 w-6 place-items-center rounded hover:bg-elevated"
                          onClick={() => setExpandedId(expanded ? null : run.id)}
                          aria-label={expanded ? "Collapse" : "Expand"}
                        >
                          {expanded ? <ChevronDown className="h-4 w-4" /> : <ChevronRight className="h-4 w-4" />}
                        </button>
                      ) : null}
                    </TableCell>
                    <TableCell>
                      <span className="inline-flex items-center gap-1.5 text-xs">
                        {run.trigger === "scheduler" ? (
                          <Clock className="h-3.5 w-3.5 text-muted-foreground" />
                        ) : (
                          <User className="h-3.5 w-3.5 text-muted-foreground" />
                        )}
                        {run.trigger === "scheduler" ? "Scheduled" : "Manual"}
                      </span>
                    </TableCell>
                    <TableCell>
                      W{run.iso_week}/{run.iso_year}
                    </TableCell>
                    <TableCell>
                      <span className={cn("rounded-full px-2 py-0.5 text-xs font-medium capitalize", statusClass(run.status))}>
                        {run.status}
                      </span>
                    </TableCell>
                    <TableCell className="text-xs text-muted-foreground">
                      {new Date(run.started_at).toLocaleString()}
                    </TableCell>
                    <TableCell className="text-xs">{formatDuration(run.started_at, run.finished_at)}</TableCell>
                    <TableCell>{run.projects_scanned}</TableCell>
                    <TableCell>{run.snapshots_evaluated}</TableCell>
                    <TableCell>{run.alerts_created}</TableCell>
                    <TableCell>{run.data_gaps}</TableCell>
                  </TableRow>
                  {expanded && (
                    <TableRow key={`${run.id}-detail`}>
                      <TableCell colSpan={10} className="bg-elevated/50 p-4">
                        {run.error_message && (
                          <p className="mb-3 text-sm text-destructive">Error: {run.error_message}</p>
                        )}
                        {run.per_project_results && run.per_project_results.length > 0 ? (
                          <div className="overflow-x-auto">
                            <table className="w-full text-xs">
                              <thead className="text-left text-muted-foreground">
                                <tr className="border-b border-border">
                                  <th className="py-1.5 pr-3">Project</th>
                                  <th className="py-1.5 pr-3">Snapshots</th>
                                  <th className="py-1.5 pr-3">Alerts</th>
                                  <th className="py-1.5 pr-3">Data gaps</th>
                                  <th className="py-1.5">Teams evaluated</th>
                                </tr>
                              </thead>
                              <tbody>
                                {run.per_project_results.map((row) => (
                                  <tr key={row.project_id} className="border-b border-border/50">
                                    <td className="py-2 pr-3 font-medium">{row.name}</td>
                                    <td className="py-2 pr-3">{row.snapshots}</td>
                                    <td className="py-2 pr-3">{row.alerts}</td>
                                    <td className="py-2 pr-3">{row.data_gaps}</td>
                                    <td className="py-2">
                                      {row.teams.length === 0 ? (
                                        <span className="text-muted-foreground">No snapshots this week</span>
                                      ) : (
                                        <ul className="space-y-0.5">
                                          {row.teams.map((t) => (
                                            <li key={t.team_id} className="text-muted-foreground">
                                              {t.data_gap && "⚠ "}
                                              {t.has_drift && "🔴 "}
                                              {t.detail ?? (t.data_gap ? "Data gap" : t.has_drift ? "Drift" : "OK")}
                                            </li>
                                          ))}
                                        </ul>
                                      )}
                                    </td>
                                  </tr>
                                ))}
                              </tbody>
                            </table>
                          </div>
                        ) : (
                          <p className="text-xs text-muted-foreground">No per-project detail recorded.</p>
                        )}
                      </TableCell>
                    </TableRow>
                  )}
                </Fragment>
              );
            })}
          </TableBody>
        </Table>
      </Card>
    </div>
  );
}
