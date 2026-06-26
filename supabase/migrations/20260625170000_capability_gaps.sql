CREATE TABLE capability_gaps (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  org_id UUID NOT NULL REFERENCES organisations (id) ON DELETE RESTRICT,
  project_id UUID NOT NULL REFERENCES projects (id) ON DELETE CASCADE,
  team_id UUID REFERENCES teams (id) ON DELETE SET NULL,
  skill_id UUID REFERENCES skills (id) ON DELETE SET NULL,
  gap_type TEXT NOT NULL CHECK (
    gap_type IN (
      'skill_shortage',
      'sme_shortage',
      'certification_gap',
      'training_gap',
      'utilization_overload',
      'utilization_underload'
    )
  ),
  severity TEXT NOT NULL CHECK (severity IN ('low', 'medium', 'high', 'critical')),
  title TEXT NOT NULL,
  detail TEXT NOT NULL,
  evidence JSONB,
  status TEXT NOT NULL DEFAULT 'open' CHECK (
    status IN ('open', 'acknowledged', 'resolved', 'dismissed')
  ),
  detected_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  resolved_at TIMESTAMPTZ,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  deleted_at TIMESTAMPTZ
);

CREATE INDEX capability_gaps_org_id_idx ON capability_gaps (org_id);
CREATE INDEX capability_gaps_project_id_idx ON capability_gaps (project_id);
CREATE INDEX capability_gaps_team_id_idx ON capability_gaps (team_id);
CREATE INDEX capability_gaps_skill_id_idx ON capability_gaps (skill_id);
CREATE INDEX capability_gaps_gap_type_idx ON capability_gaps (gap_type);
CREATE INDEX capability_gaps_severity_idx ON capability_gaps (severity);
CREATE INDEX capability_gaps_status_idx ON capability_gaps (status);
CREATE INDEX capability_gaps_detected_at_idx ON capability_gaps (detected_at);

CREATE UNIQUE INDEX capability_gaps_open_dedupe_key
  ON capability_gaps (
    project_id,
    gap_type,
    COALESCE(team_id, '00000000-0000-0000-0000-000000000000'::uuid),
    COALESCE(skill_id, '00000000-0000-0000-0000-000000000000'::uuid)
  )
  WHERE deleted_at IS NULL AND status IN ('open', 'acknowledged');

CREATE TRIGGER capability_gaps_updated_at
  BEFORE UPDATE ON capability_gaps
  FOR EACH ROW EXECUTE FUNCTION set_updated_at();

ALTER TABLE capability_gaps ENABLE ROW LEVEL SECURITY;

CREATE POLICY capability_gaps_dm_all ON capability_gaps FOR ALL TO public
  USING (public.auth_user_role() = 'delivery_manager' AND org_id = public.auth_user_org_id())
  WITH CHECK (public.auth_user_role() = 'delivery_manager' AND org_id = public.auth_user_org_id());
CREATE POLICY capability_gaps_leadership_select ON capability_gaps FOR SELECT TO public
  USING (public.auth_user_role() = 'bsg_leadership' AND deleted_at IS NULL);
CREATE POLICY capability_gaps_super_admin_all ON capability_gaps FOR ALL TO public
  USING (public.auth_user_role() = 'super_admin') WITH CHECK (public.auth_user_role() = 'super_admin');
