-- Governance dependencies list endpoint: default sort + org-scoped count.
-- Targets GET /governance/dependencies?limit=50&offset=0 (ORDER BY due_date NULLS LAST, created_at DESC).

CREATE INDEX IF NOT EXISTS project_dependencies_active_org_due_created_idx
    ON project_dependencies (org_id, due_date NULLS LAST, created_at DESC)
    WHERE deleted_at IS NULL;

CREATE INDEX IF NOT EXISTS project_dependencies_active_org_id_idx
    ON project_dependencies (org_id)
    WHERE deleted_at IS NULL;

-- Downgrade / rollback:
-- DROP INDEX IF EXISTS project_dependencies_active_org_id_idx;
-- DROP INDEX IF EXISTS project_dependencies_active_org_due_created_idx;
