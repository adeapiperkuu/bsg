-- Governance latency sprint indexes for lazy table endpoints and recent activity lookups.

CREATE INDEX IF NOT EXISTS project_dependencies_org_created_deleted_idx
    ON project_dependencies (org_id, created_at DESC, deleted_at);

CREATE INDEX IF NOT EXISTS project_dependencies_project_status_due_deleted_idx
    ON project_dependencies (project_id, status, due_date, deleted_at);

CREATE INDEX IF NOT EXISTS governance_actions_org_created_deleted_idx
    ON governance_actions (org_id, created_at DESC, deleted_at);

CREATE INDEX IF NOT EXISTS governance_actions_project_status_due_deleted_idx
    ON governance_actions (project_id, status, due_date, deleted_at);

CREATE INDEX IF NOT EXISTS governance_escalations_org_created_deleted_idx
    ON governance_escalations (org_id, created_at DESC, deleted_at);

CREATE INDEX IF NOT EXISTS governance_escalations_project_status_created_deleted_idx
    ON governance_escalations (project_id, status, created_at DESC, deleted_at);

CREATE INDEX IF NOT EXISTS project_scope_states_org_created_deleted_idx
    ON project_scope_states (org_id, created_at DESC, deleted_at);

CREATE INDEX IF NOT EXISTS project_scope_states_project_status_deleted_idx
    ON project_scope_states (project_id, scope_status, deleted_at);
