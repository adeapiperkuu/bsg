-- Targeted composite indexes for Workforce page / dashboard query patterns.
-- Skip indexes that already exist as single-column or near-equivalent composites.

-- Latest utilization per project/team (filters deleted rows + date order).
CREATE INDEX IF NOT EXISTS utilization_snapshots_project_team_annotator_deleted_date_idx
  ON utilization_snapshots (project_id, team_id, annotator_id, deleted_at, snapshot_date DESC);

-- Open/high-severity capability gap listing and detect flows.
CREATE INDEX IF NOT EXISTS capability_gaps_project_status_severity_deleted_idx
  ON capability_gaps (project_id, status, severity, deleted_at);

-- Recommendations joined to source workforce risks.
CREATE INDEX IF NOT EXISTS mitigation_recommendations_project_source_risk_deleted_idx
  ON mitigation_recommendations (project_id, source_risk_id, deleted_at);

-- Workforce imbalance risk lookups by project/type/status.
CREATE INDEX IF NOT EXISTS risk_alerts_project_type_status_deleted_idx
  ON risk_alerts (project_id, alert_type, status, deleted_at);

-- Active annotators by team (summary + matrix + training gaps).
CREATE INDEX IF NOT EXISTS annotators_team_active_deleted_idx
  ON annotators (team_id, is_active, deleted_at);

-- Skill requirements for a project (matrix build).
CREATE INDEX IF NOT EXISTS project_skill_requirements_project_deleted_idx
  ON project_skill_requirements (project_id, deleted_at);

-- Annotator skill assignments used by coverage counting.
CREATE INDEX IF NOT EXISTS annotator_skills_annotator_skill_deleted_idx
  ON annotator_skills (annotator_id, skill_id, deleted_at);
