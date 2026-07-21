import { createFileRoute } from "@tanstack/react-router";

import { ClientIntelligenceDashboard } from "@/features/client-intelligence/ClientIntelligenceDashboard";

export const Route = createFileRoute("/client-intelligence")({
  component: ClientIntelligenceDashboard,
});
