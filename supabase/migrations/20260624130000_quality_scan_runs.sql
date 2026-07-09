-- Persisted history for automated and manual quality scan runs
CREATE TABLE IF NOT EXISTS quality_scan_runs (
  id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  trigger             TEXT NOT NULL CHECK (trigger IN ('scheduler', 'manual')),
  triggered_by        UUID REFERENCES users(id) ON DELETE SET NULL,
  iso_year            INT NOT NULL,
  iso_week            INT NOT NULL,
  status              TEXT NOT NULL DEFAULT 'running'
                        CHECK (status IN ('running', 'completed', 'failed')),
  started_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
  finished_at         TIMESTAMPTZ,
  projects_scanned    INT NOT NULL DEFAULT 0,
  snapshots_evaluated INT NOT NULL DEFAULT 0,
  alerts_created      INT NOT NULL DEFAULT 0,
  data_gaps           INT NOT NULL DEFAULT 0,
  per_project_results JSONB,
  error_message       TEXT,
  created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at          TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS quality_scan_runs_started_idx ON quality_scan_runs (started_at DESC);

CREATE TRIGGER quality_scan_runs_updated_at
  BEFORE UPDATE ON quality_scan_runs
  FOR EACH ROW EXECUTE FUNCTION set_updated_at();

ALTER TABLE quality_scan_runs ENABLE ROW LEVEL SECURITY;
CREATE POLICY qsr_read ON quality_scan_runs FOR SELECT TO public USING (true);
CREATE POLICY qsr_super_admin_write ON quality_scan_runs FOR ALL TO public
  USING (current_setting('app.role', true) = 'super_admin')
  WITH CHECK (current_setting('app.role', true) = 'super_admin');
