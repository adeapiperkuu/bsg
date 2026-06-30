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
  weekly_summary: GovernanceWeeklySummary | null;
  charter_references: GovernanceCharterReference[];
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
