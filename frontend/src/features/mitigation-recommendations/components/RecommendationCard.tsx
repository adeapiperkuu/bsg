import { AiBadge, StatusPill } from "@/components/bsg/widgets";
import type {
  MitigationRecommendation,
  OwnerOption,
} from "@/features/mitigation-recommendations/types";
import { SEVERITY_LABELS } from "@/features/mitigation-recommendations/types";
import { cn } from "@/lib/utils";

type RecommendationCardProps = {
  recommendation: MitigationRecommendation;
  assignableOwners: OwnerOption[];
  onAccept: (id: string) => void;
  onReject: (id: string) => void;
  onAssignOwner: (id: string, ownerType: string | null, ownerId: string | null) => void;
  isAccepting?: boolean;
  isRejecting?: boolean;
  isAssigning?: boolean;
};

function confidencePercent(score: number | string): number {
  const value = typeof score === "string" ? parseFloat(score) : score;
  return Math.round(value * 100);
}

export function RecommendationCard({
  recommendation,
  assignableOwners,
  onAccept,
  onReject,
  onAssignOwner,
  isAccepting = false,
  isRejecting = false,
  isAssigning = false,
}: RecommendationCardProps) {
  const isPending = recommendation.status === "pending";
  const isAccepted = recommendation.status === "accepted";
  const isRejected = recommendation.status === "rejected";
  const ownerValue =
    recommendation.owner_type && recommendation.owner_id
      ? `${recommendation.owner_type}:${recommendation.owner_id}`
      : "";

  const handleOwnerChange = (value: string) => {
    if (!value) {
      onAssignOwner(recommendation.id, null, null);
      return;
    }
    const [ownerType, ownerId] = value.split(":");
    onAssignOwner(recommendation.id, ownerType, ownerId);
  };

  return (
    <div
      className={cn(
        "rounded-md border p-3 transition-colors",
        isAccepted && "border-[color:var(--success)]/40 bg-[color:var(--success)]/5",
        isRejected && "border-border bg-elevated/50 opacity-60",
        isPending && "border-border bg-elevated",
      )}
    >
      <div className="flex flex-wrap items-center gap-2">
        <StatusPill status={SEVERITY_LABELS[recommendation.severity]} />
        <AiBadge confidence={confidencePercent(recommendation.confidence_score)} />
        {isAccepted && (
          <span className="rounded-full border border-[color:var(--success)]/30 bg-[color:var(--success)]/10 px-2 py-0.5 text-[10px] font-medium text-[color:var(--success)]">
            Accepted
          </span>
        )}
        {isRejected && (
          <span className="rounded-full border border-border bg-secondary px-2 py-0.5 text-[10px] font-medium text-muted-foreground">
            Rejected
          </span>
        )}
      </div>

      <div className={cn("mt-1.5 text-sm font-medium", isRejected && "text-muted-foreground")}>
        {recommendation.title}
      </div>
      {recommendation.description && (
        <p className="mt-1 text-xs text-muted-foreground">{recommendation.description}</p>
      )}
      {recommendation.source_risk_title && (
        <p className="mt-1.5 text-[10px] text-muted-foreground">
          Linked risk: {recommendation.source_risk_title}
        </p>
      )}

      <div className="mt-2 flex flex-wrap items-center justify-between gap-2">
        <select
          className="min-w-[160px] rounded border border-border bg-card px-2 py-1 text-[11px] disabled:cursor-not-allowed disabled:opacity-50"
          value={ownerValue}
          disabled={isRejected || isAssigning}
          onChange={(event) => handleOwnerChange(event.target.value)}
        >
          <option value="">
            Owner: {recommendation.owner_label ?? "Unassigned"}
          </option>
          {assignableOwners.map((owner) => (
            <option
              key={`${owner.owner_type}:${owner.owner_id}`}
              value={`${owner.owner_type}:${owner.owner_id}`}
            >
              {owner.owner_type === "team" ? "Team" : "User"}: {owner.label}
            </option>
          ))}
        </select>

        {isPending && (
          <div className="flex gap-1.5">
            <button
              type="button"
              disabled={isAccepting || isRejecting}
              onClick={() => onAccept(recommendation.id)}
              className="rounded bg-[color:var(--brand)] px-2.5 py-1 text-[11px] font-medium text-[color:var(--brand-foreground)] disabled:opacity-50"
            >
              Accept
            </button>
            <button
              type="button"
              disabled={isAccepting || isRejecting}
              onClick={() => onReject(recommendation.id)}
              className="rounded border border-border px-2.5 py-1 text-[11px] disabled:opacity-50"
            >
              Reject
            </button>
          </div>
        )}
      </div>
    </div>
  );
}
