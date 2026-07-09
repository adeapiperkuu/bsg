import { Card, SectionHeader } from "@/components/bsg/widgets";
import type { SopAmbiguityFlag } from "@/lib/api";

export function SopAmbiguityCard({ flags }: { flags: SopAmbiguityFlag[] }) {
  if (flags.length === 0) return null;

  return (
    <Card id="sop-ambiguity">
      <SectionHeader title="SOP Ambiguity Flags" sub="UC-04 distributed IAA drop" />
      <ul className="space-y-2 text-xs">
        {flags.map((f, i) => (
          <li key={f.alert_id ?? i} className="rounded border border-border bg-elevated p-3">
            <div className="font-medium">
              {f.sop_version ? `SOP v${f.sop_version}` : "SOP ambiguity"} ·{" "}
              {f.affected_reviewer_count} pairs
            </div>
            <div className="mt-1 text-muted-foreground">{f.detail}</div>
            {f.draft_amendment && <p className="mt-2 text-foreground/90">{f.draft_amendment}</p>}
          </li>
        ))}
      </ul>
    </Card>
  );
}
