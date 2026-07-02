export type RecommendationSeverity = "low" | "medium" | "high";
export type RecommendationStatus = "pending" | "accepted" | "rejected";
export type OwnerType = "user" | "team";

export type MitigationRecommendation = {
  id: string;
  project_id: string;
  title: string;
  description: string | null;
  severity: RecommendationSeverity;
  confidence_score: number;
  status: RecommendationStatus;
  owner_type: OwnerType | null;
  owner_id: string | null;
  owner_label: string | null;
  source_risk_id: string | null;
  source_risk_title: string | null;
  source_risk_type: string | null;
  created_at: string;
  updated_at: string;
};

export type OwnerOption = {
  owner_type: OwnerType;
  owner_id: string;
  label: string;
};

// One risk-level member within a GroupedMitigationRecommendation. Keeps its own
// id/status/confidence so accept/reject/assign-owner still act on a single recommendation.
export type GroupedRecommendationRisk = {
  recommendation_id: string;
  source_risk_id: string | null;
  source_risk_title: string | null;
  description: string | null;
  status: RecommendationStatus;
  confidence_score: number;
  // True when confidence_score is a static per-tier fallback rather than a computed
  // slippage probability — surfaced in the UI as an "(est.)" marker.
  is_estimated: boolean;
  owner_type: OwnerType | null;
  owner_id: string | null;
  owner_label: string | null;
};

// Recommendations sharing the same action title, grouped for display by the backend
// (see group_recommendations_by_title). Replaces what used to be N visually identical cards.
export type GroupedMitigationRecommendation = {
  title: string;
  severity: RecommendationSeverity;
  confidence_score: number;
  is_estimated: boolean;
  project_id: string;
  risks: GroupedRecommendationRisk[];
  statuses: RecommendationStatus[];
  descriptions: string[];
};

export type ProjectRecommendationsResponse = {
  data: GroupedMitigationRecommendation[];
  assignable_owners: OwnerOption[];
  pagination: { limit: number; next_cursor: string | null };
};

export type AssignOwnerPayload = {
  owner_type: OwnerType | null;
  owner_id: string | null;
};

export const SEVERITY_ORDER: Record<RecommendationSeverity, number> = {
  high: 0,
  medium: 1,
  low: 2,
};

export const SEVERITY_LABELS: Record<RecommendationSeverity, string> = {
  high: "High",
  medium: "Medium",
  low: "Low",
};
