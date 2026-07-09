import { AiBadge, Card, EvidenceBadge, SectionHeader } from "@/components/bsg/widgets";

export function QualityNarrativeCard({ narrative }: { narrative: string }) {
  return (
    <Card>
      <SectionHeader
        title="AI Quality Narrative"
        sub="Client-safe summary"
        right={
          <div className="flex gap-2">
            <AiBadge confidence={90} />
            <EvidenceBadge />
          </div>
        }
      />
      <p className="text-sm leading-6 text-foreground/90">{narrative}</p>
    </Card>
  );
}
