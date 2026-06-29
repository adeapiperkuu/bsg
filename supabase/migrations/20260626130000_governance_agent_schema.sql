-- Project Governance Agent — Phase 1 schema

CREATE TYPE governance_scope_status AS ENUM ('approved', 'pending_revision', 'locked');
CREATE TYPE governance_dependency_type AS ENUM ('client_action', 'internal', 'external');
CREATE TYPE governance_dependency_status AS ENUM ('open', 'blocking', 'resolved');
CREATE TYPE governance_escalation_severity AS ENUM ('low', 'medium', 'high', 'critical');
CREATE TYPE governance_escalation_status AS ENUM ('open', 'in_progress', 'resolved');
CREATE TYPE governance_action_status AS ENUM ('open', 'in_progress', 'completed', 'overdue');
CREATE TYPE governance_summary_status AS ENUM ('draft', 'approved');
CREATE TYPE governance_evidence_source_type AS ENUM (
  'dependency',
  'escalation',
  'action',
  'scope_state',
  'knowledge_document'
);

CREATE TABLE project_scope_states (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  org_id UUID NOT NULL REFERENCES organisations (id) ON DELETE RESTRICT,
  project_id UUID NOT NULL REFERENCES projects (id) ON DELETE CASCADE,
  scope_status governance_scope_status NOT NULL DEFAULT 'approved',
  version_label TEXT NOT NULL DEFAULT 'v1',
  notes TEXT,
  created_by UUID REFERENCES users (id) ON DELETE SET NULL,
  updated_by UUID REFERENCES users (id) ON DELETE SET NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  deleted_at TIMESTAMPTZ
);

CREATE INDEX project_scope_states_org_id_idx ON project_scope_states (org_id);
CREATE INDEX project_scope_states_project_id_idx ON project_scope_states (project_id);

CREATE UNIQUE INDEX project_scope_states_project_active_key
  ON project_scope_states (project_id)
  WHERE deleted_at IS NULL;

CREATE TRIGGER project_scope_states_updated_at
  BEFORE UPDATE ON project_scope_states
  FOR EACH ROW EXECUTE FUNCTION set_updated_at();

CREATE TABLE project_dependencies (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  org_id UUID NOT NULL REFERENCES organisations (id) ON DELETE RESTRICT,
  project_id UUID NOT NULL REFERENCES projects (id) ON DELETE CASCADE,
  title TEXT NOT NULL,
  description TEXT,
  dependency_type governance_dependency_type NOT NULL,
  owner_id UUID REFERENCES users (id) ON DELETE SET NULL,
  due_date DATE,
  status governance_dependency_status NOT NULL DEFAULT 'open',
  resolved_at TIMESTAMPTZ,
  resolved_by UUID REFERENCES users (id) ON DELETE SET NULL,
  created_by UUID REFERENCES users (id) ON DELETE SET NULL,
  updated_by UUID REFERENCES users (id) ON DELETE SET NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  deleted_at TIMESTAMPTZ
);

CREATE INDEX project_dependencies_org_id_idx ON project_dependencies (org_id);
CREATE INDEX project_dependencies_project_id_idx ON project_dependencies (project_id);
CREATE INDEX project_dependencies_status_idx ON project_dependencies (org_id, status);

CREATE TRIGGER project_dependencies_updated_at
  BEFORE UPDATE ON project_dependencies
  FOR EACH ROW EXECUTE FUNCTION set_updated_at();

CREATE TABLE governance_escalations (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  org_id UUID NOT NULL REFERENCES organisations (id) ON DELETE RESTRICT,
  project_id UUID NOT NULL REFERENCES projects (id) ON DELETE CASCADE,
  title TEXT NOT NULL,
  description TEXT,
  severity governance_escalation_severity NOT NULL DEFAULT 'medium',
  status governance_escalation_status NOT NULL DEFAULT 'open',
  raised_by UUID REFERENCES users (id) ON DELETE SET NULL,
  assigned_to UUID REFERENCES users (id) ON DELETE SET NULL,
  raised_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  resolved_at TIMESTAMPTZ,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  deleted_at TIMESTAMPTZ
);

CREATE INDEX governance_escalations_org_id_idx ON governance_escalations (org_id);
CREATE INDEX governance_escalations_project_id_idx ON governance_escalations (project_id);
CREATE INDEX governance_escalations_status_idx ON governance_escalations (org_id, status);

CREATE TRIGGER governance_escalations_updated_at
  BEFORE UPDATE ON governance_escalations
  FOR EACH ROW EXECUTE FUNCTION set_updated_at();

CREATE TABLE governance_actions (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  org_id UUID NOT NULL REFERENCES organisations (id) ON DELETE RESTRICT,
  project_id UUID NOT NULL REFERENCES projects (id) ON DELETE CASCADE,
  title TEXT NOT NULL,
  description TEXT,
  owner_id UUID REFERENCES users (id) ON DELETE SET NULL,
  due_date DATE,
  status governance_action_status NOT NULL DEFAULT 'open',
  completed_at TIMESTAMPTZ,
  created_by UUID REFERENCES users (id) ON DELETE SET NULL,
  updated_by UUID REFERENCES users (id) ON DELETE SET NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  deleted_at TIMESTAMPTZ
);

CREATE INDEX governance_actions_org_id_idx ON governance_actions (org_id);
CREATE INDEX governance_actions_project_id_idx ON governance_actions (project_id);
CREATE INDEX governance_actions_status_idx ON governance_actions (org_id, status);
CREATE INDEX governance_actions_due_date_idx ON governance_actions (org_id, due_date);

CREATE TRIGGER governance_actions_updated_at
  BEFORE UPDATE ON governance_actions
  FOR EACH ROW EXECUTE FUNCTION set_updated_at();

CREATE TABLE governance_weekly_summaries (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  org_id UUID NOT NULL REFERENCES organisations (id) ON DELETE RESTRICT,
  summary_week DATE NOT NULL,
  summary_text TEXT NOT NULL,
  status governance_summary_status NOT NULL DEFAULT 'draft',
  generated_by_ai BOOLEAN NOT NULL DEFAULT false,
  approved_by UUID REFERENCES users (id) ON DELETE SET NULL,
  approved_at TIMESTAMPTZ,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX governance_weekly_summaries_org_id_idx ON governance_weekly_summaries (org_id);
CREATE INDEX governance_weekly_summaries_week_idx ON governance_weekly_summaries (org_id, summary_week DESC);

CREATE TRIGGER governance_weekly_summaries_updated_at
  BEFORE UPDATE ON governance_weekly_summaries
  FOR EACH ROW EXECUTE FUNCTION set_updated_at();

CREATE TABLE governance_evidence_links (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  org_id UUID NOT NULL REFERENCES organisations (id) ON DELETE RESTRICT,
  summary_id UUID NOT NULL REFERENCES governance_weekly_summaries (id) ON DELETE CASCADE,
  source_type governance_evidence_source_type NOT NULL,
  source_id UUID NOT NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX governance_evidence_links_summary_idx ON governance_evidence_links (summary_id);
CREATE INDEX governance_evidence_links_org_idx ON governance_evidence_links (org_id);

-- RLS
ALTER TABLE project_scope_states ENABLE ROW LEVEL SECURITY;
ALTER TABLE project_dependencies ENABLE ROW LEVEL SECURITY;
ALTER TABLE governance_escalations ENABLE ROW LEVEL SECURITY;
ALTER TABLE governance_actions ENABLE ROW LEVEL SECURITY;
ALTER TABLE governance_weekly_summaries ENABLE ROW LEVEL SECURITY;
ALTER TABLE governance_evidence_links ENABLE ROW LEVEL SECURITY;

-- project_scope_states
CREATE POLICY project_scope_states_dm_all ON project_scope_states FOR ALL TO public
  USING (public.auth_user_role() = 'delivery_manager' AND org_id = public.auth_user_org_id())
  WITH CHECK (public.auth_user_role() = 'delivery_manager' AND org_id = public.auth_user_org_id());
CREATE POLICY project_scope_states_leadership_select ON project_scope_states FOR SELECT TO public
  USING (public.auth_user_role() = 'bsg_leadership' AND deleted_at IS NULL);
CREATE POLICY project_scope_states_super_admin_all ON project_scope_states FOR ALL TO public
  USING (public.auth_user_role() = 'super_admin') WITH CHECK (public.auth_user_role() = 'super_admin');

-- project_dependencies (no client access)
CREATE POLICY project_dependencies_dm_all ON project_dependencies FOR ALL TO public
  USING (public.auth_user_role() = 'delivery_manager' AND org_id = public.auth_user_org_id())
  WITH CHECK (public.auth_user_role() = 'delivery_manager' AND org_id = public.auth_user_org_id());
CREATE POLICY project_dependencies_leadership_select ON project_dependencies FOR SELECT TO public
  USING (public.auth_user_role() = 'bsg_leadership' AND deleted_at IS NULL);
CREATE POLICY project_dependencies_super_admin_all ON project_dependencies FOR ALL TO public
  USING (public.auth_user_role() = 'super_admin') WITH CHECK (public.auth_user_role() = 'super_admin');

-- governance_escalations
CREATE POLICY governance_escalations_dm_all ON governance_escalations FOR ALL TO public
  USING (public.auth_user_role() = 'delivery_manager' AND org_id = public.auth_user_org_id())
  WITH CHECK (public.auth_user_role() = 'delivery_manager' AND org_id = public.auth_user_org_id());
CREATE POLICY governance_escalations_leadership_select ON governance_escalations FOR SELECT TO public
  USING (public.auth_user_role() = 'bsg_leadership' AND deleted_at IS NULL);
CREATE POLICY governance_escalations_client_select ON governance_escalations FOR SELECT TO public
  USING (
    public.auth_user_role() = 'client'
    AND org_id = public.auth_user_org_id()
    AND deleted_at IS NULL
    AND EXISTS (
      SELECT 1 FROM project_assignments pa
      WHERE pa.project_id = governance_escalations.project_id
        AND pa.user_id = public.current_user_id()
        AND pa.is_active = TRUE
        AND pa.deleted_at IS NULL
    )
  );
CREATE POLICY governance_escalations_super_admin_all ON governance_escalations FOR ALL TO public
  USING (public.auth_user_role() = 'super_admin') WITH CHECK (public.auth_user_role() = 'super_admin');

-- governance_actions (no client access)
CREATE POLICY governance_actions_dm_all ON governance_actions FOR ALL TO public
  USING (public.auth_user_role() = 'delivery_manager' AND org_id = public.auth_user_org_id())
  WITH CHECK (public.auth_user_role() = 'delivery_manager' AND org_id = public.auth_user_org_id());
CREATE POLICY governance_actions_leadership_select ON governance_actions FOR SELECT TO public
  USING (public.auth_user_role() = 'bsg_leadership' AND deleted_at IS NULL);
CREATE POLICY governance_actions_super_admin_all ON governance_actions FOR ALL TO public
  USING (public.auth_user_role() = 'super_admin') WITH CHECK (public.auth_user_role() = 'super_admin');

-- governance_weekly_summaries (clients: approved only via app layer; no client RLS policy)
CREATE POLICY governance_weekly_summaries_dm_all ON governance_weekly_summaries FOR ALL TO public
  USING (public.auth_user_role() = 'delivery_manager' AND org_id = public.auth_user_org_id())
  WITH CHECK (public.auth_user_role() = 'delivery_manager' AND org_id = public.auth_user_org_id());
CREATE POLICY governance_weekly_summaries_leadership_select ON governance_weekly_summaries FOR SELECT TO public
  USING (public.auth_user_role() = 'bsg_leadership');
CREATE POLICY governance_weekly_summaries_super_admin_all ON governance_weekly_summaries FOR ALL TO public
  USING (public.auth_user_role() = 'super_admin') WITH CHECK (public.auth_user_role() = 'super_admin');

-- governance_evidence_links
CREATE POLICY governance_evidence_links_dm_all ON governance_evidence_links FOR ALL TO public
  USING (public.auth_user_role() = 'delivery_manager' AND org_id = public.auth_user_org_id())
  WITH CHECK (public.auth_user_role() = 'delivery_manager' AND org_id = public.auth_user_org_id());
CREATE POLICY governance_evidence_links_leadership_select ON governance_evidence_links FOR SELECT TO public
  USING (public.auth_user_role() = 'bsg_leadership');
CREATE POLICY governance_evidence_links_super_admin_all ON governance_evidence_links FOR ALL TO public
  USING (public.auth_user_role() = 'super_admin') WITH CHECK (public.auth_user_role() = 'super_admin');
