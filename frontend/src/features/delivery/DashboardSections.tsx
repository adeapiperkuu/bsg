/**
 * Phase 15.6 — Delivery dashboard sections: executive overview, team bottlenecks,
 * operational timeline, and delivery insights. All content is derived from data
 * the page already loads; no AI calls happen here.
 */
import { Card, SectionHeader, StatusPill } from "@/components/bsg/widgets";
import { cn } from "@/lib/utils";
import type {
  BottleneckRow,
  DeliveryInsight,
  TimelineEvent,
  TrafficDistribution,
} from "@/features/delivery/insights";

const TONE_TEXT: Record<string, string> = {
  danger: "text-[color:var(--danger)]",
  warning: "text-[color:var(--warning)]",
  info: "text-[color:var(--info)]",
  success: "text-[color:var(--success)]",
};

const TONE_DOT: Record<string, string> = {
  danger: "bg-[color:var(--danger)]",
  warning: "bg-[color:var(--warning)]",
  info: "bg-[color:var(--info)]",
  success: "bg-[color:var(--success)]",
};

// ---------------------------------------------------------------------------
// Executive overview — portfolio health distribution
// ---------------------------------------------------------------------------

export function PortfolioHealthBar({ distribution }: { distribution: TrafficDistribution }) {
  const { green, yellow, red, insufficient, total } = distribution;
  if (total === 0) return null;
  const pct = (count: number) => `${(count / total) * 100}%`;
  return (
    <Card>
      <SectionHeader
        title="Portfolio Health"
        sub={`${total} project${total === 1 ? "" : "s"} · traffic-light distribution`}
      />
      <div className="flex h-3 w-full overflow-hidden rounded-full bg-elevated">
        {green > 0 && (
          <div className="h-full bg-[color:var(--success)]" style={{ width: pct(green) }} />
        )}
        {yellow > 0 && (
          <div className="h-full bg-[color:var(--warning)]" style={{ width: pct(yellow) }} />
        )}
        {red > 0 && (
          <div className="h-full bg-[color:var(--danger)]" style={{ width: pct(red) }} />
        )}
        {insufficient > 0 && (
          <div className="h-full bg-muted" style={{ width: pct(insufficient) }} />
        )}
      </div>
      <div className="mt-3 flex flex-wrap gap-x-4 gap-y-1 text-xs text-muted-foreground">
        <span>
          <span className="mr-1 inline-block h-2 w-2 rounded-full bg-[color:var(--success)]" />
          On track {green}
        </span>
        <span>
          <span className="mr-1 inline-block h-2 w-2 rounded-full bg-[color:var(--warning)]" />
          Needs attention {yellow}
        </span>
        <span>
          <span className="mr-1 inline-block h-2 w-2 rounded-full bg-[color:var(--danger)]" />
          At risk {red}
        </span>
        {insufficient > 0 && (
          <span>
            <span className="mr-1 inline-block h-2 w-2 rounded-full bg-muted" />
            Insufficient data {insufficient}
          </span>
        )}
      </div>
    </Card>
  );
}

// ---------------------------------------------------------------------------
// Team bottlenecks
// ---------------------------------------------------------------------------

const SEVERITY_LABEL: Record<BottleneckRow["severity"], string> = {
  critical: "Critical",
  high: "High",
  medium: "Medium",
  low: "Low",
};

export function TeamBottlenecksPanel({
  projectName,
  bottlenecks,
  loading,
}: {
  projectName?: string;
  bottlenecks: BottleneckRow[];
  loading: boolean;
}) {
  return (
    <Card id="bottlenecks">
      <SectionHeader
        title="Team Bottlenecks"
        sub={
          projectName
            ? `Active throughput constraints for ${projectName}`
            : "Active throughput constraints"
        }
      />
      {loading ? (
        <div className="space-y-2">
          <div className="h-10 animate-pulse rounded bg-elevated" />
          <div className="h-10 animate-pulse rounded bg-elevated" />
        </div>
      ) : bottlenecks.length === 0 ? (
        <p className="text-sm text-muted-foreground">
          No open or acknowledged bottlenecks for this project.
        </p>
      ) : (
        <ul className="space-y-2.5">
          {bottlenecks.map((bottleneck) => (
            <li
              key={bottleneck.id}
              className="rounded border border-border bg-elevated/30 px-3 py-2.5"
            >
              <div className="flex flex-wrap items-center justify-between gap-2">
                <p className="text-sm font-medium text-foreground">{bottleneck.title}</p>
                <div className="flex items-center gap-2">
                  <StatusPill status={SEVERITY_LABEL[bottleneck.severity]} />
                  <span className="text-[11px] uppercase tracking-wide text-muted-foreground">
                    {bottleneck.status}
                  </span>
                </div>
              </div>
              {bottleneck.detail ? (
                <p className="mt-1 text-xs text-muted-foreground">{bottleneck.detail}</p>
              ) : null}
            </li>
          ))}
        </ul>
      )}
    </Card>
  );
}

// ---------------------------------------------------------------------------
// Operational timeline
// ---------------------------------------------------------------------------

function formatEventDate(date: Date): string {
  return date.toLocaleString(undefined, {
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
  });
}

export function OperationalTimelinePanel({
  projectName,
  events,
  loading,
}: {
  projectName?: string;
  events: TimelineEvent[];
  loading: boolean;
}) {
  return (
    <Card id="timeline">
      <SectionHeader
        title="Operational Timeline"
        sub={
          projectName
            ? `Recent risks, bottlenecks, milestones, and PM actions for ${projectName}`
            : "Recent delivery events"
        }
      />
      {loading ? (
        <div className="space-y-2">
          <div className="h-8 animate-pulse rounded bg-elevated" />
          <div className="h-8 animate-pulse rounded bg-elevated" />
          <div className="h-8 animate-pulse rounded bg-elevated" />
        </div>
      ) : events.length === 0 ? (
        <p className="text-sm text-muted-foreground">No recent delivery events recorded.</p>
      ) : (
        <ol className="relative space-y-3 border-l border-border pl-4">
          {events.map((event) => (
            <li key={event.key} className="relative">
              <span
                className={cn(
                  "absolute -left-[21px] top-1.5 h-2.5 w-2.5 rounded-full border-2 border-card",
                  TONE_DOT[event.tone] ?? "bg-muted-foreground",
                )}
              />
              <div className="flex flex-wrap items-baseline justify-between gap-2">
                <p className="text-sm text-foreground">{event.title}</p>
                <span className="shrink-0 text-[11px] tabular-nums text-muted-foreground">
                  {formatEventDate(event.date)}
                </span>
              </div>
              <p className={cn("text-xs", TONE_TEXT[event.tone] ?? "text-muted-foreground")}>
                {event.detail}
              </p>
            </li>
          ))}
        </ol>
      )}
    </Card>
  );
}

// ---------------------------------------------------------------------------
// Delivery insights
// ---------------------------------------------------------------------------

export function DeliveryInsightsPanel({
  insights,
  loading,
}: {
  insights: DeliveryInsight[];
  loading: boolean;
}) {
  return (
    <Card id="insights">
      <SectionHeader
        title="Delivery Insights"
        sub="Deterministic portfolio signals · derived from scoring and root-cause trends"
      />
      {loading ? (
        <div className="space-y-2">
          <div className="h-10 animate-pulse rounded bg-elevated" />
          <div className="h-10 animate-pulse rounded bg-elevated" />
        </div>
      ) : (
        <ul className="grid gap-2.5 md:grid-cols-2">
          {insights.map((insight) => (
            <li
              key={insight.key}
              className="rounded border border-border bg-elevated/30 px-3 py-2.5"
            >
              <div className="flex items-start gap-2">
                <span
                  className={cn(
                    "mt-1.5 h-2 w-2 shrink-0 rounded-full",
                    TONE_DOT[insight.tone] ?? "bg-muted-foreground",
                  )}
                />
                <div className="min-w-0">
                  <p className="text-sm font-medium text-foreground">{insight.label}</p>
                  <p className="mt-0.5 text-xs text-muted-foreground">{insight.detail}</p>
                </div>
              </div>
            </li>
          ))}
        </ul>
      )}
    </Card>
  );
}