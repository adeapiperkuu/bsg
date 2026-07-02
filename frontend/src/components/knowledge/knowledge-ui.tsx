import type { ReactNode } from "react";

import { StatusPill } from "@/components/bsg/widgets";
import { cn } from "@/lib/utils";

export function InfoTile({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-md border border-border/70 bg-card/60 p-3">
      <div className="text-[10px] font-medium uppercase tracking-wider text-muted-foreground">{label}</div>
      <div className="mt-1 font-medium text-foreground">{value}</div>
    </div>
  );
}

export function MetaRow({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex items-start justify-between gap-3">
      <dt>{label}</dt>
      <dd className="max-w-[10rem] text-right font-medium text-foreground">{value}</dd>
    </div>
  );
}

export function DocBadge({ label, tone }: { label: string; tone?: "success" | "info" | "danger" }) {
  if (label === "Approved" || label === "Draft" || label === "Archived") return <StatusPill status={label} />;
  const classes =
    tone === "success"
      ? "border-[color:var(--success)]/30 bg-[color:var(--success)]/15 text-[color:var(--success)]"
      : tone === "danger"
        ? "border-[color:var(--danger)]/30 bg-[color:var(--danger)]/10 text-[color:var(--danger)]"
        : "border-border/70 bg-secondary/70 text-muted-foreground";
  return <span className={cn("rounded border px-1.5 py-0.5 text-[9px] font-medium", classes)}>{label}</span>;
}

export function QualityScoreBadge({
  score,
  detailed = false,
}: {
  score: { score: number; max_score: number; criteria: Array<{ key: string; label: string; passed: boolean }> };
  detailed?: boolean;
}) {
  const pct = Math.round((score.score / Math.max(score.max_score, 1)) * 100);
  return (
    <div className="inline-flex flex-col gap-1">
      <span className="inline-flex items-center gap-1 rounded bg-secondary px-1.5 py-0.5 text-[9px] font-medium text-muted-foreground">
        Quality {score.score}/{score.max_score} ({pct}%)
      </span>
      {detailed && (
        <div className="flex flex-wrap gap-1">
          {score.criteria.map((item) => (
            <span
              key={item.key}
              className={cn(
                "rounded px-1.5 py-0.5 text-[9px]",
                item.passed ? "bg-[color:var(--success)]/10 text-[color:var(--success)]" : "bg-secondary text-muted-foreground",
              )}
            >
              {item.label}
            </span>
          ))}
        </div>
      )}
    </div>
  );
}

export function FormattedPreview({ text, compact = false }: { text: string; compact?: boolean }) {
  const lines = formatPreviewLines(text);
  return (
    <div className={cn("space-y-2", compact && "space-y-1.5")}>
      {lines.map((line, index) => {
        if (line.kind === "heading") {
          return (
            <h4 key={`${line.text}-${index}`} className="pt-1 text-sm font-semibold text-foreground">
              {line.text}
            </h4>
          );
        }
        if (line.kind === "bullet") {
          return (
            <div key={`${line.text}-${index}`} className="flex gap-2 pl-2 text-sm leading-6">
              <span className="mt-2 h-1.5 w-1.5 shrink-0 rounded-full bg-muted-foreground/60" />
              <span>{line.text}</span>
            </div>
          );
        }
        return (
          <p key={`${line.text}-${index}`} className="text-sm leading-6 text-foreground">
            {line.text}
          </p>
        );
      })}
    </div>
  );
}

function formatPreviewLines(text: string): Array<{ kind: "heading" | "bullet" | "paragraph"; text: string }> {
  const normalized = text
    .replace(
      /(Purpose|Scope|Procedure|Responsibilities|Requirements|Project Summary|Challenges Encountered|Actions Taken|Results|Recommendations|Best Practices|Lessons Learned|Quality Guidance)(?=[A-Z0-9-])/g,
      "\n$1\n",
    )
    .replace(/(Phase\s+\d+:\s*[^-]+)-\s*/g, "\n$1\n- ")
    .replace(/(?<![\d\n])([1-9]\d?\.\s+)/g, "\n$1")
    .replace(/(?<=[a-z0-9)%])-\s*(?=[A-Z][A-Za-z]+(?:\s|$))/g, "\n- ")
    .replace(/(?<=[.;:])\s+-\s*(?=[A-Z][A-Za-z]+(?:\s|$))/g, "\n- ");
  return normalized
    .split(/\n+/)
    .map((line) => line.trim())
    .filter(Boolean)
    .map((line) => {
      const clean = line.replace(/^-\s*/, "").trim();
      if (line.startsWith("-")) return { kind: "bullet" as const, text: clean };
      if (/^\d+[\.)]\s+/.test(line)) return { kind: "bullet" as const, text: line };
      if (/^(Purpose|Scope|Procedure|Responsibilities|Requirements|Project Summary|Challenges Encountered|Actions Taken|Results|Recommendations|Best Practices|Lessons Learned|Quality Guidance)$/i.test(line)) {
        return { kind: "heading" as const, text: line };
      }
      if (/^Phase\s+\d+:/i.test(line)) return { kind: "heading" as const, text: line };
      if (/^[A-Z][A-Za-z0-9:() /-]{2,}$/.test(line) && line.length <= 90 && !/[.!?]$/.test(line)) {
        return { kind: "heading" as const, text: line };
      }
      return { kind: "paragraph" as const, text: line };
    });
}

export function Field({ label, children, className }: { label: string; children: ReactNode; className?: string }) {
  return (
    <label className={cn("space-y-1.5 text-xs", className)}>
      <span className="font-medium text-muted-foreground">{label}</span>
      {children}
    </label>
  );
}
