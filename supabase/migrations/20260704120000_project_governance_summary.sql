-- Phase E: precomputed per-project governance counts for the register tab.

CREATE TABLE project_governance_summary (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  org_id UUID NOT NULL REFERENCES organisations (id) ON DELETE RESTRICT,
  project_id UUID NOT NULL REFERENCES projects (id) ON DELETE CASCADE,
  open_dependencies_count INTEGER NOT NULL DEFAULT 0,
  blocked_dependencies_count INTEGER NOT NULL DEFAULT 0,
  blocking_overdue_dependencies_count INTEGER NOT NULL DEFAULT 0,
  open_actions_count INTEGER NOT NULL DEFAULT 0,
  overdue_actions_count INTEGER NOT NULL DEFAULT 0,
  open_escalations_count INTEGER NOT NULL DEFAULT 0,
  critical_escalations_count INTEGER NOT NULL DEFAULT 0,
  pending_scope_changes_count INTEGER NOT NULL DEFAULT 0,
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE UNIQUE INDEX project_governance_summary_org_project_key
  ON project_governance_summary (org_id, project_id);

CREATE INDEX project_governance_summary_org_id_idx
  ON project_governance_summary (org_id);

CREATE INDEX project_governance_summary_project_id_idx
  ON project_governance_summary (project_id);

CREATE TRIGGER project_governance_summary_updated_at
  BEFORE UPDATE ON project_governance_summary
  FOR EACH ROW EXECUTE FUNCTION set_updated_at();

-- Backfill from live governance tables (same rules as register grouped subqueries).
INSERT INTO project_governance_summary (
  org_id,
  project_id,
  open_dependencies_count,
  blocked_dependencies_count,
  blocking_overdue_dependencies_count,
  open_actions_count,
  overdue_actions_count,
  open_escalations_count,
  critical_escalations_count,
  pending_scope_changes_count
)
SELECT
  p.org_id,
  p.id,
  COALESCE(dep.open_dependencies_count, 0),
  COALESCE(dep.blocked_dependencies_count, 0),
  COALESCE(dep.blocking_overdue_dependencies_count, 0),
  COALESCE(act.open_actions_count, 0),
  COALESCE(act.overdue_actions_count, 0),
  COALESCE(esc.open_escalations_count, 0),
  COALESCE(esc.critical_escalations_count, 0),
  COALESCE(scope.pending_scope_changes_count, 0)
FROM projects p
LEFT JOIN (
  SELECT
    project_id,
    COUNT(*) FILTER (
      WHERE status IN ('open', 'blocking')
    ) AS open_dependencies_count,
    COUNT(*) FILTER (
      WHERE status = 'blocking'
    ) AS blocked_dependencies_count,
    COUNT(*) FILTER (
      WHERE status = 'blocking'
        AND due_date IS NOT NULL
        AND due_date < CURRENT_DATE
    ) AS blocking_overdue_dependencies_count
  FROM project_dependencies
  WHERE deleted_at IS NULL
  GROUP BY project_id
) dep ON dep.project_id = p.id
LEFT JOIN (
  SELECT
    project_id,
    COUNT(*) FILTER (
      WHERE status IN ('open', 'in_progress', 'overdue')
        OR (
          status != 'completed'
          AND due_date IS NOT NULL
          AND due_date < CURRENT_DATE
        )
    ) AS open_actions_count,
    COUNT(*) FILTER (
      WHERE status = 'overdue'
        OR (
          status != 'completed'
          AND due_date IS NOT NULL
          AND due_date < CURRENT_DATE
        )
    ) AS overdue_actions_count
  FROM governance_actions
  WHERE deleted_at IS NULL
  GROUP BY project_id
) act ON act.project_id = p.id
LEFT JOIN (
  SELECT
    project_id,
    COUNT(*) FILTER (
      WHERE status IN ('open', 'in_progress')
    ) AS open_escalations_count,
    COUNT(*) FILTER (
      WHERE status IN ('open', 'in_progress')
        AND severity = 'critical'
    ) AS critical_escalations_count
  FROM governance_escalations
  WHERE deleted_at IS NULL
  GROUP BY project_id
) esc ON esc.project_id = p.id
LEFT JOIN (
  SELECT
    project_id,
    COUNT(*) FILTER (
      WHERE scope_status = 'pending_revision'
    ) AS pending_scope_changes_count
  FROM project_scope_states
  WHERE deleted_at IS NULL
  GROUP BY project_id
) scope ON scope.project_id = p.id
ON CONFLICT (org_id, project_id) DO NOTHING;

-- Downgrade / rollback:
-- DROP TRIGGER IF EXISTS project_governance_summary_updated_at ON project_governance_summary;
-- DROP TABLE IF EXISTS project_governance_summary;
