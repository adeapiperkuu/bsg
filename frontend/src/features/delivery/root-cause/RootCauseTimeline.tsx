import type { RootCauseSnapshotRead } from "@/lib/api";

type Props = {
  history: RootCauseSnapshotRead[];
  loading?: boolean;
};

export function RootCauseTimeline({ history, loading = false }: Props) {
  if (loading) {
    return <div className="h-20 animate-pulse rounded bg-elevated" />;
  }
  if (history.length === 0) {
    return (
      <p className="text-sm text-muted-foreground">
        Timeline populates as daily root-cause snapshots accumulate.
      </p>
    );
  }
  return (
    <ol className="space-y-2 border-l border-border pl-3">
      {history.slice(0, 8).map((snapshot) => {
        const top = snapshot.main_contributors[0];
        return (
          <li key={snapshot.id} className="relative text-xs">
            <span className="absolute -left-[17px] top-1 h-2 w-2 rounded-full bg-[color:var(--brand)]" />
            <p className="font-medium text-foreground">{snapshot.snapshot_date}</p>
            <p className="text-muted-foreground">
              Confidence {Math.round(snapshot.overall_confidence)}% · loss{" "}
              {Math.round(snapshot.confidence_loss)} pts
              {top ? ` · led by ${top.label}` : ""}
            </p>
          </li>
        );
      })}
    </ol>
  );
}
