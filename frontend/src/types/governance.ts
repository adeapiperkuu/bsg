export type GovernanceEscalationSourceType =
  | "delivery_risk"
  | "knowledge_document"
  | "quality_risk";
export type GovernanceRecommendationAcceptanceStatus =
  | "not_accepted"
  | "partially_accepted"
  | "accepted_as_action"
  | "accepted_as_escalation";
export type GovernanceRecommendationConversionTarget = "action" | "escalation";

export type GovernanceScopeStatus = "approved" | "pending_revision" | "locked";
export type GovernanceDependencyType = "client_action" | "internal" | "external";
export type GovernanceDependencyStatus = "open" | "blocking" | "resolved";
export type GovernanceEscalationSeverity = "low" | "medium" | "high" | "critical";
export type GovernanceEscalationStatus = "open" | "in_progress" | "resolved";
export type GovernanceActionStatus = "open" | "in_progress" | "completed" | "overdue";
export type GovernanceCharterStatus = "draft" | "approved" | "archived";
export type GovernanceCharterPublicationStatus =
  | "not_published"
  | "publishing"
  | "published"
  | "failed"
  | "superseded";
export type KnowledgeVisibility = "internal_only" | "leadership_only" | "client_safe";
export type GovernanceEvidenceSourceType =
  | "dependency"
  | "escalation"
  | "action"
  | "scope_state"
  | "knowledge_document"
  | "delivery_signal"
  | "weekly_summary";

export type GovernanceSummaryStatus = "draft" | "approved";

export type GovernanceWeeklySummary = {
  id: string;
  org_id: string;
  summary_week: string;
  summary_text: string;
  status: GovernanceSummaryStatus;
  generated_by_ai: boolean;
  approved_by: string | null;
  approved_at: string | null;
  created_at: string;
  updated_at: string;
  evidence_links: GovernanceEvidenceLink[];
  evidence_link_count?: number;
  approved_by_name?: string | null;
  platform_report_id?: string | null;
};

export type GovernanceWeeklySummaryListItem = Omit<
  GovernanceWeeklySummary,
  "summary_text" | "evidence_links"
> & {
  evidence_link_count: number;
};

export type GovernanceKpis = {
  open_actions: number;
  overdue_actions: number;
  open_escalations: number;
  blocking_dependencies: number;
  at_risk_items: number;
  sla_adherence_pct: number;
};

export type GovernanceListPagination = {
  items: number;
  total: number;
  limit: number;
  offset: number;
  has_more: boolean;
};

export type PaginatedGovernanceList<T> = {
  items: T[];
  total: number;
  limit: number;
  offset: number;
  has_more: boolean;
};

export type GovernanceListParams = {
  limit?: number;
  offset?: number;
  project_id?: string;
  status?: string;
  severity?: string;
  dependency_type?: string;
  owner_id?: string;
  assigned_to?: string;
  search?: string;
  date_from?: string;
  date_to?: string;
};

/** Alias for KPI block in bootstrap responses. */
export type GovernanceKpiSummary = GovernanceKpis;

export type ProjectScopeState = {
  id: string;
  org_id: string;
  project_id: string;
  scope_status: GovernanceScopeStatus;
  version_label: string;
  notes: string | null;
  linked_charter_document_id?: string | null;
  created_by: string | null;
  updated_by: string | null;
  created_at: string;
  updated_at: string;
};

export type ProjectDependency = {
  id: string;
  org_id: string;
  project_id: string;
  title: string;
  description: string | null;
  dependency_type: GovernanceDependencyType;
  owner_id: string | null;
  due_date: string | null;
  status: GovernanceDependencyStatus;
  resolved_at: string | null;
  resolved_by: string | null;
  created_by: string | null;
  updated_by: string | null;
  created_at: string;
  updated_at: string;
  overdue_days: number;
  project_name: string | null;
  owner_name: string | null;
};

export type GovernanceEscalation = {
  id: string;
  org_id: string;
  project_id: string;
  title: string;
  description: string | null;
  severity: GovernanceEscalationSeverity;
  status: GovernanceEscalationStatus;
  raised_by: string | null;
  assigned_to: string | null;
  raised_at: string;
  resolved_at: string | null;
  created_at: string;
  updated_at: string;
  project_name: string | null;
  raised_by_name: string | null;
  assigned_to_name: string | null;
  source_type?: GovernanceEscalationSourceType | null;
  source_id?: string | null;
  client_summary?: string | null;
  client_visible?: boolean;
  client_published_at?: string | null;
  provenance_source_type?: "manual" | "ai_recommendation" | "delivery_risk" | "other";
  source_recommendation_id?: string | null;
  source_recommendation_title?: string | null;
  source_conversion_id?: string | null;
  evidence_link_count?: number;
  has_ai_source?: boolean;
};

export type GovernanceAction = {
  id: string;
  org_id: string;
  project_id: string;
  title: string;
  description: string | null;
  owner_id: string | null;
  due_date: string | null;
  status: GovernanceActionStatus;
  completed_at: string | null;
  created_by: string | null;
  updated_by: string | null;
  created_at: string;
  updated_at: string;
  project_name: string | null;
  owner_name: string | null;
  linked_knowledge_document_id?: string | null;
  provenance_source_type?: "manual" | "ai_recommendation" | "delivery_risk" | "other";
  source_recommendation_id?: string | null;
  source_recommendation_title?: string | null;
  source_conversion_id?: string | null;
  evidence_link_count?: number;
  has_ai_source?: boolean;
};

export type GovernanceRecordEvidenceLink = {
  id: string;
  link_type: string;
  source_type: string;
  source_id: string | null;
  evidence_id: string | null;
  recommendation_id: string | null;
  conversion_id: string | null;
  title: string | null;
  description: string | null;
  status: string | null;
  severity: string | null;
  project_id: string | null;
  project_name: string | null;
  occurred_at: string | null;
  created_at: string;
  source_available: boolean;
  can_view_source: boolean;
};

export type GovernanceSourceRecommendation = {
  id: string;
  title: string;
  recommendation_type: string | null;
  priority: string | null;
  confidence: number | null;
  generated_at: string | null;
  status: string | null;
  accepted_at: string | null;
  source_type: "ai_recommendation";
  can_view: boolean;
  source_available: boolean;
};

export type GovernanceEvidenceLink = {
  id: string;
  org_id: string;
  summary_id?: string | null;
  charter_id?: string | null;
  source_type: GovernanceEvidenceSourceType;
  source_id: string;
  created_at: string;
  label?: string | null;
  detail?: string | null;
  project_name?: string | null;
};

export type ProjectCharter = {
  id: string;
  org_id: string;
  project_id: string;
  version: string;
  status: GovernanceCharterStatus;
  generated_text: string;
  generated_by_ai: boolean;
  previous_version_id: string | null;
  knowledge_document_id: string | null;
  knowledge_version_id?: string | null;
  visibility: KnowledgeVisibility;
  approved_by: string | null;
  approved_at: string | null;
  publication_status?: GovernanceCharterPublicationStatus;
  published_at?: string | null;
  published_by?: string | null;
  publication_error?: string | null;
  publication_attempt_count?: number;
  last_publication_attempt_at?: string | null;
  created_at: string;
  updated_at: string;
  evidence_links: GovernanceEvidenceLink[];
  approved_by_name?: string | null;
  published_by_name?: string | null;
  project_name?: string | null;
  knowledge_url?: string | null;
};

export type ProjectChartersPanelData = {
  charters: ProjectCharter[];
  selected_charter: ProjectCharter | null;
  limit: number;
  offset: number;
  has_more: boolean;
};

export type CharterPublicationStatus = {
  charter_id: string;
  publication_status: GovernanceCharterPublicationStatus;
  knowledge_document_id: string | null;
  knowledge_version_id: string | null;
  published_at: string | null;
  published_by: string | null;
  published_by_name?: string | null;
  publication_error: string | null;
  publication_attempt_count: number;
  last_publication_attempt_at: string | null;
  knowledge_url: string | null;
  charter_status: GovernanceCharterStatus;
  charter_version: string;
};

export type CharterKnowledgeLink = CharterPublicationStatus & {
  project_name?: string | null;
  knowledge_document_title?: string | null;
  view_document_url?: string | null;
  open_in_knowledge_url?: string | null;
};

export type CharterPublicationVersion = {
  charter_id: string;
  charter_version: string;
  charter_status: GovernanceCharterStatus;
  publication_status: GovernanceCharterPublicationStatus;
  knowledge_document_id: string | null;
  knowledge_version_id: string | null;
  knowledge_version: string | null;
  created_at: string;
  published_at: string | null;
  published_by: string | null;
  published_by_name?: string | null;
  approval_date: string | null;
  knowledge_url: string | null;
};

export type ProjectDependencyListItem = Pick<
  ProjectDependency,
  | "id"
  | "project_id"
  | "title"
  | "dependency_type"
  | "owner_id"
  | "due_date"
  | "status"
  | "overdue_days"
  | "project_name"
  | "owner_name"
>;

export type GovernanceEscalationListItem = Pick<
  GovernanceEscalation,
  | "id"
  | "project_id"
  | "title"
  | "severity"
  | "status"
  | "raised_at"
  | "source_type"
  | "source_id"
  | "project_name"
  | "raised_by_name"
  | "assigned_to_name"
  | "description"
  | "client_summary"
  | "client_visible"
  | "client_published_at"
>;

export type GovernanceActionListItem = Pick<
  GovernanceAction,
  "id" | "project_id" | "title" | "owner_id" | "due_date" | "status" | "project_name" | "owner_name"
>;

export type GovernanceBootstrap = {
  kpis: GovernanceKpis;
  dependencies: ProjectDependencyListItem[];
  escalations: GovernanceEscalationListItem[];
  actions: GovernanceActionListItem[];
  scope_states: ProjectScopeState[];
};

export type GovernanceRegisterRowApi = {
  project_id: string;
  project_name: string;
  scope_status: GovernanceScopeStatus | null;
  scope_version: string | null;
  open_dependencies: number;
  blocking_dependencies: number;
  open_actions: number;
  open_escalations: number;
  health: "green" | "amber" | "red";
};

export type GovernanceProjectSheetSection<T> = {
  items: T[];
  total: number;
  has_more: boolean;
};

export type GovernanceProjectSheetRisk = {
  id: string;
  project_id: string;
  title: string;
  detail: string;
  risk_tier: string;
  status: string;
  created_at: string;
};

export type GovernanceProjectSheet = {
  project: {
    id: string;
    name: string;
    description: string | null;
    vertical: string;
    status: string;
    start_date: string;
    target_end_date: string;
  };
  summary: {
    scope_status: GovernanceScopeStatus | null;
    scope_version: string | null;
    open_dependencies: number;
    blocking_dependencies: number;
    overdue_actions: number;
    open_actions: number;
    open_escalations: number;
    critical_escalations: number;
    health: "green" | "amber" | "red";
  };
  scope: ProjectScopeState | null;
  dependencies: GovernanceProjectSheetSection<ProjectDependencyListItem>;
  actions: GovernanceProjectSheetSection<GovernanceActionListItem>;
  escalations: GovernanceProjectSheetSection<GovernanceEscalationListItem>;
  delivery_risks: GovernanceProjectSheetSection<GovernanceProjectSheetRisk>;
  permissions: {
    can_write: boolean;
    can_view_internal: boolean;
    can_view_delivery_risks: boolean;
  };
  generated_at: string;
};

export type GovernanceJobStatus =
  | "queued"
  | "running"
  | "retry_scheduled"
  | "succeeded"
  | "failed"
  | "cancellation_requested"
  | "cancelled";

export type GovernanceJobStart = {
  job_id: string;
  job_type: string;
  status: GovernanceJobStatus;
  deduplicated: boolean;
};

export type GovernanceJob = {
  id: string;
  org_id: string;
  project_id: string | null;
  job_type: string;
  status: GovernanceJobStatus;
  progress_stage: string;
  progress_percent: number;
  attempt_count: number;
  max_attempts: number;
  requested_at: string;
  started_at: string | null;
  completed_at: string | null;
  next_attempt_at: string | null;
  retryable: boolean;
  cancellable: boolean;
  error_code: string | null;
  error_message: string | null;
  result_record_type: string | null;
  result_record_id: string | null;
  result: Record<string, unknown> | null;
};

export type GovernanceAnalyticsEvidence = {
  source_type: string;
  source_id: string | null;
  label: string;
  detail: string | null;
  project_id: string | null;
  project_name: string | null;
};

export type GovernanceAnalyticsInsight = {
  title: string;
  detail: string;
  severity: string;
  evidence: GovernanceAnalyticsEvidence[];
};

export type GovernanceAnalyticsRecommendation = {
  title: string;
  detail: string;
  priority: string;
  project_id: string | null;
  project_name: string | null;
  evidence: GovernanceAnalyticsEvidence[];
};

export type GovernanceAISuggestedAction = {
  label: string;
  description: string;
  action_type: string;
  target_entity_type: string | null;
  target_entity_id: string | null;
};

export type GovernanceAIRecommendationEvidence = {
  evidence_id: string;
  entity_type: string;
  entity_id: string | null;
  project_id: string | null;
  title: string;
  summary: string;
  status: string | null;
  severity: string | null;
  occurred_at: string | null;
};

export type GovernanceAIRecommendation = {
  id: string;
  scope: "project" | "portfolio";
  project_id: string | null;
  project_name: string | null;
  recommendation_type: string;
  title: string;
  narrative: string;
  rationale: string;
  priority: "low" | "medium" | "high" | "critical";
  confidence: number;
  suggested_actions: GovernanceAISuggestedAction[];
  evidence: GovernanceAIRecommendationEvidence[];
  status: "active" | "dismissed" | "superseded" | "generation_failed" | "stale" | "snoozed";
  generated_at: string;
  expires_at: string | null;
  can_regenerate: boolean;
  can_dismiss: boolean;
  is_ai_generated: boolean;
  source_type: "ai" | "rule_based";
  is_stale: boolean;
  evidence_hash: string | null;
  acceptance_status: GovernanceRecommendationAcceptanceStatus;
  accepted_at: string | null;
  accepted_by_user_id: string | null;
  converted_action_id: string | null;
  converted_escalation_id: string | null;
  accepted_suggested_action_index: number | null;
  acceptance_note: string | null;
  auto_detected?: boolean;
  trigger_type?: string | null;
  trigger_entity_type?: string | null;
  trigger_entity_id?: string | null;
  severity_score?: number | null;
  detected_at?: string | null;
  snoozed_until?: string | null;
  can_snooze?: boolean;
  linked_milestone_id?: string | null;
  risk_categories?: string[];
  signal_providers?: string[];
  repeated_detection_count?: number | null;
  latest_detected_at?: string | null;
};

export type GovernanceRecommendationConversion = {
  id: string;
  recommendation_id: string;
  conversion_target: GovernanceRecommendationConversionTarget;
  suggested_action_index: number;
  created_action_id: string | null;
  created_escalation_id: string | null;
  created_by_user_id: string | null;
  created_at: string;
  note: string | null;
  idempotent_reuse: boolean;
  created_action: GovernanceAction | null;
  created_escalation: GovernanceEscalation | null;
  updated_recommendation: GovernanceAIRecommendation | null;
};

export type GovernanceAIRecommendationList = {
  items: GovernanceAIRecommendation[];
  rule_based: Array<{
    title: string;
    detail: string;
    priority: string;
    project_id: string | null;
    project_name: string | null;
    evidence: GovernanceAIRecommendationEvidence[];
    source_type: "rule_based";
    is_ai_generated: boolean;
  }>;
  total: number;
  ai_enabled: boolean;
  can_generate: boolean;
};

export type GovernanceAIRecommendationGenerationResult = {
  recommendations: GovernanceAIRecommendation[];
  rule_based_fallback: GovernanceAIRecommendationList["rule_based"];
  reused: boolean;
  fallback_used: boolean;
  fallback_reason: string | null;
  generation_request_id: string | null;
  evidence_hash: string | null;
  candidates_returned: number;
  candidates_persisted: number;
  candidates_rejected_grounding: number;
  duplicates_suppressed: number;
  duration_ms: number | null;
  projects_attempted: number;
  projects_with_recommendations: number;
  projects_reused: number;
  projects_using_fallback: number;
  project_failures: Record<string, string>;
};

export type GovernanceHealthProject = {
  project_id: string;
  project_name: string;
  score: number;
  risk_level: string;
  priority: number;
  blocking_dependencies: number;
  open_dependencies: number;
  open_escalations: number;
  critical_escalations: number;
  overdue_actions: number;
  pending_scope_revisions: number;
  delivery_confidence: number | null;
  delivery_traffic_light: string | null;
  quality_risk: string | null;
  workforce_risk: string | null;
  trend: string;
  vertical?: string | null;
  evidence: GovernanceAnalyticsEvidence[];
};

export type GovernanceChartPoint = {
  label: string;
  value: number;
  secondary_value: number | null;
};

export type GovernanceInsightsKpis = {
  portfolio_governance_score: number;
  projects_at_risk: number;
  recommendation_acceptance_rate_pct: number;
  recommendation_dismissal_rate_pct: number;
  escalations_created: number;
  recommendations_created: number;
  sla_adherence_pct: number;
};

export type GovernanceNamedCount = {
  label: string;
  count: number;
  project_id?: string | null;
  project_name?: string | null;
  vertical?: string | null;
  detail?: string | null;
};

export type GovernanceRiskHeatmapCell = {
  vertical: string;
  risk_level: string;
  project_count: number;
  avg_score: number;
};

export type GovernanceAnalytics = {
  generated_at: string;
  date_range_days: number;
  project_health: GovernanceHealthProject[];
  portfolio_risk_ranking: GovernanceHealthProject[];
  insights: GovernanceAnalyticsInsight[];
  recommendations: GovernanceAnalyticsRecommendation[];
  charts: Record<string, GovernanceChartPoint[]>;
  recent_activity: GovernanceAnalyticsEvidence[];
  export_sections: string[];
  portfolio_governance_score?: number | null;
  insights_kpis?: GovernanceInsightsKpis | null;
  top_governance_risks?: GovernanceNamedCount[];
  top_recurring_blockers?: GovernanceNamedCount[];
  top_recurring_mitigation_failures?: GovernanceNamedCount[];
  most_affected_projects?: GovernanceNamedCount[];
  most_affected_departments?: GovernanceNamedCount[];
  risk_heatmap?: GovernanceRiskHeatmapCell[];
};

export type GovernanceAnalyticsSummary = {
  generated_at: string;
  date_range_days: number;
  project_health: GovernanceHealthProject[];
  portfolio_risk_ranking: GovernanceHealthProject[];
  charts: Record<string, GovernanceChartPoint[]>;
  export_sections: string[];
  portfolio_governance_score?: number | null;
  insights_kpis?: GovernanceInsightsKpis | null;
};

export type GovernanceAnalyticsDetail = {
  generated_at: string;
  date_range_days: number;
  insights: GovernanceAnalyticsInsight[];
  recommendations: GovernanceAnalyticsRecommendation[];
  charts: Record<string, GovernanceChartPoint[]>;
  recent_activity: GovernanceAnalyticsEvidence[];
  export_sections: string[];
  insights_kpis?: GovernanceInsightsKpis | null;
  top_governance_risks?: GovernanceNamedCount[];
  top_recurring_blockers?: GovernanceNamedCount[];
  top_recurring_mitigation_failures?: GovernanceNamedCount[];
  most_affected_projects?: GovernanceNamedCount[];
  most_affected_departments?: GovernanceNamedCount[];
  risk_heatmap?: GovernanceRiskHeatmapCell[];
};

export type GovernanceEffectivenessMetric = {
  value: number | null;
  numerator: number;
  denominator: number;
  null_reason: string | null;
};

export type GovernanceEffectivenessSummary = {
  generated_at: string;
  date_range_days: number;
  total_recommendations: number;
  reviewed: number;
  pending: number;
  acceptance_rate: GovernanceEffectivenessMetric;
  dismissal_rate: GovernanceEffectivenessMetric;
  conversion_rate: GovernanceEffectivenessMetric;
  resolution_rate: GovernanceEffectivenessMetric;
  false_positive_rate: GovernanceEffectivenessMetric;
  average_quality_score: number | null;
  median_time_to_review_seconds: number | null;
  average_time_to_review_seconds: number | null;
  median_time_to_convert_seconds: number | null;
  average_time_to_convert_seconds: number | null;
  median_time_to_resolve_seconds: number | null;
  average_time_to_resolve_seconds: number | null;
  recurrence_after_acceptance: number;
  recurrence_after_dismissal: number;
  metric_version: string;
};

export type GovernanceEffectivenessFunnel = {
  created: number;
  reviewed: number;
  accepted: number;
  dismissed: number;
  converted: number;
  resolved: number;
};

export type GovernanceEffectivenessTrendPoint = {
  date: string;
  created: number;
  reviewed: number;
  accepted: number;
  dismissed: number;
  converted: number;
  resolved: number;
  false_positives: number;
  average_quality_score: number | null;
  recurrence_after_acceptance: number;
  recurrence_after_dismissal: number;
};

export type GovernanceEffectivenessCategoryStat = {
  category_key: string;
  trigger_type: string;
  severity: string;
  confidence_band: string;
  vertical: string;
  explanation_version: string;
  sample_size: number;
  acceptance_rate: GovernanceEffectivenessMetric;
  dismissal_rate: GovernanceEffectivenessMetric;
  conversion_rate: GovernanceEffectivenessMetric;
  resolution_rate: GovernanceEffectivenessMetric;
  false_positive_rate: GovernanceEffectivenessMetric;
  recurrence_after_acceptance: number;
  recurrence_after_dismissal: number;
  successful: boolean;
};

export type GovernanceEffectivenessFilters = {
  days?: number;
  projectId?: string | null;
  vertical?: string | null;
  triggerType?: string | null;
  strategyVersion?: string | null;
  qualityBand?: string | null;
  confidenceBand?: string | null;
  status?: string | null;
};

export type GovernanceLearningRule = {
  id: string;
  org_id: string;
  rule_type: string;
  rule_payload: Record<string, unknown>;
  version: number;
  status: string;
  evaluation_mode: string;
  change_summary: string | null;
  approved_at: string | null;
  activated_at: string | null;
  reverted_at: string | null;
  disabled_at: string | null;
  shadow_evaluation_id: string | null;
  created_at: string;
};

export type GovernanceOptimizationDriftAlert = {
  id?: string | null;
  alert_type: string;
  severity: string;
  metric_name: string;
  baseline_value: number | null;
  current_value: number | null;
  threshold_value: number | null;
  message: string;
  strategy_version?: string | null;
  created_at: string;
};

export type GovernanceOptimizationStrategy = {
  id: string;
  strategy_version: string;
  confidence_version: string;
  quality_version: string;
  explanation_version: string;
  learning_rule_version: string | null;
  is_active: boolean;
  change_summary: string | null;
  activated_at: string | null;
  created_at: string;
};

export type GovernanceOptimizationShadow = {
  id: string;
  learning_rule_id: string | null;
  status: string;
  sample_size: number;
  baseline_metrics: Record<string, unknown>;
  shadow_metrics: Record<string, unknown>;
  comparison_summary: Record<string, unknown>;
  expected_impact: Record<string, unknown>;
  started_at: string | null;
  completed_at: string | null;
  created_at: string;
};

export type GovernanceOptimizationReport = {
  id: string;
  period: string;
  period_start: string;
  period_end: string;
  strategy_version: string | null;
  report_payload: Record<string, unknown>;
  generated_at: string;
};

export type GovernanceOptimizationSummary = {
  generated_at: string;
  filters: Record<string, unknown>;
  metrics: Record<string, unknown>;
  active_learning_rules: GovernanceLearningRule[];
  pending_approvals: GovernanceLearningRule[];
  recent_shadow_evaluations: GovernanceOptimizationShadow[];
  drift_warnings: GovernanceOptimizationDriftAlert[];
  strategy_versions: GovernanceOptimizationStrategy[];
  recent_reports: GovernanceOptimizationReport[];
  learning_rules_enabled: boolean;
};

export type GovernanceOptimizationCompare = {
  strategy_a: string;
  strategy_b: string;
  days: number;
  metrics_a: Record<string, unknown>;
  metrics_b: Record<string, unknown>;
  deltas: Record<string, number | null>;
  generated_at: string;
};

/** Alias matching API response naming. */
export type GovernanceBootstrapResponse = GovernanceBootstrap;

export type ProjectDependencyUpdatePayload = {
  title?: string;
  description?: string | null;
  dependency_type?: GovernanceDependencyType;
  owner_id?: string | null;
  due_date?: string | null;
  status?: GovernanceDependencyStatus;
};

export type GovernanceEscalationUpdatePayload = {
  title?: string;
  description?: string | null;
  severity?: GovernanceEscalationSeverity;
  status?: GovernanceEscalationStatus;
  assigned_to?: string | null;
  source_type?: GovernanceEscalationSourceType | null;
  source_id?: string | null;
  client_summary?: string | null;
};

export type PublishClientEscalationSummaryPayload = {
  client_summary: string;
  client_visible?: boolean;
};

export type GovernanceActionUpdatePayload = {
  title?: string;
  description?: string | null;
  owner_id?: string | null;
  due_date?: string | null;
  status?: GovernanceActionStatus;
  linked_knowledge_document_id?: string | null;
};

export type ProjectDependencyCreatePayload = {
  title: string;
  description?: string | null;
  dependency_type: GovernanceDependencyType;
  owner_id?: string | null;
  due_date?: string | null;
  status?: GovernanceDependencyStatus;
};

export type GovernanceEscalationCreatePayload = {
  project_id: string;
  title: string;
  description?: string | null;
  severity?: GovernanceEscalationSeverity;
  status?: GovernanceEscalationStatus;
  assigned_to?: string | null;
  source_type?: GovernanceEscalationSourceType | null;
  source_id?: string | null;
};

export type GovernanceActionCreatePayload = {
  project_id: string;
  title: string;
  description?: string | null;
  owner_id?: string | null;
  due_date?: string | null;
  status?: GovernanceActionStatus;
  linked_knowledge_document_id?: string | null;
};

export type ConvertRecommendationToActionPayload = GovernanceActionCreatePayload & {
  suggested_action_index?: number | null;
  note?: string | null;
  idempotency_key?: string | null;
};

export type ConvertRecommendationToEscalationPayload = Omit<
  GovernanceEscalationCreatePayload,
  "source_type" | "source_id"
> & {
  suggested_action_index?: number | null;
  note?: string | null;
  idempotency_key?: string | null;
};

export type ProjectScopeStateUpdatePayload = {
  scope_status?: GovernanceScopeStatus;
  version_label?: string;
  notes?: string | null;
  linked_charter_document_id?: string | null;
};

export type ProjectCharterGeneratePayload = {
  project_id: string;
  visibility?: KnowledgeVisibility;
};

export type ProjectCharterUpdatePayload = {
  generated_text: string;
  visibility?: KnowledgeVisibility;
};
