import { createFileRoute } from "@tanstack/react-router";

import { GovernanceDashboard } from "@/features/governance/GovernanceDashboard";

export const Route = createFileRoute("/governance")({
  validateSearch: (search: Record<string, unknown>) => ({
    days:
      typeof search.days === "number"
        ? search.days
        : typeof search.days === "string" && [7, 30, 90, 365].includes(Number(search.days))
          ? Number(search.days)
          : undefined,
    projectId: typeof search.projectId === "string" ? search.projectId : undefined,
    vertical: typeof search.vertical === "string" ? search.vertical : undefined,
    triggerType: typeof search.triggerType === "string" ? search.triggerType : undefined,
  }),
  component: GovernancePage,
});

function GovernancePage() {
  return <GovernanceDashboard />;
}
