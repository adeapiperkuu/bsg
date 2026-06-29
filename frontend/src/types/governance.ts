export type GovernanceScopeStatus = "approved" | "pending_revision" | "locked";
export type GovernanceDependencyType = "client_action" | "internal" | "external";
export type GovernanceDependencyStatus = "open" | "blocking" | "resolved";
export type GovernanceEscalationSeverity = "low" | "medium" | "high" | "critical";
export type GovernanceEscalationStatus = "open" | "in_progress" | "resolved";
export type GovernanceActionStatus = "open" | "in_progress" | "completed" | "overdue";
export type GovernanceSummaryStatus = "draft" | "approved";
export type GovernanceEvidenceSourceType =
  | "dependency"
  | "escalation"
  | "action"
  | "scope_state"
  | "knowledge_document";

export type GovernanceKpis = {
  open_actions: number;
  overdue_actions: number;
  open_escalations: number;
  blocking_dependencies: number;
  at_risk_items: number;
  sla_adherence_pct: number;
};

export type ProjectScopeState = {
  id: string;
  org_id: string;
  project_id: string;
  scope_status: GovernanceScopeStatus;
  version_label: string;
  notes: string | null;
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
};

export type GovernanceEvidenceLink = {
  id: string;
  org_id: string;
  summary_id: string;
  source_type: GovernanceEvidenceSourceType;
  source_id: string;
  created_at: string;
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
};

export type GovernanceActionCreatePayload = {
  project_id: string;
  title: string;
  description?: string | null;
  owner_id?: string | null;
  due_date?: string | null;
  status?: GovernanceActionStatus;
};

export type ProjectScopeStateUpdatePayload = {
  scope_status?: GovernanceScopeStatus;
  version_label?: string;
  notes?: string | null;
};

export type GovernanceWeeklySummaryCreatePayload = {
  summary_week: string;
  summary_text: string;
  evidence_links?: Array<{
    source_type: GovernanceEvidenceSourceType;
    source_id: string;
  }>;
};
