import { useState, type ReactNode } from "react";
import { ChevronDown } from "lucide-react";

import { Collapsible, CollapsibleContent, CollapsibleTrigger } from "@/components/ui/collapsible";
import { cn } from "@/lib/utils";

/**
 * Compact fold for Workforce page sections — keeps the page scannable while
 * still exposing full detail on demand.
 */
export function WorkforceFold({
  title,
  sub,
  summary,
  badge,
  defaultOpen = false,
  plain = false,
  right,
  children,
}: {
  title: string;
  sub?: string;
  /** Shown when collapsed so the section still communicates status. */
  summary?: string;
  badge?: string;
  defaultOpen?: boolean;
  /** Drop outer card chrome when nested inside another panel. */
  plain?: boolean;
  right?: ReactNode;
  children: ReactNode;
}) {
  const [open, setOpen] = useState(defaultOpen);

  return (
    <Collapsible open={open} onOpenChange={setOpen}>
      <div
        className={cn(
          plain ? "rounded-md border border-border/70 bg-elevated/20" : "rounded-lg border border-border bg-card",
        )}
      >
        <div className={cn("flex items-start gap-2", plain ? "px-3 py-2.5" : "p-4")}>
          <CollapsibleTrigger
            className="flex min-w-0 flex-1 items-start gap-2 text-left outline-none"
            aria-expanded={open}
          >
            <ChevronDown
              className={cn(
                "mt-0.5 h-4 w-4 shrink-0 text-muted-foreground transition-transform duration-200",
                open && "rotate-180",
              )}
            />
            <div className="min-w-0 flex-1">
              <div className="flex flex-wrap items-center gap-2">
                <h3 className="text-sm font-semibold tracking-tight text-foreground">{title}</h3>
                {badge ? (
                  <span className="rounded-md border border-border bg-elevated px-1.5 py-0.5 text-[10px] font-medium text-muted-foreground">
                    {badge}
                  </span>
                ) : null}
              </div>
              {open && sub ? (
                <p className="mt-0.5 text-xs text-muted-foreground">{sub}</p>
              ) : null}
              {!open && summary ? (
                <p className="mt-0.5 text-xs text-muted-foreground">{summary}</p>
              ) : null}
            </div>
          </CollapsibleTrigger>
          {right ? <div className="shrink-0 pt-0.5">{right}</div> : null}
        </div>
        <CollapsibleContent>
          <div className={cn("border-t border-border", plain ? "px-3 pb-3 pt-2.5" : "px-4 pb-4 pt-3")}>
            {children}
          </div>
        </CollapsibleContent>
      </div>
    </Collapsible>
  );
}
