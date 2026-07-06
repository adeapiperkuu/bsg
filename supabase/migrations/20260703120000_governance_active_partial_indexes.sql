-- Governance Phase 4 active-record partial indexes.
-- These are intentionally narrower than the existing broad deleted_at IS NULL indexes.
-- They target the hot dashboard/list/analytics paths that repeatedly read unresolved records.

CREATE INDEX IF NOT EXISTS project_dependencies_active_org_status_due_project_idx
    ON project_dependencies (org_id, status, due_date, project_id)
    WHERE deleted_at IS NULL
      AND status IN ('open', 'blocking');

CREATE INDEX IF NOT EXISTS project_dependencies_blocking_org_project_due_idx
    ON project_dependencies (org_id, project_id, due_date)
    WHERE deleted_at IS NULL
      AND status = 'blocking';

CREATE INDEX IF NOT EXISTS governance_actions_active_org_status_due_project_idx
    ON governance_actions (org_id, status, due_date, project_id)
    WHERE deleted_at IS NULL
      AND status IN ('open', 'in_progress', 'overdue');

CREATE INDEX IF NOT EXISTS governance_actions_active_due_org_project_idx
    ON governance_actions (org_id, due_date, project_id)
    WHERE deleted_at IS NULL
      AND status IN ('open', 'in_progress', 'overdue')
      AND due_date IS NOT NULL;

CREATE INDEX IF NOT EXISTS governance_escalations_active_org_status_raised_project_idx
    ON governance_escalations (org_id, status, raised_at DESC, project_id)
    WHERE deleted_at IS NULL
      AND status IN ('open', 'in_progress');

CREATE INDEX IF NOT EXISTS governance_escalations_critical_org_severity_raised_project_idx
    ON governance_escalations (org_id, severity, raised_at DESC, project_id)
    WHERE deleted_at IS NULL
      AND status IN ('open', 'in_progress')
      AND severity IN ('high', 'critical');

CREATE INDEX IF NOT EXISTS project_scope_states_pending_org_updated_project_idx
    ON project_scope_states (org_id, updated_at DESC, project_id)
    WHERE deleted_at IS NULL
      AND scope_status = 'pending_revision';

-- Downgrade / rollback:
-- DROP INDEX IF EXISTS project_scope_states_pending_org_updated_project_idx;
-- DROP INDEX IF EXISTS governance_escalations_critical_org_severity_raised_project_idx;
-- DROP INDEX IF EXISTS governance_escalations_active_org_status_raised_project_idx;
-- DROP INDEX IF EXISTS governance_actions_active_due_org_project_idx;
-- DROP INDEX IF EXISTS governance_actions_active_org_status_due_project_idx;
-- DROP INDEX IF EXISTS project_dependencies_blocking_org_project_due_idx;
-- DROP INDEX IF EXISTS project_dependencies_active_org_status_due_project_idx;
