import { WorkforceAgentChat } from "./WorkforceAgentChat";

type PlaceholderPanelProps = {
  title: string;
  reason: string;
};

function PlaceholderPanel({ title, reason }: PlaceholderPanelProps) {
  return (
    <div className="rounded-md border border-dashed border-border bg-elevated/50 px-4 py-8 text-center">
      <p className="text-sm font-medium text-muted-foreground">{title}</p>
      <p className="mt-1 text-xs text-muted-foreground">{reason}</p>
    </div>
  );
}

type WorkforceAgentSectionProps = {
  projectId: string | null;
  canReadInternalWorkforce: boolean;
  onAskingChange?: (asking: boolean) => void;
};

export function WorkforceAgentSection({
  projectId,
  canReadInternalWorkforce,
  onAskingChange,
}: WorkforceAgentSectionProps) {
  if (!canReadInternalWorkforce) {
    return (
      <div className="rounded-lg border border-border bg-card p-5">
        <PlaceholderPanel
          title="Workforce Agent restricted"
          reason="The Workforce Agent is available to internal roles only."
        />
      </div>
    );
  }

  return <WorkforceAgentChat projectId={projectId} onAskingChange={onAskingChange} />;
}
