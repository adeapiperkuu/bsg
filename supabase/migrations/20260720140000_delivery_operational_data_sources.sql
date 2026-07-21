-- Delivery Performance Agent Phase 15.2: operational data sources for root-cause inputs.
-- Deterministic signals only; AI must not read these tables directly for invention.

-- Composite FKs require unique (id, org_id) / (id, project_id, org_id). Idempotent if
-- Phase 2 (team throughput) already created these indexes.
CREATE UNIQUE INDEX IF NOT EXISTS projects_id_org_uidx
  ON projects (id, org_id);

CREATE UNIQUE INDEX IF NOT EXISTS teams_id_project_org_uidx
  ON teams (id, project_id, org_id);

CREATE TYPE operational_data_source_type AS ENUM (
  'manual',
  'import',
  'event',
  'derived',
  'correction'
);

-- Daily timesheet hours attributed to a project team.
CREATE TABLE delivery_timesheet_entries (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  org_id UUID NOT NULL,
  project_id UUID NOT NULL,
  team_id UUID NOT NULL,
  snapshot_date DATE NOT NULL,
  hours_logged NUMERIC(8, 2) NOT NULL CHECK (hours_logged >= 0),
  expected_hours NUMERIC(8, 2) CHECK (expected_hours IS NULL OR expected_hours >= 0),
  source_type operational_data_source_type NOT NULL DEFAULT 'manual',
  source_reference TEXT CHECK (char_length(source_reference) <= 500),
  notes TEXT CHECK (char_length(notes) <= 2000),
  created_by UUID REFERENCES users (id) ON DELETE SET NULL,
  updated_by UUID REFERENCES users (id) ON DELETE SET NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  CONSTRAINT delivery_timesheet_entries_org_project_team_date_key
    UNIQUE (org_id, project_id, team_id, snapshot_date),
  CONSTRAINT delivery_timesheet_entries_project_org_fkey
    FOREIGN KEY (project_id, org_id) REFERENCES projects (id, org_id) ON DELETE CASCADE,
  CONSTRAINT delivery_timesheet_entries_team_project_org_fkey
    FOREIGN KEY (team_id, project_id, org_id)
    REFERENCES teams (id, project_id, org_id) ON DELETE RESTRICT
);

CREATE INDEX delivery_timesheet_entries_org_project_date_idx
  ON delivery_timesheet_entries (org_id, project_id, snapshot_date DESC);

CREATE TRIGGER delivery_timesheet_entries_updated_at
  BEFORE UPDATE ON delivery_timesheet_entries
  FOR EACH ROW EXECUTE FUNCTION set_updated_at();

-- Project-day absenteeism pressure.
CREATE TABLE delivery_absenteeism_snapshots (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  org_id UUID NOT NULL,
  project_id UUID NOT NULL,
  snapshot_date DATE NOT NULL,
  absent_fte NUMERIC(8, 2) NOT NULL CHECK (absent_fte >= 0),
  planned_fte NUMERIC(8, 2) NOT NULL CHECK (planned_fte > 0),
  absence_rate_pct NUMERIC(5, 2) NOT NULL
    CHECK (absence_rate_pct >= 0 AND absence_rate_pct <= 100),
  source_type operational_data_source_type NOT NULL DEFAULT 'manual',
  source_reference TEXT CHECK (char_length(source_reference) <= 500),
  notes TEXT CHECK (char_length(notes) <= 2000),
  created_by UUID REFERENCES users (id) ON DELETE SET NULL,
  updated_by UUID REFERENCES users (id) ON DELETE SET NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  CONSTRAINT delivery_absenteeism_snapshots_project_date_key
    UNIQUE (project_id, snapshot_date),
  CONSTRAINT delivery_absenteeism_snapshots_project_org_fkey
    FOREIGN KEY (project_id, org_id) REFERENCES projects (id, org_id) ON DELETE CASCADE
);

CREATE INDEX delivery_absenteeism_snapshots_org_date_idx
  ON delivery_absenteeism_snapshots (org_id, snapshot_date DESC);

CREATE TRIGGER delivery_absenteeism_snapshots_updated_at
  BEFORE UPDATE ON delivery_absenteeism_snapshots
  FOR EACH ROW EXECUTE FUNCTION set_updated_at();

-- Review queue metrics (feeds review_turnaround root cause).
CREATE TABLE delivery_review_queue_snapshots (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  org_id UUID NOT NULL,
  project_id UUID NOT NULL,
  snapshot_date DATE NOT NULL,
  pending_count INTEGER NOT NULL CHECK (pending_count >= 0),
  avg_turnaround_hours NUMERIC(8, 2) NOT NULL CHECK (avg_turnaround_hours >= 0),
  sla_breach_count INTEGER NOT NULL DEFAULT 0 CHECK (sla_breach_count >= 0),
  source_type operational_data_source_type NOT NULL DEFAULT 'manual',
  source_reference TEXT CHECK (char_length(source_reference) <= 500),
  notes TEXT CHECK (char_length(notes) <= 2000),
  created_by UUID REFERENCES users (id) ON DELETE SET NULL,
  updated_by UUID REFERENCES users (id) ON DELETE SET NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  CONSTRAINT delivery_review_queue_snapshots_project_date_key
    UNIQUE (project_id, snapshot_date),
  CONSTRAINT delivery_review_queue_snapshots_project_org_fkey
    FOREIGN KEY (project_id, org_id) REFERENCES projects (id, org_id) ON DELETE CASCADE
);

CREATE INDEX delivery_review_queue_snapshots_org_date_idx
  ON delivery_review_queue_snapshots (org_id, snapshot_date DESC);

CREATE TRIGGER delivery_review_queue_snapshots_updated_at
  BEFORE UPDATE ON delivery_review_queue_snapshots
  FOR EACH ROW EXECUTE FUNCTION set_updated_at();

-- Backlog queue analytics (feeds queue / backlog congestion).
CREATE TABLE delivery_backlog_queue_snapshots (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  org_id UUID NOT NULL,
  project_id UUID NOT NULL,
  snapshot_date DATE NOT NULL,
  item_count INTEGER NOT NULL CHECK (item_count >= 0),
  aging_item_count INTEGER NOT NULL DEFAULT 0 CHECK (aging_item_count >= 0),
  oldest_item_age_days INTEGER NOT NULL DEFAULT 0 CHECK (oldest_item_age_days >= 0),
  source_type operational_data_source_type NOT NULL DEFAULT 'manual',
  source_reference TEXT CHECK (char_length(source_reference) <= 500),
  notes TEXT CHECK (char_length(notes) <= 2000),
  created_by UUID REFERENCES users (id) ON DELETE SET NULL,
  updated_by UUID REFERENCES users (id) ON DELETE SET NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  CONSTRAINT delivery_backlog_queue_snapshots_project_date_key
    UNIQUE (project_id, snapshot_date),
  CONSTRAINT delivery_backlog_queue_aging_lte_items
    CHECK (aging_item_count <= item_count),
  CONSTRAINT delivery_backlog_queue_snapshots_project_org_fkey
    FOREIGN KEY (project_id, org_id) REFERENCES projects (id, org_id) ON DELETE CASCADE
);

CREATE INDEX delivery_backlog_queue_snapshots_org_date_idx
  ON delivery_backlog_queue_snapshots (org_id, snapshot_date DESC);

CREATE TRIGGER delivery_backlog_queue_snapshots_updated_at
  BEFORE UPDATE ON delivery_backlog_queue_snapshots
  FOR EACH ROW EXECUTE FUNCTION set_updated_at();

-- Capacity snapshots (feeds capacity shortage).
CREATE TABLE delivery_capacity_snapshots (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  org_id UUID NOT NULL,
  project_id UUID NOT NULL,
  snapshot_date DATE NOT NULL,
  planned_capacity_hours NUMERIC(10, 2) NOT NULL CHECK (planned_capacity_hours > 0),
  available_capacity_hours NUMERIC(10, 2) NOT NULL CHECK (available_capacity_hours >= 0),
  source_type operational_data_source_type NOT NULL DEFAULT 'manual',
  source_reference TEXT CHECK (char_length(source_reference) <= 500),
  notes TEXT CHECK (char_length(notes) <= 2000),
  created_by UUID REFERENCES users (id) ON DELETE SET NULL,
  updated_by UUID REFERENCES users (id) ON DELETE SET NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  CONSTRAINT delivery_capacity_snapshots_project_date_key
    UNIQUE (project_id, snapshot_date),
  CONSTRAINT delivery_capacity_snapshots_project_org_fkey
    FOREIGN KEY (project_id, org_id) REFERENCES projects (id, org_id) ON DELETE CASCADE
);

CREATE INDEX delivery_capacity_snapshots_org_date_idx
  ON delivery_capacity_snapshots (org_id, snapshot_date DESC);

CREATE TRIGGER delivery_capacity_snapshots_updated_at
  BEFORE UPDATE ON delivery_capacity_snapshots
  FOR EACH ROW EXECUTE FUNCTION set_updated_at();

-- Team availability history (feeds capacity / availability pressure).
CREATE TABLE delivery_team_availability_snapshots (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  org_id UUID NOT NULL,
  project_id UUID NOT NULL,
  team_id UUID NOT NULL,
  snapshot_date DATE NOT NULL,
  available_headcount INTEGER NOT NULL CHECK (available_headcount >= 0),
  planned_headcount INTEGER NOT NULL CHECK (planned_headcount > 0),
  available_fte NUMERIC(8, 2) CHECK (available_fte IS NULL OR available_fte >= 0),
  source_type operational_data_source_type NOT NULL DEFAULT 'manual',
  source_reference TEXT CHECK (char_length(source_reference) <= 500),
  notes TEXT CHECK (char_length(notes) <= 2000),
  created_by UUID REFERENCES users (id) ON DELETE SET NULL,
  updated_by UUID REFERENCES users (id) ON DELETE SET NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  CONSTRAINT delivery_team_availability_snapshots_org_project_team_date_key
    UNIQUE (org_id, project_id, team_id, snapshot_date),
  CONSTRAINT delivery_team_availability_snapshots_project_org_fkey
    FOREIGN KEY (project_id, org_id) REFERENCES projects (id, org_id) ON DELETE CASCADE,
  CONSTRAINT delivery_team_availability_snapshots_team_project_org_fkey
    FOREIGN KEY (team_id, project_id, org_id)
    REFERENCES teams (id, project_id, org_id) ON DELETE RESTRICT
);

CREATE INDEX delivery_team_availability_snapshots_org_project_date_idx
  ON delivery_team_availability_snapshots (org_id, project_id, snapshot_date DESC);

CREATE TRIGGER delivery_team_availability_snapshots_updated_at
  BEFORE UPDATE ON delivery_team_availability_snapshots
  FOR EACH ROW EXECUTE FUNCTION set_updated_at();

-- RLS: internal operational tables — no client policies.
DO $$
DECLARE
  tbl text;
BEGIN
  FOREACH tbl IN ARRAY ARRAY[
    'delivery_timesheet_entries',
    'delivery_absenteeism_snapshots',
    'delivery_review_queue_snapshots',
    'delivery_backlog_queue_snapshots',
    'delivery_capacity_snapshots',
    'delivery_team_availability_snapshots'
  ]
  LOOP
    EXECUTE format('ALTER TABLE %I ENABLE ROW LEVEL SECURITY', tbl);
    EXECUTE format(
      'CREATE POLICY %I ON %I FOR ALL TO public
         USING (
           public.auth_user_role() = ''delivery_manager''
           AND org_id = public.auth_user_org_id()
         )
         WITH CHECK (
           public.auth_user_role() = ''delivery_manager''
           AND org_id = public.auth_user_org_id()
         )',
      tbl || '_dm_all', tbl
    );
    EXECUTE format(
      'CREATE POLICY %I ON %I FOR SELECT TO public
         USING (
           public.auth_user_role() = ''bsg_leadership''
           AND org_id = public.auth_user_org_id()
         )',
      tbl || '_leadership_select', tbl
    );
    EXECUTE format(
      'CREATE POLICY %I ON %I FOR ALL TO public
         USING (public.auth_user_role() = ''super_admin'')
         WITH CHECK (public.auth_user_role() = ''super_admin'')',
      tbl || '_super_admin_all', tbl
    );
  END LOOP;
END $$;

COMMENT ON TABLE delivery_timesheet_entries IS
  'Phase 15.2 daily timesheet hours for Delivery root-cause inputs.';
COMMENT ON TABLE delivery_absenteeism_snapshots IS
  'Phase 15.2 project-day absenteeism rates for Delivery root-cause inputs.';
COMMENT ON TABLE delivery_review_queue_snapshots IS
  'Phase 15.2 review queue metrics for Delivery root-cause inputs.';
COMMENT ON TABLE delivery_backlog_queue_snapshots IS
  'Phase 15.2 backlog queue analytics for Delivery root-cause inputs.';
COMMENT ON TABLE delivery_capacity_snapshots IS
  'Phase 15.2 capacity planned vs available for Delivery root-cause inputs.';
COMMENT ON TABLE delivery_team_availability_snapshots IS
  'Phase 15.2 team availability history for Delivery root-cause inputs.';
