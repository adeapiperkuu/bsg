export type DeliverySite = "india" | "kosovo";

export type ProficiencyLevel = "beginner" | "intermediate" | "advanced" | "expert";

export type SkillRequirementPriority = "low" | "medium" | "high" | "critical";

export type SkillCoverageStatus = "high" | "medium" | "low";

export type TeamRead = {
  id: string;
  project_id: string;
  org_id: string;
  name: string;
  site: DeliverySite;
  domain: string;
  is_active: boolean;
  created_at: string;
  updated_at: string;
};

export type AnnotatorRead = {
  id: string;
  org_id: string;
  team_id: string;
  full_name: string;
  site: DeliverySite;
  is_sme_certified: boolean;
  is_active: boolean;
  created_at: string;
  updated_at: string;
};

export type UtilizationSnapshotRead = {
  id: string;
  org_id: string;
  project_id: string;
  team_id: string | null;
  annotator_id: string | null;
  snapshot_date: string;
  allocated_hours: string | number;
  available_hours: string | number;
  utilization_pct: string | number;
  billable_hours: string | number | null;
  non_billable_hours: string | number | null;
  notes: string | null;
  created_at: string;
  updated_at: string;
};

export type ProjectUtilizationFilters = {
  team_id?: string;
  annotator_id?: string;
  from_date?: string;
  to_date?: string;
  limit?: number;
};

export type SkillRead = {
  id: string;
  org_id: string;
  name: string;
  category: string | null;
  domain: string | null;
  description: string | null;
  is_critical: boolean;
  created_at: string;
  updated_at: string;
};

export type ProjectSkillRequirementRead = {
  id: string;
  org_id: string;
  project_id: string;
  skill_id: string;
  required_proficiency_level: ProficiencyLevel;
  required_headcount: number;
  required_sme_count: number;
  priority: SkillRequirementPriority;
  created_at: string;
  updated_at: string;
};

export type SkillMatrixSiteSummary = {
  site: DeliverySite;
  available_headcount: number;
  available_sme_count: number;
  coverage_status: SkillCoverageStatus;
};

export type SkillMatrixRow = {
  skill_id: string;
  skill_name: string;
  category: string | null;
  domain: string | null;
  required_proficiency_level: ProficiencyLevel;
  required_headcount: number;
  available_headcount: number;
  required_sme_count: number;
  available_sme_count: number;
  coverage_status: SkillCoverageStatus;
  by_site: SkillMatrixSiteSummary[];
};

export type SkillMatrixRead = {
  project_id: string;
  rows: SkillMatrixRow[];
};

export type TrainingGapType =
  | "mandatory_training_incomplete"
  | "expired_or_failed_training"
  | "expired_certification"
  | "pending_certification_review";

export type TrainingGapRow = {
  team_id: string | null;
  team_name: string | null;
  skill_id: string | null;
  skill_name: string | null;
  training_program_id: string | null;
  training_program_name: string | null;
  certification_id: string | null;
  certification_name: string | null;
  gap_type: TrainingGapType;
  affected_count: number;
};

export type TrainingGapSummaryRead = {
  project_id: string;
  total_training_gaps: number;
  mandatory_training_incomplete: number;
  expired_or_failed_training: number;
  expired_certifications: number;
  pending_certification_reviews: number;
  rows: TrainingGapRow[];
};
