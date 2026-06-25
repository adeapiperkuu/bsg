-- Workforce & Capability Agent — skills and utilization

CREATE TABLE workforce_skills (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  annotator_id UUID NOT NULL REFERENCES annotators (id) ON DELETE CASCADE,
  org_id UUID NOT NULL REFERENCES organisations (id) ON DELETE RESTRICT,
  skill_code TEXT NOT NULL,
  proficiency_level TEXT NOT NULL CHECK (proficiency_level IN ('beginner', 'intermediate', 'advanced', 'expert')),
  certified_at TIMESTAMPTZ,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  CONSTRAINT workforce_skills_annotator_skill_key UNIQUE (annotator_id, skill_code)
);

CREATE TABLE workforce_utilization_snapshots (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  team_id UUID NOT NULL REFERENCES teams (id) ON DELETE CASCADE,
  org_id UUID NOT NULL REFERENCES organisations (id) ON DELETE RESTRICT,
  iso_year INT NOT NULL CHECK (iso_year >= 2024),
  iso_week INT NOT NULL CHECK (iso_week BETWEEN 1 AND 53),
  target_hours NUMERIC(6, 2) NOT NULL CHECK (target_hours >= 0),
  logged_hours NUMERIC(6, 2) NOT NULL CHECK (logged_hours >= 0),
  utilization_pct NUMERIC(5, 2) CHECK (utilization_pct >= 0),
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  CONSTRAINT workforce_utilization_team_week_key UNIQUE (team_id, iso_year, iso_week)
);

CREATE INDEX workforce_skills_annotator_id_idx ON workforce_skills (annotator_id);
CREATE INDEX workforce_skills_org_id_idx ON workforce_skills (org_id);
CREATE INDEX workforce_utilization_team_id_idx ON workforce_utilization_snapshots (team_id);
CREATE INDEX workforce_utilization_org_id_idx ON workforce_utilization_snapshots (org_id);

CREATE TRIGGER workforce_skills_updated_at BEFORE UPDATE ON workforce_skills FOR EACH ROW EXECUTE FUNCTION set_updated_at();
CREATE TRIGGER workforce_utilization_updated_at BEFORE UPDATE ON workforce_utilization_snapshots FOR EACH ROW EXECUTE FUNCTION set_updated_at();

ALTER TABLE workforce_skills ENABLE ROW LEVEL SECURITY;
ALTER TABLE workforce_utilization_snapshots ENABLE ROW LEVEL SECURITY;

CREATE POLICY workforce_skills_dm_all ON workforce_skills FOR ALL TO public
  USING (public.auth_user_role() = 'delivery_manager' AND org_id = public.auth_user_org_id())
  WITH CHECK (public.auth_user_role() = 'delivery_manager' AND org_id = public.auth_user_org_id());
CREATE POLICY workforce_skills_leadership_select ON workforce_skills FOR SELECT TO public
  USING (public.auth_user_role() = 'bsg_leadership');
CREATE POLICY workforce_skills_super_admin_select ON workforce_skills FOR SELECT TO public
  USING (public.auth_user_role() = 'super_admin');

CREATE POLICY workforce_util_dm_all ON workforce_utilization_snapshots FOR ALL TO public
  USING (public.auth_user_role() = 'delivery_manager' AND org_id = public.auth_user_org_id())
  WITH CHECK (public.auth_user_role() = 'delivery_manager' AND org_id = public.auth_user_org_id());
CREATE POLICY workforce_util_leadership_select ON workforce_utilization_snapshots FOR SELECT TO public
  USING (public.auth_user_role() = 'bsg_leadership');
CREATE POLICY workforce_util_super_admin_select ON workforce_utilization_snapshots FOR SELECT TO public
  USING (public.auth_user_role() = 'super_admin');
