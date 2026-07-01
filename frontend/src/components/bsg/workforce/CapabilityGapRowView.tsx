import {
  capabilityGapSeverityClass,
  capabilityGapSeverityLabel,
  capabilityGapStatusClass,
  capabilityGapStatusLabel,
  capabilityGapTypeLabel,
  formatDetectedAt,
} from "@/lib/workforceLabels";
import { cn } from "@/lib/utils";
import type { CapabilityGapRead, CapabilityGapStatus } from "@/types/workforce";

export function CapabilityGapRowView({
  gap,
  canManage,
  isUpdating,
  onStatusUpdate,
}: {
  gap: CapabilityGapRead;
  canManage: boolean;
  isUpdating: boolean;
  onStatusUpdate: (gapId: string, status: CapabilityGapStatus) => void;
}) {
  const isActive = gap.status === "open" || gap.status === "acknowledged";

  return (
    <tr className="border-b border-border/50">
      <td className="py-2.5 pr-3">
        <div className="font-medium">{gap.title}</div>
        <div className="mt-0.5 text-[11px] text-muted-foreground line-clamp-2">{gap.detail}</div>
      </td>
      <td className="py-2.5 pr-3 text-muted-foreground">{capabilityGapTypeLabel(gap.gap_type)}</td>
      <td className="py-2.5 pr-3">
        <span
          className={cn(
            "inline-flex items-center rounded-full border px-2 py-0.5 text-[10px] font-medium",
            capabilityGapSeverityClass(gap.severity),
          )}
        >
          {capabilityGapSeverityLabel(gap.severity)}
        </span>
      </td>
      <td className="py-2.5 pr-3">
        <span
          className={cn(
            "inline-flex items-center rounded-full border px-2 py-0.5 text-[10px] font-medium",
            capabilityGapStatusClass(gap.status),
          )}
        >
          {capabilityGapStatusLabel(gap.status)}
        </span>
      </td>
      <td className="py-2.5 pr-3 text-muted-foreground whitespace-nowrap">
        {formatDetectedAt(gap.detected_at)}
      </td>
      {canManage && (
        <td className="py-2.5 pr-3">
          {isActive && !isUpdating ? (
            <div className="flex flex-wrap gap-1">
              {gap.status === "open" && (
                <button
                  type="button"
                  onClick={() => onStatusUpdate(gap.id, "acknowledged")}
                  className="rounded border border-border bg-elevated px-1.5 py-0.5 text-[10px] hover:bg-card"
                >
                  Acknowledge
                </button>
              )}
              <button
                type="button"
                onClick={() => onStatusUpdate(gap.id, "resolved")}
                className="rounded border border-[color:var(--success)]/30 bg-[color:var(--success)]/10 px-1.5 py-0.5 text-[10px] text-[color:var(--success)] hover:bg-[color:var(--success)]/20"
              >
                Resolve
              </button>
              <button
                type="button"
                onClick={() => onStatusUpdate(gap.id, "dismissed")}
                className="rounded border border-border bg-elevated px-1.5 py-0.5 text-[10px] text-muted-foreground hover:bg-card"
              >
                Dismiss
              </button>
            </div>
          ) : isUpdating ? (
            <span className="text-[10px] text-muted-foreground">Updating...</span>
          ) : null}
        </td>
      )}
    </tr>
  );
}
