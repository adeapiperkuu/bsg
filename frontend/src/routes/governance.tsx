import { createFileRoute } from "@tanstack/react-router";

import { GovernanceDashboard } from "@/features/governance/GovernanceDashboard";

export const Route = createFileRoute("/governance")({ component: GovernancePage });

function GovernancePage() {
  return <GovernanceDashboard />;
}
