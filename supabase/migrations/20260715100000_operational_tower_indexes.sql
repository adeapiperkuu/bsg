-- Composite indexes for the Operational Tower dashboard query patterns.
-- delivery_confidence_scores already has single-column indexes on project_id and
-- milestone_id; these add the created_at ordering the dashboard actually filters and
-- ranks on, so the newest rows can be found without sorting the whole per-project set.

-- Risk trend: scores for the portfolio over the last N weeks (project_id + created_at range).
CREATE INDEX IF NOT EXISTS delivery_confidence_scores_project_created_idx
  ON delivery_confidence_scores (project_id, created_at DESC);

-- Upcoming milestones: latest score per milestone (row_number partitioned by milestone_id,
-- ordered by created_at DESC).
CREATE INDEX IF NOT EXISTS delivery_confidence_scores_milestone_created_idx
  ON delivery_confidence_scores (milestone_id, created_at DESC);

-- Open risk alerts per project. Resolves the TODO(perf) in
-- app/agents/delivery/services/dashboard_service.py: risk_alerts only had project_id and
-- an (project_id, alert_type, status, deleted_at) composite, neither of which serves the
-- alert_type-agnostic (project_id, status, deleted_at) filter used by the tower and by
-- _fetch_open_risks_by_project.
CREATE INDEX IF NOT EXISTS risk_alerts_project_status_deleted_idx
  ON risk_alerts (project_id, status, deleted_at);

-- Quality trend: the tower resolves the most recent iso weeks for a set of projects, then
-- reads only those weeks. quality_snapshots_project_id_idx alone cannot serve the week
-- ordering; quality_snapshots_week_idx cannot serve the project filter.
CREATE INDEX IF NOT EXISTS quality_snapshots_project_week_idx
  ON quality_snapshots (project_id, iso_year DESC, iso_week DESC);
