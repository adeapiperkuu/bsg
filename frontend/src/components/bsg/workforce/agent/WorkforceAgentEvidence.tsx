import { useState } from "react";
import { cn } from "@/lib/utils";
import type { AgentQueryEvidenceLinkRead } from "@/types/workforce";
import {
  DEFAULT_EVIDENCE_PREVIEW_COUNT,
  normalizeEvidenceLinks,
  type DisplayEvidenceItem,
} from "./evidence-utils";

function WorkforceEvidenceCard({ item }: { item: DisplayEvidenceItem }) {
  const title = item.description || item.sourceLabel;

  return (
    <span
      className="inline-flex max-w-full flex-col rounded-md border border-border/70 bg-secondary/50 px-2 py-1.5 text-left text-[10px] text-foreground"
      title={item.description || item.sourceLabel}
    >
      <span className="line-clamp-2 font-medium">{title}</span>
      {item.description ? <span className="text-muted-foreground">{item.sourceLabel}</span> : null}
    </span>
  );
}

type WorkforceAgentEvidenceProps = {
  evidenceLinks: AgentQueryEvidenceLinkRead[];
  previewCount?: number;
};

export function WorkforceAgentEvidence({
  evidenceLinks,
  previewCount = DEFAULT_EVIDENCE_PREVIEW_COUNT,
}: WorkforceAgentEvidenceProps) {
  const [expanded, setExpanded] = useState(false);
  const [showTechnical, setShowTechnical] = useState(false);
  const items = normalizeEvidenceLinks(evidenceLinks);

  if (items.length === 0) return null;

  const hiddenCount = Math.max(items.length - previewCount, 0);
  const visibleItems = expanded ? items : items.slice(0, previewCount);
  const technicalItems = items.filter((item) => item.rowIdShort);

  return (
    <div className="mt-3 border-t border-border/50 pt-2.5">
      <div className="mb-1.5 flex flex-wrap items-baseline justify-between gap-2">
        <div className="text-[10px] font-semibold uppercase tracking-wider text-muted-foreground">
          Why this answer?
        </div>
        <span className="text-[10px] text-muted-foreground/70">Top signals</span>
      </div>
      <div className="flex flex-wrap gap-1.5" data-testid="workforce-evidence-list">
        {visibleItems.map((item) => (
          <WorkforceEvidenceCard key={item.id} item={item} />
        ))}
      </div>
      {hiddenCount > 0 && (
        <button
          type="button"
          onClick={() => setExpanded((current) => !current)}
          className={cn("mt-2 text-[10px] font-medium text-[color:var(--brand)] hover:underline")}
        >
          {expanded ? "Show less" : `Show all evidence (${items.length})`}
        </button>
      )}
      {technicalItems.length > 0 && (
        <div className="mt-2">
          <button
            type="button"
            onClick={() => setShowTechnical((current) => !current)}
            className="text-[10px] text-muted-foreground hover:text-foreground"
          >
            Technical details
          </button>
          {showTechnical ? (
            <ul className="mt-1.5 space-y-1 text-[9px] text-muted-foreground/75">
              {technicalItems.map((item) => (
                <li key={`tech-${item.id}`} className="font-mono">
                  {item.sourceLabel}
                  {item.description ? ` · ${item.description}` : ""} · Ref {item.rowIdShort}
                </li>
              ))}
            </ul>
          ) : null}
        </div>
      )}
    </div>
  );
}
