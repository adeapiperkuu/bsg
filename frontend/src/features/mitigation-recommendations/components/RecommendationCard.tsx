import { AiBadge, StatusPill } from "@/components/bsg/widgets";
import type {
  GroupedMitigationRecommendation,
  GroupedRecommendationRisk,
  OwnerOption,
} from "@/features/mitigation-recommendations/types";
import { SEVERITY_LABELS } from "@/features/mitigation-recommendations/types";
import { cn } from "@/lib/utils";

type RecommendationCardProps = {
  recommendation: GroupedMitigationRecommendation;
  assignableOwners: OwnerOption[];
  onAccept: (id: string) => void;
  onReject: (id: string) => void;
  onAssignOwner: (id: string, ownerType: string | null, ownerId: string | null) => void;
  isAccepting?: (id: string) => boolean;
  isRejecting?: (id: string) => boolean;
  isAssigning?: (id: string) => boolean;
};

function confidencePercent(score: number | string): number {
  const value = typeof score === "string" ? parseFloat(score) : score;
  return Math.round(value * 100);
}

// Every recommendation description is generated as "<shared template text> Linked risk: <detail>".
// Members of a group share the same template text, so split on that fixed marker to show the
// boilerplate once at the group level and only the risk-specific detail on each row.
const LINKED_RISK_MARKER = " Linked risk: ";

function splitDescription(description: string | null): { lead: string | null; detail: string | null } {
  if (!description) return { lead: null, detail: null };
  const markerIndex = description.indexOf(LINKED_RISK_MARKER);
  if (markerIndex === -1) return { lead: description, detail: null };
  return {
    lead: description.slice(0, markerIndex).trim() || null,
    detail: description.slice(markerIndex + LINKED_RISK_MARKER.length).trim() || null,
  };
}

const STATUS_BADGE_STYLES: Record<string, string> = {
  pending: "border-border bg-secondary text-muted-foreground",
  // Neutral, not success-green: accepting only flips a status flag, it does not
  // change system behavior, so the badge shouldn't look like a resolved/success state.
  accepted: "border-border bg-secondary text-muted-foreground",
  rejected: "border-border bg-elevated text-muted-foreground",
};

const STATUS_BADGE_LABELS: Record<string, string> = {
  pending: "pending",
  accepted: "accepted",
  rejected: "rejected",
};

function RiskRow({
  risk,
  assignableOwners,
  onAccept,
  onReject,
  onAssignOwner,
  isAccepting,
  isRejecting,
  isAssigning,
}: {
  risk: GroupedRecommendationRisk;
  assignableOwners: OwnerOption[];
  onAccept: (id: string) => void;
  onReject: (id: string) => void;
  onAssignOwner: (id: string, ownerType: string | null, ownerId: string | null) => void;
  isAccepting: boolean;
  isRejecting: boolean;
  isAssigning: boolean;
}) {
  const isPending = risk.status === "pending";
  const isAccepted = risk.status === "accepted";
  const isRejected = risk.status === "rejected";
  const ownerValue = risk.owner_type && risk.owner_id ? `${risk.owner_type}:${risk.owner_id}` : "";
  const { detail, lead } = splitDescription(risk.description);
  // Fall back to the full description only when it didn't contain the expected marker,
  // so no information is silently dropped.
  const riskDetailText = detail ?? lead;

  const handleOwnerChange = (value: string) => {
    if (!value) {
      onAssignOwner(risk.recommendation_id, null, null);
      return;
    }
    const [ownerType, ownerId] = value.split(":");
    onAssignOwner(risk.recommendation_id, ownerType, ownerId);
  };

  return (
    <div
      className={cn(
        "rounded border border-border/70 p-2",
        isRejected && "bg-elevated/50 opacity-60",
      )}
    >
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div className="min-w-0">
          <p className={cn("text-[11px] font-medium", isRejected && "text-muted-foreground")}>
            {risk.source_risk_title ?? "Linked risk"}
          </p>
          {riskDetailText && (
            <p className="mt-0.5 text-[10px] text-muted-foreground">{riskDetailText}</p>
          )}
        </div>
        <div className="flex shrink-0 items-center gap-1.5">
          <AiBadge
            label="Slippage probability"
            source="formula"
            confidence={confidencePercent(risk.confidence_score)}
            estimated={risk.is_estimated}
          />
          {isAccepted && (
            <span className="rounded-full border border-border bg-secondary px-2 py-0.5 text-[10px] font-medium text-muted-foreground">
              Accepted
            </span>
          )}
          {isRejected && (
            <span
              title="This recommendation may reappear if conditions persist"
              className="rounded-full border border-border bg-secondary px-2 py-0.5 text-[10px] font-medium text-muted-foreground"
            >
              Rejected
            </span>
          )}
        </div>
      </div>

      <div className="mt-2 flex flex-wrap items-center justify-between gap-2">
        <select
          className="min-w-[150px] rounded border border-border bg-card px-2 py-1 text-[11px] disabled:cursor-not-allowed disabled:opacity-50"
          value={ownerValue}
          disabled={isRejected || isAssigning}
          onChange={(event) => handleOwnerChange(event.target.value)}
        >
          <option value="">Owner: {risk.owner_label ?? "Unassigned"}</option>
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
          <div className="flex flex-wrap items-center justify-end gap-1.5">
            <span className="text-[10px] text-muted-foreground">
              Records a decision only — no automatic action is taken.
            </span>
            <button
              type="button"
              disabled={isAccepting || isRejecting}
              onClick={() => onAccept(risk.recommendation_id)}
              className="rounded bg-[color:var(--brand)] px-2.5 py-1 text-[11px] font-medium text-[color:var(--brand-foreground)] disabled:opacity-50"
            >
              Accept
            </button>
            <button
              type="button"
              disabled={isAccepting || isRejecting}
              onClick={() => onReject(risk.recommendation_id)}
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

export function RecommendationCard({
  recommendation,
  assignableOwners,
  onAccept,
  onReject,
  onAssignOwner,
  isAccepting = () => false,
  isRejecting = () => false,
  isAssigning = () => false,
}: RecommendationCardProps) {
  const isGroup = recommendation.risks.length > 1;
  const statusCounts = recommendation.risks.reduce<Record<string, number>>((acc, risk) => {
    acc[risk.status] = (acc[risk.status] ?? 0) + 1;
    return acc;
  }, {});
  const isMixedDecision = isGroup && Object.keys(statusCounts).length > 1;
  // The shared template text is identical across every member of a group (see
  // splitDescription) — show it once instead of repeating it on every risk row.
  const { lead: sharedLead } = splitDescription(recommendation.risks[0]?.description ?? null);

  return (
    <div className="rounded-md border border-border bg-elevated p-3">
      <div className="flex flex-wrap items-center gap-2">
        <StatusPill status={SEVERITY_LABELS[recommendation.severity]} />
        <AiBadge
          label="Slippage probability"
          source="formula"
          confidence={confidencePercent(recommendation.confidence_score)}
          estimated={recommendation.is_estimated}
        />
        {isGroup && (
          <span className="rounded-full border border-border bg-secondary px-2 py-0.5 text-[10px] font-medium text-muted-foreground">
            {recommendation.risks.length} risks
          </span>
        )}
        {isGroup &&
          (["pending", "accepted", "rejected"] as const)
            .filter((status) => statusCounts[status])
            .map((status) => (
              <span
                key={status}
                className={cn(
                  "rounded-full border px-2 py-0.5 text-[10px] font-medium",
                  STATUS_BADGE_STYLES[status],
                )}
              >
                {statusCounts[status]} {STATUS_BADGE_LABELS[status]}
              </span>
            ))}
      </div>

      <div className="mt-1.5 text-sm font-medium">{recommendation.title}</div>
      {sharedLead && <p className="mt-0.5 text-xs text-muted-foreground">{sharedLead}</p>}
      {isMixedDecision && (
        <p className="mt-1 text-[10px] font-medium text-[color:var(--warning)]">
          Mixed decision across linked risks — review each row below.
        </p>
      )}

      <div className="mt-2 space-y-1.5">
        {recommendation.risks.map((risk) => (
          <RiskRow
            key={risk.recommendation_id}
            risk={risk}
            assignableOwners={assignableOwners}
            onAccept={onAccept}
            onReject={onReject}
            onAssignOwner={onAssignOwner}
            isAccepting={isAccepting(risk.recommendation_id)}
            isRejecting={isRejecting(risk.recommendation_id)}
            isAssigning={isAssigning(risk.recommendation_id)}
          />
        ))}
      </div>
    </div>
  );
}
