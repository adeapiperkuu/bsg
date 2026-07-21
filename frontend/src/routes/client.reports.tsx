/**
 * Client published archive (`/client/reports`).
 * Shows sent communications only; read-only. Not the PM workflow at `/reports`.
 */
import { createFileRoute } from "@tanstack/react-router";

import { ClientReportsPage } from "@/features/client-reports/ClientReportsPage";

export const Route = createFileRoute("/client/reports")({
  component: ClientReportsPage,
});
