/**
 * PM `/reports` route — thin file-route shell.
 *
 * This is the internal PM workflow console (all communication statuses + lifecycle).
 * It is NOT `/client/reports` (client published archive, sent-only, read-only).
 * Navigation: Shell → Reporting → Reports → `/reports` (internal nav only).
 */

import { createFileRoute } from "@tanstack/react-router";
import { ReportsPage } from "@/features/reports/ReportsPage";
import { parseInboxFilter } from "@/features/reports/report-status";

export const Route = createFileRoute("/reports")({
  validateSearch: (search: Record<string, unknown>) => ({
    status: parseInboxFilter(search.status) === "all" ? undefined : parseInboxFilter(search.status),
  }),
  component: ReportsPage,
});
