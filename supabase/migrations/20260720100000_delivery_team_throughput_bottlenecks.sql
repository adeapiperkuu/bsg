-- Delivery Performance Agent Phase 2: deterministic team throughput and bottlenecks.
-- Existing project throughput, bottlenecks, and historical scores are preserved.

CREATE TYPE team_throughput_source_type AS ENUM (
  'manual',
  'import',
  'event',
  'derived',
  'correction'
);

CREATE TYPE bottleneck_source_type AS ENUM ('manual', 'detector');

-- PostgreSQL requires referenced column groups to be unique. These indexes are
-- additive and let the snapshot table enforce tenant/project/team consistency.
CREATE UNIQUE INDEX IF NOT EXISTS projects_id_org_uidx
  ON projects (id, org_id);

CREATE UNIQUE INDEX IF NOT EXISTS teams_id_project_org_uidx
  ON teams (id, project_id, org_id);

CREATE TABLE team_throughput_snapshots (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  org_id UUID NOT NULL,
  project_id UUID NOT NULL,
  team_id UUID NOT NULL,
  snapshot_date DATE NOT NULL,
  units_completed INTEGER NOT NULL CHECK (units_completed >= 0),
  active_headcount INTEGER CHECK (active_headcount >= 0),
  source_type team_throughput_source_type NOT NULL,
  source_reference TEXT CHECK (char_length(source_reference) <= 500),
  notes TEXT CHECK (char_length(notes) <= 2000),
  created_by UUID REFERENCES users (id) ON DELETE SET NULL,
  updated_by UUID REFERENCES users (id) ON DELETE SET NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  CONSTRAINT team_throughput_snapshots_org_project_team_date_key
    UNIQUE (org_id, project_id, team_id, snapshot_date),
  CONSTRAINT team_throughput_snapshots_project_org_fkey
    FOREIGN KEY (project_id, org_id)
    REFERENCES projects (id, org_id) ON DELETE CASCADE,
  CONSTRAINT team_throughput_snapshots_team_project_org_fkey
    FOREIGN KEY (team_id, project_id, org_id)
    REFERENCES teams (id, project_id, org_id) ON DELETE RESTRICT
);

CREATE INDEX team_throughput_snapshots_org_project_date_idx
  ON team_throughput_snapshots (org_id, project_id, snapshot_date DESC);

CREATE INDEX team_throughput_snapshots_org_project_team_date_idx
  ON team_throughput_snapshots (org_id, project_id, team_id, snapshot_date DESC);

CREATE INDEX team_throughput_snapshots_org_date_idx
  ON team_throughput_snapshots (org_id, snapshot_date DESC);

CREATE TRIGGER team_throughput_snapshots_updated_at
  BEFORE UPDATE ON team_throughput_snapshots
  FOR EACH ROW EXECUTE FUNCTION set_updated_at();

ALTER TABLE team_throughput_snapshots ENABLE ROW LEVEL SECURITY;

CREATE POLICY team_throughput_snapshots_dm_all
  ON team_throughput_snapshots FOR ALL TO public
  USING (
    public.auth_user_role() = 'delivery_manager'
    AND org_id = public.auth_user_org_id()
  )
  WITH CHECK (
    public.auth_user_role() = 'delivery_manager'
    AND org_id = public.auth_user_org_id()
    AND EXISTS (
      SELECT 1 FROM projects p
      WHERE p.id = project_id AND p.org_id = org_id AND p.deleted_at IS NULL
    )
    AND EXISTS (
      SELECT 1 FROM teams t
      WHERE t.id = team_id
        AND t.project_id = project_id
        AND t.org_id = org_id
        AND t.deleted_at IS NULL
    )
  );

CREATE POLICY team_throughput_snapshots_leadership_select
  ON team_throughput_snapshots FOR SELECT TO public
  USING (
    public.auth_user_role() = 'bsg_leadership'
    AND org_id = public.auth_user_org_id()
  );

CREATE POLICY team_throughput_snapshots_super_admin_all
  ON team_throughput_snapshots FOR ALL TO public
  USING (public.auth_user_role() = 'super_admin')
  WITH CHECK (public.auth_user_role() = 'super_admin');

ALTER TABLE bottlenecks
  ADD COLUMN IF NOT EXISTS severity risk_tier NOT NULL DEFAULT 'medium',
  ADD COLUMN IF NOT EXISTS source_type bottleneck_source_type,
  ADD COLUMN IF NOT EXISTS source_key TEXT,
  ADD COLUMN IF NOT EXISTS detector_version TEXT,
  ADD COLUMN IF NOT EXISTS evidence_json JSONB,
  ADD COLUMN IF NOT EXISTS first_detected_at TIMESTAMPTZ,
  ADD COLUMN IF NOT EXISTS last_detected_at TIMESTAMPTZ,
  ADD COLUMN IF NOT EXISTS acknowledged_at TIMESTAMPTZ,
  ADD COLUMN IF NOT EXISTS acknowledged_by UUID REFERENCES users (id) ON DELETE SET NULL,
  ADD COLUMN IF NOT EXISTS acknowledgement_note TEXT,
  ADD COLUMN IF NOT EXISTS resolution_reason TEXT,
  ADD COLUMN IF NOT EXISTS recovery_started_at TIMESTAMPTZ,
  ADD COLUMN IF NOT EXISTS last_evidence_hash TEXT,
  ADD COLUMN IF NOT EXISTS occurrence_count INTEGER NOT NULL DEFAULT 1
    CHECK (occurrence_count >= 1);

CREATE UNIQUE INDEX IF NOT EXISTS bottlenecks_detector_source_active_uidx
  ON bottlenecks (source_key)
  WHERE source_key IS NOT NULL AND deleted_at IS NULL;

CREATE INDEX IF NOT EXISTS bottlenecks_org_project_status_idx
  ON bottlenecks (org_id, project_id, status);

DROP POLICY IF EXISTS bottlenecks_leadership_select ON bottlenecks;
CREATE POLICY bottlenecks_leadership_select ON bottlenecks FOR SELECT TO public
  USING (
    public.auth_user_role() = 'bsg_leadership'
    AND org_id = public.auth_user_org_id()
  );

DROP POLICY IF EXISTS bottlenecks_super_admin_select ON bottlenecks;
CREATE POLICY bottlenecks_super_admin_all ON bottlenecks FOR ALL TO public
  USING (public.auth_user_role() = 'super_admin')
  WITH CHECK (public.auth_user_role() = 'super_admin');

-- Add detector defaults without replacing any explicit global or org values.
UPDATE metric_configurations
SET threshold_config = jsonb_build_object(
  'observation_days', 5,
  'decline_threshold_pct', 20,
  'recovery_days', 3,
  'historical_window_days', 14,
  'minimum_history_days', 5,
  'minimum_project_units', 1,
  'headcount_tolerance_pct', 5,
  'stale_after_days', 2,
  'maximum_history_days', 90,
  'require_headcount', true,
  'severity_medium_pct', 35,
  'severity_high_pct', 50,
  'severity_critical_pct', 70
) || COALESCE(threshold_config, '{}'::jsonb)
WHERE metric_key = 'delivery_bottleneck'
  AND deleted_at IS NULL;

COMMENT ON TABLE team_throughput_snapshots IS
  'Daily non-cumulative delivery units attributed to a project team.';

COMMENT ON COLUMN team_throughput_snapshots.snapshot_date IS
  'Logical reporting date. Organisation timezone is used upstream when available; UTC is the fallback.';
