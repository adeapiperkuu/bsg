import { Card, SectionHeader } from "@/components/bsg/widgets";
import { TimeSeriesState } from "@/components/bsg/time-series/TimeSeriesState";
import type { RecommendationTimelineEvent } from "@/types/time-series";

export function RecommendationTimeline({
  title = "Recommendation Timeline",
  events,
  loading,
  error,
  emptyMessage = "No recommendation timeline events.",
}: {
  title?: string;
  events: RecommendationTimelineEvent[];
  loading?: boolean;
  error?: unknown;
  emptyMessage?: string;
}) {
  return (
    <Card>
      <SectionHeader title={title} sub={`${events.length} events`} />
      <TimeSeriesState
        loading={loading}
        error={error}
        empty={!loading && !error && events.length === 0}
        emptyMessage={emptyMessage}
      >
        <ol className="space-y-3" aria-label="Recommendation timeline">
          {events.map((event) => (
            <li
              key={event.id}
              className="rounded-lg border border-[color:var(--border)] bg-[color:var(--panel-2)] px-3 py-2"
            >
              <div className="flex flex-wrap items-center justify-between gap-2">
                <span className="text-sm font-medium capitalize">
                  {event.event_type.replaceAll("_", " ")}
                </span>
                <time className="text-[11px] text-muted-foreground" dateTime={event.event_timestamp}>
                  {new Date(event.event_timestamp).toLocaleString()}
                </time>
              </div>
              <div className="mt-1 text-xs text-muted-foreground">
                {[event.source_agent, event.recommendation_type, event.severity, event.status_snapshot]
                  .filter(Boolean)
                  .join(" · ")}
              </div>
            </li>
          ))}
        </ol>
      </TimeSeriesState>
    </Card>
  );
}
