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

export type ProjectWorkforceSummaryRead = {
  project_id: string;
  teams: TeamRead[];
  annotators: AnnotatorRead[];
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

export type UtilizationSnapshotCreatePayload = {
  team_id?: string | null;
  annotator_id?: string | null;
  snapshot_date: string;
  allocated_hours: number;
  available_hours: number;
  utilization_pct?: number | null;
  billable_hours?: number | null;
  non_billable_hours?: number | null;
  notes?: string | null;
};

export type UtilizationSnapshotUpdatePayload = Partial<UtilizationSnapshotCreatePayload>;

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

export type ProjectSkillRequirementCreatePayload = {
  skill_id: string;
  required_proficiency_level: ProficiencyLevel;
  required_headcount?: number;
  required_sme_count?: number;
  priority?: SkillRequirementPriority;
};

export type ProjectSkillRequirementUpdatePayload = {
  required_proficiency_level?: ProficiencyLevel;
  required_headcount?: number;
  required_sme_count?: number;
  priority?: SkillRequirementPriority;
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

export type CapabilityGapType =
  | "skill_shortage"
  | "sme_shortage"
  | "certification_gap"
  | "training_gap"
  | "utilization_overload"
  | "utilization_underload";

export type CapabilityGapSeverity = "low" | "medium" | "high" | "critical";

export type CapabilityGapStatus = "open" | "acknowledged" | "resolved" | "dismissed";

export type CapabilityGapRead = {
  id: string;
  org_id: string;
  project_id: string;
  team_id: string | null;
  skill_id: string | null;
  gap_type: CapabilityGapType;
  severity: CapabilityGapSeverity;
  title: string;
  detail: string;
  evidence: Record<string, unknown> | null;
  status: CapabilityGapStatus;
  detected_at: string;
  resolved_at: string | null;
  created_at: string;
  updated_at: string;
};

export type CapabilityGapUpdatePayload = {
  status?: CapabilityGapStatus;
  severity?: CapabilityGapSeverity;
  title?: string;
  detail?: string;
};

export type CapabilityGapDetectionResponse = {
  project_id: string;
  detected_count: number;
  created_count: number;
  gaps: CapabilityGapRead[];
  risk_alerts_created: number;
  recommendations_created: number;
};

export type WorkforceRecommendationRead = {
  id: string;
  project_id: string;
  title: string;
  description: string | null;
  severity: string;
  confidence_score: string | number;
  status: string;
  owner_type: string | null;
  owner_id: string | null;
  owner_label: string | null;
  source_risk_id: string | null;
  source_risk_title: string | null;
  source_risk_type: string | null;
  created_at: string;
  updated_at: string;
};

export type WorkforceRecommendationGenerateResponse = {
  project_id: string;
  recommendations_created: number;
  recommendations: WorkforceRecommendationRead[];
};

export type CertificationStatus = "active" | "expired" | "pending_review" | "revoked";

export type TrainingRecordStatus =
  | "not_started"
  | "in_progress"
  | "completed"
  | "failed"
  | "expired";

export type AnnotatorSkillRead = {
  id: string;
  org_id: string;
  annotator_id: string;
  skill_id: string;
  proficiency_level: ProficiencyLevel;
  verified_by: string | null;
  verified_at: string | null;
  created_at: string;
  updated_at: string;
};

export type AnnotatorSkillCreatePayload = {
  skill_id: string;
  proficiency_level: ProficiencyLevel;
};

export type AnnotatorSkillUpdatePayload = {
  proficiency_level?: ProficiencyLevel;
};

export type CertificationRead = {
  id: string;
  org_id: string;
  name: string;
  issuing_body: string | null;
  description: string | null;
  validity_months: number | null;
  is_required_for_sme: boolean;
  created_at: string;
  updated_at: string;
};

export type EmployeeCertificationRead = {
  id: string;
  org_id: string;
  annotator_id: string;
  certification_id: string;
  issued_at: string | null;
  expires_at: string | null;
  status: CertificationStatus;
  evidence_url: string | null;
  created_at: string;
  updated_at: string;
};

export type EmployeeCertificationCreatePayload = {
  certification_id: string;
  status?: CertificationStatus;
  issued_at?: string | null;
  expires_at?: string | null;
};

export type EmployeeCertificationUpdatePayload = {
  status?: CertificationStatus;
  issued_at?: string | null;
  expires_at?: string | null;
};

export type TrainingProgramRead = {
  id: string;
  org_id: string;
  skill_id: string | null;
  name: string;
  description: string | null;
  required_for_skill_level: ProficiencyLevel | null;
  is_mandatory: boolean;
  knowledge_document_id: string | null;
  created_at: string;
  updated_at: string;
};

export type TrainingRecordRead = {
  id: string;
  org_id: string;
  annotator_id: string;
  training_program_id: string;
  status: TrainingRecordStatus;
  started_at: string | null;
  completed_at: string | null;
  score_pct: string | number | null;
  created_at: string;
  updated_at: string;
};

export type TrainingRecordCreatePayload = {
  training_program_id: string;
  status?: TrainingRecordStatus;
};

export type TrainingRecordUpdatePayload = {
  status?: TrainingRecordStatus;
};

export type AgentQueryEvidenceLinkRead = {
  id: string | null;
  source_table: string;
  source_row_id: string;
  description: string;
  created_at: string | null;
};

export type AgentQueryRead = {
  id: string;
  agent_name: string;
  project_id: string | null;
  query_text: string;
  answer_text: string;
  model_used: string | null;
  latency_ms: number | null;
  created_at: string;
  evidence_links: AgentQueryEvidenceLinkRead[];
};

export type AgentQueryCreate = {
  agent_name: string;
  project_id?: string | null;
  query_text: string;
};
