import { createFileRoute } from "@tanstack/react-router";
import { lazy, Suspense } from "react";

import { GovernancePageShell } from "@/features/governance/GovernancePageShell";

const GovernanceDashboard = lazy(() =>
  import("@/features/governance/GovernanceDashboard").then((module) => ({
    default: module.GovernanceDashboard,
  })),
);

export const Route = createFileRoute("/governance")({ component: GovernancePage });

function GovernancePage() {
  return (
    <Suspense fallback={<GovernancePageShell />}>
      <GovernanceDashboard />
    </Suspense>
  );
}
