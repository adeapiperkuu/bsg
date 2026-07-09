import { Card, SectionHeader } from "@/components/bsg/widgets";
import { Skeleton } from "@/components/ui/skeleton";

export function GovernancePageShell() {
  return (
    <div className="governance-no-shadow space-y-5" aria-busy="true" aria-label="Loading governance">
      <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-4">
        {["actions", "escalations", "deps", "sla"].map((item) => (
          <Card key={item}>
            <Skeleton className="h-3 w-24" />
            <Skeleton className="mt-4 h-7 w-12" />
          </Card>
        ))}
      </div>
      <Card>
        <SectionHeader title="Dependency Tracker" sub="Loading governance tables" />
        <Skeleton className="h-[258px] w-full" />
      </Card>
    </div>
  );
}
