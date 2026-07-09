-- Speed up per-org stale-summary lookup for date-dependent register counts.
CREATE INDEX project_governance_summary_org_updated_idx
  ON project_governance_summary (org_id, updated_at);

-- Downgrade / rollback:
-- DROP INDEX IF EXISTS project_governance_summary_org_updated_idx;
