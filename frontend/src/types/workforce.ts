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

export type TeamCreatePayload = {
  name: string;
  site: DeliverySite;
  domain: string;
  is_active?: boolean;
};

export type TeamUpdatePayload = {
  name?: string;
  site?: DeliverySite;
  domain?: string;
  is_active?: boolean;
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

export type AnnotatorCreatePayload = {
  full_name: string;
  site: DeliverySite;
  is_sme_certified?: boolean;
  is_active?: boolean;
};

export type AnnotatorUpdatePayload = {
  full_name?: string;
  site?: DeliverySite;
  is_sme_certified?: boolean;
  is_active?: boolean;
  team_id?: string;
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

export type ProjectWorkforceDashboardRead = {
  project_id: string;
  summary: ProjectWorkforceSummaryRead;
  utilization: UtilizationSnapshotRead[];
  skill_matrix: SkillMatrixRead;
  training_gaps: TrainingGapSummaryRead;
  capability_gaps: CapabilityGapRead[];
  recommendations: {
    data: Array<{
      title: string;
      severity: string;
      confidence_score: number | string;
      is_estimated?: boolean;
      project_id: string;
      risks: Array<{
        recommendation_id: string;
        source_risk_id: string | null;
        source_risk_title: string | null;
        source_risk_type: string | null;
        description: string | null;
        status: string;
        confidence_score: number | string;
        is_estimated?: boolean;
        owner_type: string | null;
        owner_id: string | null;
        owner_label: string | null;
      }>;
      statuses: string[];
      descriptions: string[];
    }>;
    assignable_owners: Array<{
      owner_type: string;
      owner_id: string;
      label: string;
    }>;
    pagination: { limit: number; next_cursor?: string | null };
  };
  optimization?: WorkforceOptimizationRead | null;
};

export type RecommendationSourceEntity = {
  source_table: string;
  source_row_id: string | null;
  label: string | null;
  attributes?: Record<string, unknown>;
};

export type RecommendationCalculation = {
  name: string;
  description: string;
  inputs?: Record<string, unknown>;
  result?: unknown;
  formula?: string | null;
};

export type RecommendationEvidenceItem = {
  evidence_id: string;
  summary: string;
  source_entities: RecommendationSourceEntity[];
  metric_keys: string[];
  document_ids: string[];
  observed_at: string | null;
  visibility: "internal" | "client_safe";
  attributes?: Record<string, unknown>;
};

export type RecommendationLineage = {
  recommendation_id: string;
  recommendation_type: string;
  generated_at: string;
  confidence_score: number;
  evidence: RecommendationEvidenceItem[];
  source_entities: RecommendationSourceEntity[];
  calculations: RecommendationCalculation[];
  metrics_involved: string[];
  documents_referenced: string[];
  related_entity_ids: Record<string, string[]>;
  model_version: string;
  notes: string | null;
};

export type SkillMatchCandidate = {
  annotator_id: string;
  annotator_name: string;
  team_id: string;
  team_name: string | null;
  site: string;
  is_sme_certified: boolean;
  match_score: number;
  confidence_score: number;
  strengths: string[];
  missing_skills: string[];
  reasoning: string;
  utilization_pct: number | null;
  proficiency_level: string | null;
  active_certification_count: number;
  lineage: RecommendationLineage;
};

export type SkillMatchRecommendation = {
  skill_id: string;
  skill_name: string;
  required_proficiency_level: string;
  required_headcount: number;
  required_sme_count: number;
  priority: string;
  headcount_shortfall: number;
  candidates: SkillMatchCandidate[];
};

export type WorkloadRebalanceRecommendation = {
  recommendation_id: string;
  annotator_id: string;
  annotator_name: string;
  source_team_id: string;
  source_team_name: string;
  source_utilization_pct: number;
  destination_team_id: string;
  destination_team_name: string;
  destination_utilization_pct: number;
  estimated_utilization_improvement: number;
  confidence_score: number;
  risks: string[];
  expected_business_impact: string;
  reasoning: string;
  lineage: RecommendationLineage;
};

export type ResourcePlanningRecommendation = {
  recommendation_id: string;
  role: string;
  skill_id: string | null;
  skill_name: string | null;
  estimated_headcount: number;
  hiring_priority: string;
  urgency: string;
  confidence_score: number;
  affected_projects: string[];
  reasoning: string;
  required_proficiency_level: string | null;
  current_available: number;
  current_shortfall: number;
  sme_shortfall: number;
  lineage: RecommendationLineage;
};

export type SmeCoverageFinding = {
  finding_type: string;
  severity: string;
  summary: string;
  annotator_id: string | null;
  annotator_name: string | null;
};

export type SmeCoverageRecommendation = {
  recommendation_id: string;
  skill_id: string;
  skill_name: string;
  severity: string;
  confidence_score: number;
  findings: SmeCoverageFinding[];
  recommended_actions: string[];
  sme_count: number;
  required_sme_count: number;
  backup_candidate_count: number;
  reasoning: string;
  lineage: RecommendationLineage;
};

export type UtilizationForecastPoint = {
  week_offset: number;
  forecast_date: string;
  projected_utilization_pct: number;
  confidence_score: number;
};

export type WorkforceSkillShortage = {
  skill_id: string;
  skill_name: string;
  required_headcount: number;
  available_headcount: number;
  shortfall: number;
  severity: string;
  priority: string;
};

export type WorkforceInsight = {
  insight_id: string;
  category: string;
  urgency: string;
  title: string;
  detail: string;
  confidence_score: number;
  related_recommendation_ids: string[];
};

export type WorkforcePriorityAction = {
  action_id: string;
  title: string;
  detail: string;
  urgency: string;
  category: string;
  confidence_score: number;
};

export type WorkforceOptimizationRead = {
  project_id: string;
  generated_at: string;
  skill_matches: SkillMatchRecommendation[];
  rebalancing: WorkloadRebalanceRecommendation[];
  resource_planning: ResourcePlanningRecommendation[];
  sme_coverage: SmeCoverageRecommendation[];
  utilization_forecast: UtilizationForecastPoint[];
  skill_shortages: WorkforceSkillShortage[];
  insights: WorkforceInsight[];
  priority_actions: WorkforcePriorityAction[];
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
  retrieval_params?: Record<string, unknown> | null;
  confidence_level?: string | null;
  insufficient_evidence?: boolean;
  related_records?: Array<Record<string, unknown>>;
  source_agents_used?: string[];
  evidence_links: AgentQueryEvidenceLinkRead[];
};

export type AgentQueryCreate = {
  agent_name: string;
  project_id?: string | null;
  query_text: string;
  filters?: Record<string, unknown> | null;
};
