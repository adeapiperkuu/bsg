CREATE TABLE utilization_snapshots (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  org_id UUID NOT NULL REFERENCES organisations (id) ON DELETE RESTRICT,
  project_id UUID NOT NULL REFERENCES projects (id) ON DELETE CASCADE,
  team_id UUID REFERENCES teams (id) ON DELETE SET NULL,
  annotator_id UUID REFERENCES annotators (id) ON DELETE SET NULL,
  snapshot_date DATE NOT NULL,
  allocated_hours NUMERIC(10, 2) NOT NULL CHECK (allocated_hours >= 0),
  available_hours NUMERIC(10, 2) NOT NULL CHECK (available_hours >= 0),
  utilization_pct NUMERIC(7, 2) NOT NULL CHECK (utilization_pct >= 0),
  billable_hours NUMERIC(10, 2) CHECK (billable_hours >= 0),
  non_billable_hours NUMERIC(10, 2) CHECK (non_billable_hours >= 0),
  notes TEXT,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  deleted_at TIMESTAMPTZ,
  CONSTRAINT utilization_snapshots_annotator_requires_team CHECK (annotator_id IS NULL OR team_id IS NOT NULL)
);

CREATE INDEX utilization_snapshots_org_id_idx ON utilization_snapshots (org_id);
CREATE INDEX utilization_snapshots_project_id_idx ON utilization_snapshots (project_id);
CREATE INDEX utilization_snapshots_team_id_idx ON utilization_snapshots (team_id);
CREATE INDEX utilization_snapshots_annotator_id_idx ON utilization_snapshots (annotator_id);
CREATE INDEX utilization_snapshots_snapshot_date_idx ON utilization_snapshots (snapshot_date);
CREATE INDEX utilization_snapshots_project_id_date_idx ON utilization_snapshots (project_id, snapshot_date DESC);
CREATE INDEX utilization_snapshots_team_id_date_idx ON utilization_snapshots (team_id, snapshot_date DESC);

CREATE TRIGGER utilization_snapshots_updated_at
  BEFORE UPDATE ON utilization_snapshots
  FOR EACH ROW EXECUTE FUNCTION set_updated_at();

ALTER TABLE utilization_snapshots ENABLE ROW LEVEL SECURITY;

CREATE POLICY utilization_snapshots_dm_all ON utilization_snapshots FOR ALL TO public
  USING (public.auth_user_role() = 'delivery_manager' AND org_id = public.auth_user_org_id())
  WITH CHECK (public.auth_user_role() = 'delivery_manager' AND org_id = public.auth_user_org_id());
CREATE POLICY utilization_snapshots_leadership_select ON utilization_snapshots FOR SELECT TO public
  USING (public.auth_user_role() = 'bsg_leadership' AND deleted_at IS NULL);
CREATE POLICY utilization_snapshots_super_admin_all ON utilization_snapshots FOR ALL TO public
  USING (public.auth_user_role() = 'super_admin') WITH CHECK (public.auth_user_role() = 'super_admin');
