export type GovernanceEscalationSourceType = "delivery_risk" | "knowledge_document";

export type GovernanceScopeStatus = "approved" | "pending_revision" | "locked";
export type GovernanceDependencyType = "client_action" | "internal" | "external";
export type GovernanceDependencyStatus = "open" | "blocking" | "resolved";
export type GovernanceEscalationSeverity = "low" | "medium" | "high" | "critical";
export type GovernanceEscalationStatus = "open" | "in_progress" | "resolved";
export type GovernanceActionStatus = "open" | "in_progress" | "completed" | "overdue";
export type GovernanceSummaryStatus = "draft" | "approved";
export type GovernanceCharterStatus = "draft" | "approved" | "archived";
export type KnowledgeVisibility = "internal_only" | "leadership_only" | "client_safe";
export type GovernanceEvidenceSourceType =
  | "dependency"
  | "escalation"
  | "action"
  | "scope_state"
  | "knowledge_document"
  | "delivery_signal"
  | "weekly_summary";

export type GovernanceKpis = {
  open_actions: number;
  overdue_actions: number;
  open_escalations: number;
  blocking_dependencies: number;
  at_risk_items: number;
  sla_adherence_pct: number;
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
  approved_by_name?: string | null;
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
  visibility: KnowledgeVisibility;
  approved_by: string | null;
  approved_at: string | null;
  created_at: string;
  updated_at: string;
  evidence_links: GovernanceEvidenceLink[];
  approved_by_name?: string | null;
  project_name?: string | null;
};

export type GovernanceCharterReference = {
  document_id: string;
  title: string;
  project: string | null;
  version: string;
  status: string;
  visibility: string;
};

export type GovernanceBootstrap = {
  kpis: GovernanceKpis;
  dependencies: ProjectDependency[];
  escalations: GovernanceEscalation[];
  actions: GovernanceAction[];
  scope_states: ProjectScopeState[];
  charter_references: GovernanceCharterReference[];
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
  evidence: GovernanceAnalyticsEvidence[];
};

export type GovernanceChartPoint = {
  label: string;
  value: number;
  secondary_value: number | null;
};

export type GovernanceTrendPoint = {
  date: string;
  open_dependencies: number;
  resolved_dependencies: number;
  blocking_dependencies: number;
  escalations_created: number;
  escalations_resolved: number;
  critical_escalations: number;
  actions_created: number;
  actions_completed: number;
  overdue_actions: number;
  scope_revisions: number;
  scope_approvals: number;
  locked_scope: number;
  portfolio_health: number;
  sla_adherence_pct: number;
};

export type GovernanceAnalyticsKpis = {
  portfolio_score: number;
  projects_at_risk: number;
  leadership_attention_projects: number;
  blocking_dependencies: number;
  critical_escalations: number;
  pending_scope_approvals: number;
  upcoming_governance_meetings: number;
  governance_sla_pct: number;
  avg_dependency_resolution_days: number | null;
  avg_escalation_resolution_days: number | null;
  avg_action_completion_days: number | null;
  open_dependencies: number;
  open_actions: number;
  overdue_actions: number;
  projects_red: number;
  projects_amber: number;
  projects_green: number;
  weekly_trend: number;
  monthly_trend: number;
};

export type GovernanceAnalytics = {
  generated_at: string;
  date_range_days: number;
  kpis: GovernanceAnalyticsKpis;
  project_health: GovernanceHealthProject[];
  portfolio_risk_ranking: GovernanceHealthProject[];
  insights: GovernanceAnalyticsInsight[];
  recommendations: GovernanceAnalyticsRecommendation[];
  trends: GovernanceTrendPoint[];
  charts: Record<string, GovernanceChartPoint[]>;
  recent_activity: GovernanceAnalyticsEvidence[];
  export_sections: string[];
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

export type ProjectScopeStateUpdatePayload = {
  scope_status?: GovernanceScopeStatus;
  version_label?: string;
  notes?: string | null;
  linked_charter_document_id?: string | null;
};

export type GovernanceWeeklySummaryCreatePayload = {
  summary_week: string;
  summary_text: string;
  evidence_links?: Array<{
    source_type: GovernanceEvidenceSourceType;
    source_id: string;
  }>;
};

export type ProjectCharterGeneratePayload = {
  project_id: string;
  visibility?: KnowledgeVisibility;
};

export type ProjectCharterUpdatePayload = {
  generated_text: string;
  visibility?: KnowledgeVisibility;
};
