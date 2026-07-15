-- Ensure Project Charter list hot paths have additive latency indexes.
-- Idempotent follow-up for environments missing the Phase 8 charter index.

CREATE INDEX IF NOT EXISTS project_charters_org_project_status_created_idx
  ON project_charters (org_id, project_id, status, created_at DESC);

CREATE INDEX IF NOT EXISTS project_charters_org_created_idx
  ON project_charters (org_id, created_at DESC);
