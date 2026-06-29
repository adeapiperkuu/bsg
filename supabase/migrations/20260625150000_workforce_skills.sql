CREATE TABLE skills (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  org_id UUID NOT NULL REFERENCES organisations (id) ON DELETE RESTRICT,
  name TEXT NOT NULL,
  category TEXT,
  domain TEXT,
  description TEXT,
  is_critical BOOLEAN NOT NULL DEFAULT false,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  deleted_at TIMESTAMPTZ
);

CREATE INDEX skills_org_id_idx ON skills (org_id);
CREATE INDEX skills_name_idx ON skills (name);

CREATE TRIGGER skills_updated_at
  BEFORE UPDATE ON skills
  FOR EACH ROW EXECUTE FUNCTION set_updated_at();

CREATE TABLE annotator_skills (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  org_id UUID NOT NULL REFERENCES organisations (id) ON DELETE RESTRICT,
  annotator_id UUID NOT NULL REFERENCES annotators (id) ON DELETE CASCADE,
  skill_id UUID NOT NULL REFERENCES skills (id) ON DELETE RESTRICT,
  proficiency_level TEXT NOT NULL CHECK (
    proficiency_level IN ('beginner', 'intermediate', 'advanced', 'expert')
  ),
  verified_by UUID REFERENCES users (id) ON DELETE SET NULL,
  verified_at TIMESTAMPTZ,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  deleted_at TIMESTAMPTZ
);

CREATE INDEX annotator_skills_org_id_idx ON annotator_skills (org_id);
CREATE INDEX annotator_skills_annotator_id_idx ON annotator_skills (annotator_id);
CREATE INDEX annotator_skills_skill_id_idx ON annotator_skills (skill_id);

CREATE UNIQUE INDEX annotator_skills_annotator_skill_active_key
  ON annotator_skills (annotator_id, skill_id)
  WHERE deleted_at IS NULL;

CREATE TRIGGER annotator_skills_updated_at
  BEFORE UPDATE ON annotator_skills
  FOR EACH ROW EXECUTE FUNCTION set_updated_at();

CREATE TABLE project_skill_requirements (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  org_id UUID NOT NULL REFERENCES organisations (id) ON DELETE RESTRICT,
  project_id UUID NOT NULL REFERENCES projects (id) ON DELETE CASCADE,
  skill_id UUID NOT NULL REFERENCES skills (id) ON DELETE RESTRICT,
  required_proficiency_level TEXT NOT NULL CHECK (
    required_proficiency_level IN ('beginner', 'intermediate', 'advanced', 'expert')
  ),
  required_headcount INTEGER NOT NULL DEFAULT 1 CHECK (required_headcount >= 0),
  required_sme_count INTEGER NOT NULL DEFAULT 0 CHECK (required_sme_count >= 0),
  priority TEXT NOT NULL DEFAULT 'medium' CHECK (
    priority IN ('low', 'medium', 'high', 'critical')
  ),
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  deleted_at TIMESTAMPTZ
);

CREATE INDEX project_skill_requirements_org_id_idx ON project_skill_requirements (org_id);
CREATE INDEX project_skill_requirements_project_id_idx ON project_skill_requirements (project_id);
CREATE INDEX project_skill_requirements_skill_id_idx ON project_skill_requirements (skill_id);

CREATE UNIQUE INDEX project_skill_requirements_project_skill_active_key
  ON project_skill_requirements (project_id, skill_id)
  WHERE deleted_at IS NULL;

CREATE TRIGGER project_skill_requirements_updated_at
  BEFORE UPDATE ON project_skill_requirements
  FOR EACH ROW EXECUTE FUNCTION set_updated_at();

ALTER TABLE skills ENABLE ROW LEVEL SECURITY;
ALTER TABLE annotator_skills ENABLE ROW LEVEL SECURITY;
ALTER TABLE project_skill_requirements ENABLE ROW LEVEL SECURITY;

CREATE POLICY skills_dm_all ON skills FOR ALL TO public
  USING (public.auth_user_role() = 'delivery_manager' AND org_id = public.auth_user_org_id())
  WITH CHECK (public.auth_user_role() = 'delivery_manager' AND org_id = public.auth_user_org_id());
CREATE POLICY skills_leadership_select ON skills FOR SELECT TO public
  USING (public.auth_user_role() = 'bsg_leadership' AND deleted_at IS NULL);
CREATE POLICY skills_super_admin_all ON skills FOR ALL TO public
  USING (public.auth_user_role() = 'super_admin') WITH CHECK (public.auth_user_role() = 'super_admin');

CREATE POLICY annotator_skills_dm_all ON annotator_skills FOR ALL TO public
  USING (public.auth_user_role() = 'delivery_manager' AND org_id = public.auth_user_org_id())
  WITH CHECK (public.auth_user_role() = 'delivery_manager' AND org_id = public.auth_user_org_id());
CREATE POLICY annotator_skills_leadership_select ON annotator_skills FOR SELECT TO public
  USING (public.auth_user_role() = 'bsg_leadership' AND deleted_at IS NULL);
CREATE POLICY annotator_skills_super_admin_all ON annotator_skills FOR ALL TO public
  USING (public.auth_user_role() = 'super_admin') WITH CHECK (public.auth_user_role() = 'super_admin');

CREATE POLICY project_skill_requirements_dm_all ON project_skill_requirements FOR ALL TO public
  USING (public.auth_user_role() = 'delivery_manager' AND org_id = public.auth_user_org_id())
  WITH CHECK (public.auth_user_role() = 'delivery_manager' AND org_id = public.auth_user_org_id());
CREATE POLICY project_skill_requirements_leadership_select ON project_skill_requirements FOR SELECT TO public
  USING (public.auth_user_role() = 'bsg_leadership' AND deleted_at IS NULL);
CREATE POLICY project_skill_requirements_super_admin_all ON project_skill_requirements FOR ALL TO public
  USING (public.auth_user_role() = 'super_admin') WITH CHECK (public.auth_user_role() = 'super_admin');
