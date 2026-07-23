import { createFileRoute } from "@tanstack/react-router";

import {
  ClientProjectWorkspace,
  type ClientWorkspaceView,
} from "@/features/client-dashboard/ClientProjectWorkspace";

const VIEWS = new Set<ClientWorkspaceView>([
  "overview",
  "progress",
  "risks",
  "actions",
  "summary",
  "documents",
  "deliverables",
  "changes",
  "meetings",
  "notifications",
]);

type ClientStatusSearch = {
  view?: ClientWorkspaceView;
};

export const Route = createFileRoute("/client/status")({
  validateSearch: (search: Record<string, unknown>): ClientStatusSearch =>
    typeof search.view === "string" && VIEWS.has(search.view as ClientWorkspaceView)
      ? { view: search.view as ClientWorkspaceView }
      : {},
  component: ClientStatus,
});

function ClientStatus() {
  const { view } = Route.useSearch();
  const navigate = Route.useNavigate();
  return (
    <ClientProjectWorkspace
      activeView={view ?? "overview"}
      onViewChange={(nextView) => void navigate({ search: { view: nextView } })}
    />
  );
}
