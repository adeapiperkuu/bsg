-- Project Governance Agent — dependencies and action register

ALTER TYPE alert_type ADD VALUE IF NOT EXISTS 'quality_escalation';
ALTER TYPE notification_type ADD VALUE IF NOT EXISTS 'skill_gap_detected';

CREATE TABLE project_dependencies (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  from_project_id UUID NOT NULL REFERENCES projects (id) ON DELETE CASCADE,
  to_project_id UUID NOT NULL REFERENCES projects (id) ON DELETE CASCADE,
  org_id UUID NOT NULL REFERENCES organisations (id) ON DELETE RESTRICT,
  dependency_type TEXT NOT NULL CHECK (dependency_type IN ('blocks', 'relates_to', 'feeds_into')),
  status TEXT NOT NULL DEFAULT 'open' CHECK (status IN ('open', 'in_progress', 'resolved', 'dismissed')),
  due_date DATE,
  notes TEXT,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  CONSTRAINT project_dependencies_no_self_ref CHECK (from_project_id <> to_project_id)
);

CREATE TABLE governance_actions (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  project_id UUID NOT NULL REFERENCES projects (id) ON DELETE CASCADE,
  org_id UUID NOT NULL REFERENCES organisations (id) ON DELETE RESTRICT,
  title TEXT NOT NULL,
  owner_id UUID REFERENCES users (id) ON DELETE SET NULL,
  due_date DATE,
  status TEXT NOT NULL DEFAULT 'open' CHECK (status IN ('open', 'in_progress', 'completed', 'cancelled')),
  priority TEXT NOT NULL DEFAULT 'medium' CHECK (priority IN ('low', 'medium', 'high', 'critical')),
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX project_dependencies_from_idx ON project_dependencies (from_project_id);
CREATE INDEX project_dependencies_to_idx ON project_dependencies (to_project_id);
CREATE INDEX project_dependencies_org_id_idx ON project_dependencies (org_id);
CREATE INDEX governance_actions_project_id_idx ON governance_actions (project_id);
CREATE INDEX governance_actions_org_id_idx ON governance_actions (org_id);

CREATE TRIGGER project_dependencies_updated_at BEFORE UPDATE ON project_dependencies FOR EACH ROW EXECUTE FUNCTION set_updated_at();
CREATE TRIGGER governance_actions_updated_at BEFORE UPDATE ON governance_actions FOR EACH ROW EXECUTE FUNCTION set_updated_at();

ALTER TABLE project_dependencies ENABLE ROW LEVEL SECURITY;
ALTER TABLE governance_actions ENABLE ROW LEVEL SECURITY;

CREATE POLICY project_deps_client_select ON project_dependencies FOR SELECT TO public
  USING (public.auth_user_role() = 'client' AND org_id = public.auth_user_org_id());
CREATE POLICY project_deps_dm_all ON project_dependencies FOR ALL TO public
  USING (public.auth_user_role() = 'delivery_manager' AND org_id = public.auth_user_org_id())
  WITH CHECK (public.auth_user_role() = 'delivery_manager' AND org_id = public.auth_user_org_id());
CREATE POLICY project_deps_leadership_select ON project_dependencies FOR SELECT TO public
  USING (public.auth_user_role() = 'bsg_leadership');
CREATE POLICY project_deps_super_admin_select ON project_dependencies FOR SELECT TO public
  USING (public.auth_user_role() = 'super_admin');

CREATE POLICY governance_actions_client_select ON governance_actions FOR SELECT TO public
  USING (public.auth_user_role() = 'client' AND org_id = public.auth_user_org_id());
CREATE POLICY governance_actions_dm_all ON governance_actions FOR ALL TO public
  USING (public.auth_user_role() = 'delivery_manager' AND org_id = public.auth_user_org_id())
  WITH CHECK (public.auth_user_role() = 'delivery_manager' AND org_id = public.auth_user_org_id());
CREATE POLICY governance_actions_leadership_select ON governance_actions FOR SELECT TO public
  USING (public.auth_user_role() = 'bsg_leadership');
CREATE POLICY governance_actions_super_admin_select ON governance_actions FOR SELECT TO public
  USING (public.auth_user_role() = 'super_admin');
