CREATE TABLE IF NOT EXISTS project_assignments (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id UUID NOT NULL REFERENCES users (id) ON DELETE CASCADE,
  project_id UUID NOT NULL REFERENCES projects (id) ON DELETE CASCADE,
  org_id UUID NOT NULL REFERENCES organisations (id) ON DELETE RESTRICT,
  is_active BOOLEAN NOT NULL DEFAULT TRUE,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  deleted_at TIMESTAMPTZ,
  CONSTRAINT project_assignments_user_project_key UNIQUE (user_id, project_id)
);

CREATE INDEX IF NOT EXISTS project_assignments_user_id_idx ON project_assignments (user_id);
CREATE INDEX IF NOT EXISTS project_assignments_project_id_idx ON project_assignments (project_id);
CREATE INDEX IF NOT EXISTS project_assignments_org_id_idx ON project_assignments (org_id);

CREATE TRIGGER project_assignments_updated_at
BEFORE UPDATE ON project_assignments
FOR EACH ROW EXECUTE FUNCTION set_updated_at();

ALTER TABLE project_assignments ENABLE ROW LEVEL SECURITY;

CREATE POLICY project_assignments_own_select ON project_assignments FOR SELECT TO public
  USING (user_id = public.current_user_id() AND deleted_at IS NULL);

CREATE POLICY project_assignments_dm_all ON project_assignments FOR ALL TO public
  USING (public.auth_user_role() = 'delivery_manager' AND org_id = public.auth_user_org_id())
  WITH CHECK (public.auth_user_role() = 'delivery_manager' AND org_id = public.auth_user_org_id());

CREATE POLICY project_assignments_leadership_select ON project_assignments FOR SELECT TO public
  USING (public.auth_user_role() = 'bsg_leadership' AND deleted_at IS NULL);

CREATE POLICY project_assignments_super_admin_all ON project_assignments FOR ALL TO public
  USING (public.auth_user_role() = 'super_admin')
  WITH CHECK (public.auth_user_role() = 'super_admin');
