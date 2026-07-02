import { Card, SectionHeader } from "@/components/bsg/widgets";
import { Skeleton } from "@/components/ui/skeleton";

export function QualityPageSkeleton() {
  return (
    <div className="space-y-5" aria-label="Loading quality dashboard">
      <div className="grid grid-cols-2 gap-4 lg:grid-cols-4">
        {Array.from({ length: 4 }).map((_, i) => (
          <Card key={i}>
            <Skeleton className="h-3 w-24" />
            <Skeleton className="mt-3 h-8 w-16" />
          </Card>
        ))}
      </div>

      <Card>
        <SectionHeader title="Quality Trend" sub="Gold accuracy & IAA · up to 6 weeks" />
        <Skeleton className="h-[260px] w-full rounded-md" />
      </Card>

      <div className="grid grid-cols-1 gap-5 lg:grid-cols-2">
        <Card>
          <SectionHeader title="Error Category Breakdown" sub="Current week share %" />
          <Skeleton className="h-[240px] w-full rounded-md" />
        </Card>
        <Card>
          <SectionHeader title="Drift Alerts" sub="Linked AI actions" />
          <div className="space-y-2">
            {Array.from({ length: 3 }).map((_, i) => (
              <Skeleton key={i} className="h-16 w-full rounded-md" />
            ))}
          </div>
        </Card>
      </div>

      <Card>
        <SectionHeader title="Team Quality Scorecard" />
        <div className="space-y-2">
          {Array.from({ length: 4 }).map((_, i) => (
            <Skeleton key={i} className="h-10 w-full rounded-md" />
          ))}
        </div>
      </Card>
    </div>
  );
}
