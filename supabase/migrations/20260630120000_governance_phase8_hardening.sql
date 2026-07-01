-- Phase 8 governance hardening indexes.
-- These target the dashboard/bootstrap, analytics, audit, and chatbot monitoring paths.

CREATE INDEX IF NOT EXISTS project_dependencies_org_status_due_idx
    ON project_dependencies (org_id, status, due_date)
    WHERE deleted_at IS NULL;

CREATE INDEX IF NOT EXISTS project_dependencies_org_project_status_idx
    ON project_dependencies (org_id, project_id, status)
    WHERE deleted_at IS NULL;

CREATE INDEX IF NOT EXISTS governance_escalations_org_project_status_severity_idx
    ON governance_escalations (org_id, project_id, status, severity)
    WHERE deleted_at IS NULL;

CREATE INDEX IF NOT EXISTS governance_escalations_org_raised_at_idx
    ON governance_escalations (org_id, raised_at DESC)
    WHERE deleted_at IS NULL;

CREATE INDEX IF NOT EXISTS governance_actions_org_project_status_due_idx
    ON governance_actions (org_id, project_id, status, due_date)
    WHERE deleted_at IS NULL;

CREATE INDEX IF NOT EXISTS governance_actions_org_completed_at_idx
    ON governance_actions (org_id, completed_at DESC)
    WHERE deleted_at IS NULL;

CREATE INDEX IF NOT EXISTS project_scope_states_org_project_status_idx
    ON project_scope_states (org_id, project_id, scope_status)
    WHERE deleted_at IS NULL;

CREATE INDEX IF NOT EXISTS project_charters_org_project_status_created_idx
    ON project_charters (org_id, project_id, status, created_at DESC);

CREATE INDEX IF NOT EXISTS agent_queries_governance_org_created_idx
    ON agent_queries (org_id, agent_name, created_at DESC)
    WHERE agent_name = 'project_governance_agent';

CREATE INDEX IF NOT EXISTS audit_logs_governance_org_created_idx
    ON audit_logs (org_id, created_at DESC)
    WHERE event_type LIKE 'governance.%';
