export type EvidenceVisibility = "internal" | "client_safe";
export type DataQualityState = "complete" | "partial" | "stale" | "conflicting" | "unavailable";
export type SourceAgent =
  | "delivery_performance"
  | "quality_intelligence"
  | "workforce_capability"
  | "project_governance"
  | "operational_knowledge"
  | "client_intelligence";

export type ReportingPeriod = {
  start_date: string;
  end_date: string;
  previous_start_date: string;
  previous_end_date: string;
  as_of: string;
};

export type ClientIntelligenceProjectIdentity = {
  project_id: string;
  org_id: string;
  project_name: string;
  project_status: string;
};

export type DataQualityIssue = {
  source: string;
  state: DataQualityState;
  detail: string;
  observed_at: string | null;
};

export type VisibilityLimitation = {
  source: string;
  reason: string;
  detail: string;
};

type BaseEvidenceReference = {
  source_agent: SourceAgent;
  source_table: string;
  source_row_id: string;
  visibility: EvidenceVisibility;
  claim_keys: string[];
};

export type ProjectHealthEvidenceReference = BaseEvidenceReference;
export type ProjectHealthStatus = "green" | "amber" | "red" | "insufficient";
export type ProjectHealthSignalState =
  | "positive"
  | "neutral"
  | "watch"
  | "adverse"
  | "unavailable"
  | "stale"
  | "conflicting";

export type ProjectHealthSignal = {
  signal_key: string;
  source_agent: SourceAgent;
  source_table: string;
  binding_type: "direct" | "unavailable";
  observed_value: string | number | boolean | null;
  signal_state: ProjectHealthSignalState;
  observed_at: string | null;
  data_quality: DataQualityState;
  evidence: ProjectHealthEvidenceReference[];
  limitation: string | null;
};

export type ProjectHealthDriver = {
  driver_key: string;
  polarity: "positive" | "negative";
  materiality: number;
  reason_code: string;
  signal_keys: string[];
  evidence: ProjectHealthEvidenceReference[];
};

export type ProjectHealthHistory = {
  previous_status: ProjectHealthStatus | null;
  current_status: ProjectHealthStatus;
  trend: "improving" | "stable" | "deteriorating" | "unknown";
  previous_reporting_period: ReportingPeriod | null;
  added_driver_keys: string[];
  removed_driver_keys: string[];
  changed_driver_keys: string[];
  limitation: string | null;
};

export type ProjectHealthAssessment = {
  org_id: string;
  project_id: string;
  reporting_period: ReportingPeriod;
  visibility_mode: EvidenceVisibility;
  status: ProjectHealthStatus;
  rules_version: string | null;
  source_fingerprint: string;
  policy_fingerprint: string | null;
  overall_data_quality: DataQualityState;
  signals: ProjectHealthSignal[];
  positive_drivers: ProjectHealthDriver[];
  negative_drivers: ProjectHealthDriver[];
  limitations: string[];
  evidence: ProjectHealthEvidenceReference[];
  history: ProjectHealthHistory;
  assessed_at: string;
};

export type DeliveryConfidenceEvidenceReference = BaseEvidenceReference & {
  period: "current" | "previous";
  source_fingerprint: string;
  observed_at: string | null;
};

export type DeliveryConfidenceMilestone = {
  milestone_id: string;
  name: string;
  status: string;
  planned_date: string;
  actual_date: string | null;
  evidence: DeliveryConfidenceEvidenceReference[];
};

export type DeliveryConfidenceDriver = {
  driver_key: string;
  polarity: "positive" | "negative";
  category:
    | "delivery_confidence"
    | "milestone"
    | "throughput"
    | "quality"
    | "bottleneck"
    | "dependency"
    | "risk"
    | "mitigation";
  reason_code: string;
  materiality: number;
  candidate_keys: string[];
  evidence: DeliveryConfidenceEvidenceReference[];
  data_quality: DataQualityState;
};

export type DeliveryConfidenceAssessment = {
  org_id: string;
  project_id: string;
  reporting_period: ReportingPeriod;
  visibility_mode: EvidenceVisibility;
  availability: "available" | "stale" | "conflicting" | "partial" | "no_score";
  score_pct: string | null;
  confidence_band: string | null;
  confidence_band_is_delivery_owned_status: true;
  current_milestone: DeliveryConfidenceMilestone | null;
  forecast_completion_date: string | null;
  observed_at: string | null;
  source_data_quality: DataQualityState;
  trend: "increased" | "decreased" | "stable" | "unknown";
  previous_score_pct: string | null;
  positive_drivers: DeliveryConfidenceDriver[];
  negative_drivers: DeliveryConfidenceDriver[];
  mitigation_contribution: "verified" | "none_proven" | "unavailable";
  limitations: string[];
  source_limitations: string[];
  evidence: DeliveryConfidenceEvidenceReference[];
  source_fingerprint: string;
  previous_source_fingerprint: string | null;
  rules_version: string | null;
  assessed_at: string;
};

export type RiskTransparencyEvidenceReference = BaseEvidenceReference & {
  period: "current";
  source_fingerprint: string;
  observed_at: string | null;
};

export type RiskBusinessImpact = {
  dimension: "timeline" | "scope" | "quality" | "readiness" | "client_action" | "unavailable";
  quantified: boolean;
  amount: null;
  unit: null;
  limitations: string[];
};

export type RiskMitigation = {
  availability: "unavailable";
  owner_role: null;
  progress: null;
  target: null;
  residual_risk: null;
  client_action: null;
  limitations: string[];
};

export type RiskTransparencyItem = {
  source_row_id: string;
  source_type: "risk_alert" | "bottleneck";
  source_agent: SourceAgent;
  source_table: string;
  source_fingerprint: string;
  category:
    | "resource_constraint"
    | "qa_rework"
    | "workflow_bottleneck"
    | "dependency_delay"
    | "unclassified";
  status: string;
  risk_tier: "low" | "medium" | "high" | "critical" | null;
  alert_type: string | null;
  materiality: "material" | "not_material" | "undecided";
  client_visibility: "client_visible" | "internal_only" | "undecided";
  data_quality: DataQualityState;
  visibility: EvidenceVisibility;
  observed_at: string | null;
  business_impact: RiskBusinessImpact;
  mitigation: RiskMitigation;
  evidence: RiskTransparencyEvidenceReference[];
  limitations: string[];
};

export type RiskTransparencyAssessment = {
  org_id: string;
  project_id: string;
  as_of: string;
  visibility_mode: EvidenceVisibility;
  availability: "available" | "partial" | "unavailable" | "stale" | "conflicting";
  risk_items: RiskTransparencyItem[];
  evidence: RiskTransparencyEvidenceReference[];
  limitations: string[];
  source_limitations: string[];
  source_fingerprint: string;
  rules_version: string | null;
  assessed_at: string;
};

export type DeliveryTrendEvidenceReference = BaseEvidenceReference & {
  period: "current";
  source_fingerprint: string;
  observed_at: string | null;
};

export type TrendSeriesValueState =
  | "observed"
  | "missing_source"
  | "redacted"
  | "unavailable"
  | "stale"
  | "conflicting";

export type DeliveryTrendPoint = {
  snapshot_date: string;
  source_row_id: string;
  source_agent: SourceAgent;
  source_table: string;
  actual_units: number | null;
  actual_state: TrendSeriesValueState;
  plan_units: number | null;
  plan_state: TrendSeriesValueState;
  forecast_units: number | null;
  forecast_state: TrendSeriesValueState;
  delta_actual_forecast: number | null;
  delta_actual_plan: number | null;
  data_quality: DataQualityState | null;
  visibility: EvidenceVisibility;
  source_fingerprint: string;
  evidence: DeliveryTrendEvidenceReference[];
  limitations: string[];
};

export type DeliveryTrendDeviation = {
  candidate_key: string;
  source_row_id: string;
  snapshot_date: string;
  actual_units: number;
  forecast_units: number;
  delta_actual_forecast: number;
  materiality: "material" | "not_material";
  data_quality: "complete";
  visibility: EvidenceVisibility;
  source_fingerprint: string;
  evidence: DeliveryTrendEvidenceReference[];
};

export type DeliveryTrendAssessment = {
  org_id: string;
  project_id: string;
  as_of: string;
  covered_start_date: string;
  covered_end_date: string;
  grain: "day";
  timezone: "utc";
  visibility_mode: EvidenceVisibility;
  availability: "available" | "partial" | "stale" | "conflicting" | "unavailable";
  trend_points: DeliveryTrendPoint[];
  deviations: DeliveryTrendDeviation[];
  evidence: DeliveryTrendEvidenceReference[];
  limitations: string[];
  source_limitations: string[];
  source_fingerprint: string;
  rules_version: string | null;
  assessed_at: string;
};

export type ClientIntelligenceOverview = {
  project: ClientIntelligenceProjectIdentity;
  reporting_period: ReportingPeriod;
  as_of: string;
  generated_at: string;
  visibility_mode: EvidenceVisibility;
  source_fingerprint: string;
  overall_data_quality: DataQualityState;
  data_quality: DataQualityIssue[];
  source_limitations: string[];
  visibility_limitations: VisibilityLimitation[];
  project_health: ProjectHealthAssessment;
  delivery_confidence: DeliveryConfidenceAssessment;
  risk_transparency: RiskTransparencyAssessment;
  delivery_trend: DeliveryTrendAssessment;
  readiness?: ReadinessAssessment | null;
  go_live?: GoLiveAssessment | null;
  recommendations?: ReadinessRecommendationSet | null;
};

export type ReadinessStatus =
  | "ready"
  | "ready_with_minor_risks"
  | "conditionally_ready"
  | "not_ready"
  | "insufficient_evidence";

export type ReadinessCategoryKey =
  | "resources"
  | "planning"
  | "risks"
  | "dependencies"
  | "documentation"
  | "testing"
  | "training"
  | "governance";

export type AiExplainability = {
  why_generated: string;
  supporting_evidence: Array<{
    source_agent: string;
    source_table: string;
    source_row_id: string;
    visibility: EvidenceVisibility;
    claim_keys: string[];
    summary?: string | null;
    observed_at?: string | null;
  }>;
  confidence_score: string;
  confidence_band: "high" | "medium" | "low" | "insufficient";
  assumptions: string[];
  affected_kpis: string[];
  reasoning?: string | null;
  model_version: string;
};

export type ReadinessCategoryScore = {
  category: ReadinessCategoryKey;
  score_pct: string | null;
  availability: string;
  weight: string;
  missing_requirements: string[];
  blockers: string[];
  positive_findings: string[];
  limitations: string[];
  data_quality: DataQualityState;
};

export type ReadinessAssessment = {
  org_id: string;
  project_id: string;
  as_of: string;
  assessed_at: string;
  availability: string;
  overall_score_pct: string | null;
  status: ReadinessStatus;
  assessment_confidence: string;
  categories: ReadinessCategoryScore[];
  missing_requirements: string[];
  major_blockers: string[];
  positive_findings: string[];
  limitations: string[];
  source_fingerprint: string;
  rules_version: string;
  explainability?: AiExplainability | null;
};

export type GoLiveDecision = "go" | "go_with_conditions" | "no_go";

export type GoLiveAssessment = {
  org_id: string;
  project_id: string;
  as_of: string;
  assessed_at: string;
  availability: string;
  decision: GoLiveDecision;
  confidence_score: string;
  reasons: string[];
  blocking_items: string[];
  required_actions: string[];
  outstanding_defects: string[];
  open_blockers: string[];
  required_approvals: string[];
  dependency_gaps: string[];
  rollout_readiness_notes: string[];
  limitations: string[];
  source_fingerprint: string;
  rules_version: string;
  explainability?: AiExplainability | null;
};

export type ReadinessRecommendation = {
  recommendation_id: string;
  recommendation_type: string;
  title: string;
  priority: "critical" | "high" | "medium" | "low";
  expected_business_impact: string;
  confidence: string;
  reasoning: string;
  category?: ReadinessCategoryKey | null;
  explainability: AiExplainability;
};

export type ReadinessRecommendationSet = {
  org_id: string;
  project_id: string;
  assessed_at: string;
  recommendations: ReadinessRecommendation[];
  source_fingerprint: string;
  rules_version: string;
  limitations: string[];
};

export type ClientDashboard = {
  project_id: string;
  as_of: string;
  generated_at: string;
  readiness?: ReadinessAssessment | null;
  go_live?: GoLiveAssessment | null;
  recommendations?: ReadinessRecommendationSet | null;
  project_health?: ProjectHealthAssessment | null;
  reports_drafted_count: number;
  reports_approved_count: number;
  reports_published_count: number;
  communications_pending_count: number;
  open_approvals_count: number;
  milestone_on_track_count: number;
  milestone_at_risk_count: number;
  widget_availability: Record<string, "available" | "partial" | "unavailable">;
  limitations: string[];
};

export type ClientReportCadence = "weekly" | "monthly" | "quarterly" | "executive";

export type ClientReportGovernanceStatus =
  | "draft"
  | "pending_manager"
  | "pending_leadership"
  | "pending_compliance"
  | "published"
  | "rejected";

export type ClientReportDeliveryStatus = "pending" | "distributed" | "failed";

export type ReportSectionKey =
  | "executive_summary"
  | "project_status"
  | "risks"
  | "milestones"
  | "confidence"
  | "timeline"
  | "readiness"
  | "go_live"
  | "recommendations";

export type ReportSectionConfig = {
  section: ReportSectionKey;
  enabled: boolean;
};

export type ClientReportSchedule = {
  id: string;
  org_id: string;
  project_id: string;
  cadence: ClientReportCadence;
  enabled: boolean;
  section_config: ReportSectionConfig[] | Array<Record<string, unknown>>;
  next_run_at: string | null;
  last_run_at: string | null;
  last_package_id: string | null;
  created_by: string | null;
  created_at: string;
  updated_at: string;
};

export type ClientReportPackage = {
  id: string;
  org_id: string;
  project_id: string;
  schedule_id: string | null;
  communication_id: string | null;
  report_type: ClientReportCadence;
  title: string;
  body_markdown: string;
  section_config: ReportSectionConfig[] | Array<Record<string, unknown>>;
  version: number;
  status: ClientReportGovernanceStatus;
  source_fingerprint: string | null;
  rejection_reason: string | null;
  created_by: string | null;
  updated_by: string | null;
  published_at: string | null;
  created_at: string;
  updated_at: string;
};

export type ClientReportApproval = {
  id: string;
  org_id: string;
  package_id: string;
  from_status: ClientReportGovernanceStatus | null;
  to_status: ClientReportGovernanceStatus;
  actor_user_id: string | null;
  comment: string | null;
  rejection_reason: string | null;
  created_at: string;
};

export type ClientReportDelivery = {
  id: string;
  org_id: string;
  package_id: string;
  channel: string;
  status: ClientReportDeliveryStatus;
  recipient_summary: string | null;
  error_detail: string | null;
  delivered_at: string | null;
  created_at: string;
};

export type ReportGovernanceAction = "submit" | "approve" | "reject" | "resubmit";

export type ReportExportFormat = "pdf" | "docx";

export const REPORT_SECTION_OPTIONS: Array<{ key: ReportSectionKey; label: string }> = [
  { key: "executive_summary", label: "Executive Summary" },
  { key: "project_status", label: "Project Status" },
  { key: "confidence", label: "Confidence" },
  { key: "milestones", label: "Milestones" },
  { key: "risks", label: "Risks" },
  { key: "timeline", label: "Timeline" },
  { key: "readiness", label: "Readiness" },
  { key: "go_live", label: "Go-Live" },
  { key: "recommendations", label: "Recommendations" },
];

export const REPORT_CADENCE_OPTIONS: Array<{ value: ClientReportCadence; label: string }> = [
  { value: "weekly", label: "Weekly" },
  { value: "monthly", label: "Monthly" },
  { value: "quarterly", label: "Quarterly" },
  { value: "executive", label: "Executive" },
];

export const GOVERNANCE_STATUS_LABELS: Record<ClientReportGovernanceStatus, string> = {
  draft: "Draft",
  pending_manager: "Manager Review",
  pending_leadership: "Leadership Review",
  pending_compliance: "Compliance Review",
  published: "Published",
  rejected: "Rejected",
};

export type SummaryMetricAvailability = "available" | "no_data" | "partial" | "unavailable";

export type DeliveryConfidenceSummaryMetric = {
  availability: SummaryMetricAvailability;
  average_score_pct: string | null;
  covered_project_count: number;
  eligible_project_count: number;
  limitations: string[];
};

export type ReportsSummaryMetric = {
  availability: SummaryMetricAvailability;
  drafted_count: number;
  approved_count: number;
  eligible_record_count: number;
  limitations: string[];
};

export type QueryResponseSummaryMetric = {
  availability: SummaryMetricAvailability;
  average_latency_ms: number | null;
  sample_size: number;
  limitations: string[];
};

export type CsatSummaryMetric = {
  availability: SummaryMetricAvailability;
  average_score: string | null;
  sample_size: number;
  scale_max: 5;
  limitations: string[];
};

export type ClientIntelligenceSummary = {
  delivery_confidence: DeliveryConfidenceSummaryMetric;
  reports: ReportsSummaryMetric;
  query_response: QueryResponseSummaryMetric;
  csat: CsatSummaryMetric;
  authorized_project_count: number;
};

export type ClientMasterHealthAvailability = "not_assessed";

export type ClientMasterRow = {
  project_id: string;
  project_name: string;
  project_count: 1;
  health_status: ProjectHealthStatus | null;
  health_availability: ClientMasterHealthAvailability;
  confidence_score_pct: string | null;
  last_report_at: string | null;
  next_milestone_date: string | null;
  csat_average: string | null;
  csat_sample_size: number;
  draft_count: number;
};

export type DeliveryConfidenceHistoryAvailability =
  | "available"
  | "partial"
  | "no_data"
  | "unavailable";

export type DeliveryConfidenceCurrentScoreAvailability = "available" | "invalid" | "missing";

export type DeliveryConfidenceHistoryPoint = {
  source_row_id: string;
  project_id: string;
  milestone_id: string;
  score_pct: string;
  confidence_status: string;
  observed_at: string;
};

export type DeliveryConfidenceHistory = {
  project_id: string;
  availability: DeliveryConfidenceHistoryAvailability;
  points: DeliveryConfidenceHistoryPoint[];
  returned_point_count: number;
  total_valid_point_count: number;
  limitations: string[];
  current_score_availability: DeliveryConfidenceCurrentScoreAvailability;
  current_source_row_id: string | null;
  latest_history_point_is_current: boolean;
};

export type CommunicationEvidenceLink = {
  id: string | null;
  source_table: string;
  source_row_id: string;
  description: string;
  created_at: string | null;
};

export type ClientCommunicationDraft = {
  id: string;
  project_id: string;
  comm_type: "weekly_summary" | "executive_summary" | "ad_hoc";
  subject: string;
  body_draft: string;
  body_approved: string | null;
  status: "draft" | "in_review" | "approved" | "sent" | "rejected";
  drafted_by_agent: string;
  reviewed_by: string | null;
  reviewed_at: string | null;
  approved_by: string | null;
  approved_at: string | null;
  sent_at: string | null;
  rejection_reason: string | null;
  rejected_by: string | null;
  rejected_at: string | null;
  created_at: string;
  updated_at: string;
  evidence_links: CommunicationEvidenceLink[];
};

export type CommunicationDraftEditPayload = {
  subject: string;
  body_draft: string;
};

export type CommunicationReviewPayload = {
  body_approved: string;
};

export type CommunicationRejectPayload = {
  rejection_reason: string;
};

export type ClientIntelligenceReportStatus = "approved" | "sent";

export type ReportProvenanceAvailability = "complete" | "partial" | "unavailable";

export type ClientIntelligenceReportHistoryItem = {
  communication_id: string;
  project_id: string;
  report_type: string;
  subject: string;
  approved_body: string | null;
  status: ClientIntelligenceReportStatus;
  reviewed_by: string | null;
  reviewed_at: string | null;
  approved_by: string | null;
  approved_at: string | null;
  sent_at: string | null;
  history_at: string | null;
  provenance_availability: ReportProvenanceAvailability;
  limitations: string[];
  evidence_links: CommunicationEvidenceLink[];
  created_at: string;
  updated_at: string;
};

export type ClientIntelligenceReportHistory = {
  project_id: string;
  items: ClientIntelligenceReportHistoryItem[];
  limit: number;
  offset: number;
  total: number;
  has_more: boolean;
  status_filter: ClientIntelligenceReportStatus | null;
};

export type ReportHistoryStatusFilter = "all" | ClientIntelligenceReportStatus;

export type ClientIntelligenceAnswerAvailability =
  | "answered"
  | "insufficient_evidence"
  | "unsupported"
  | "provider_unavailable";

export type ClientIntelligenceConfidenceLevel = "high" | "medium" | "low" | "insufficient";

export type ClientIntelligenceQuestionCategory =
  | "project_health"
  | "delivery_confidence"
  | "confidence_history"
  | "milestones"
  | "risks"
  | "delivery_trend"
  | "change"
  | "reports"
  | "quality"
  | "workforce"
  | "governance"
  | "knowledge"
  | "commitment"
  | "cross_scope"
  | "sensitive"
  | "injection"
  | "unsupported"
  | "general_status";

export type ClientIntelligenceQueryEvidenceLink = {
  id: string;
  source_table: string;
  source_row_id: string;
  description: string;
  created_at: string | null;
};

export type ClientIntelligenceQueryRead = {
  query_id: string;
  project_id: string;
  question: string;
  answer_text: string;
  answer_availability: ClientIntelligenceAnswerAvailability;
  confidence_level: ClientIntelligenceConfidenceLevel;
  limitations: string[];
  next_step: string | null;
  escalation_required: boolean;
  source_agents: string[];
  evidence_links: ClientIntelligenceQueryEvidenceLink[];
  as_of: string | null;
  reporting_period_start: string | null;
  reporting_period_end: string | null;
  model_used: string | null;
  latency_ms: number | null;
  created_at: string;
  category: ClientIntelligenceQuestionCategory | null;
  insufficient_evidence: boolean;
};

export type ClientIntelligenceQueryHistorySource = "server" | "local_pending" | "unavailable";

export type ClientIntelligenceQueryHistory = {
  project_id: string;
  items: ClientIntelligenceQueryRead[];
  limit: number;
  offset: number;
  total: number;
  has_more: boolean;
  /** Absent or "server" means total/has_more come from the API. */
  history_source?: ClientIntelligenceQueryHistorySource;
};
