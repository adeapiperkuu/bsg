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

export type ProjectRecommendationsResponse = {
  data: MitigationRecommendation[];
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
