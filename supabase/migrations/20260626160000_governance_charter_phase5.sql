-- Project Governance Agent — Phase 5: AI Project Charter Generation

CREATE TYPE governance_charter_status AS ENUM ('draft', 'approved', 'archived');

CREATE TABLE project_charters (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  org_id UUID NOT NULL REFERENCES organisations (id) ON DELETE RESTRICT,
  project_id UUID NOT NULL REFERENCES projects (id) ON DELETE CASCADE,
  version TEXT NOT NULL,
  status governance_charter_status NOT NULL DEFAULT 'draft',
  generated_text TEXT NOT NULL,
  generated_by_ai BOOLEAN NOT NULL DEFAULT true,
  previous_version_id UUID REFERENCES project_charters (id) ON DELETE SET NULL,
  knowledge_document_id UUID REFERENCES knowledge_documents (id) ON DELETE SET NULL,
  visibility knowledge_visibility NOT NULL DEFAULT 'internal_only',
  approved_by UUID REFERENCES users (id) ON DELETE SET NULL,
  approved_at TIMESTAMPTZ,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX project_charters_org_id_idx ON project_charters (org_id);
CREATE INDEX project_charters_project_id_idx ON project_charters (project_id, created_at DESC);
CREATE UNIQUE INDEX project_charters_project_version_key ON project_charters (project_id, version);

CREATE TRIGGER project_charters_updated_at
  BEFORE UPDATE ON project_charters
  FOR EACH ROW EXECUTE FUNCTION set_updated_at();

ALTER TYPE governance_evidence_source_type ADD VALUE IF NOT EXISTS 'weekly_summary';

ALTER TABLE governance_evidence_links
  ALTER COLUMN summary_id DROP NOT NULL;

ALTER TABLE governance_evidence_links
  ADD COLUMN charter_id UUID REFERENCES project_charters (id) ON DELETE CASCADE;

ALTER TABLE governance_evidence_links
  ADD CONSTRAINT governance_evidence_parent_check CHECK (
    (summary_id IS NOT NULL AND charter_id IS NULL)
    OR (summary_id IS NULL AND charter_id IS NOT NULL)
  );

CREATE INDEX governance_evidence_links_charter_idx ON governance_evidence_links (charter_id);

ALTER TABLE project_charters ENABLE ROW LEVEL SECURITY;

CREATE POLICY project_charters_dm_all ON project_charters FOR ALL TO public
  USING (public.auth_user_role() = 'delivery_manager' AND org_id = public.auth_user_org_id())
  WITH CHECK (public.auth_user_role() = 'delivery_manager' AND org_id = public.auth_user_org_id());

CREATE POLICY project_charters_leadership_select ON project_charters FOR SELECT TO public
  USING (
    public.auth_user_role() = 'bsg_leadership'
    AND status = 'approved'
  );

CREATE POLICY project_charters_client_select ON project_charters FOR SELECT TO public
  USING (
    public.auth_user_role() = 'client'
    AND org_id = public.auth_user_org_id()
    AND status = 'approved'
    AND visibility = 'client_safe'
    AND EXISTS (
      SELECT 1 FROM project_assignments pa
      WHERE pa.project_id = project_charters.project_id
        AND pa.user_id = public.current_user_id()
        AND pa.is_active = TRUE
        AND pa.deleted_at IS NULL
    )
  );

CREATE POLICY project_charters_super_admin_all ON project_charters FOR ALL TO public
  USING (public.auth_user_role() = 'super_admin')
  WITH CHECK (public.auth_user_role() = 'super_admin');

-- Extend evidence link policies (charter-backed links)
CREATE POLICY governance_evidence_links_charter_dm ON governance_evidence_links FOR ALL TO public
  USING (
    charter_id IS NOT NULL
    AND public.auth_user_role() = 'delivery_manager'
    AND org_id = public.auth_user_org_id()
  )
  WITH CHECK (
    charter_id IS NOT NULL
    AND public.auth_user_role() = 'delivery_manager'
    AND org_id = public.auth_user_org_id()
  );

CREATE POLICY governance_evidence_links_charter_leadership ON governance_evidence_links FOR SELECT TO public
  USING (charter_id IS NOT NULL AND public.auth_user_role() = 'bsg_leadership');

CREATE POLICY governance_evidence_links_charter_client ON governance_evidence_links FOR SELECT TO public
  USING (
    charter_id IS NOT NULL
    AND org_id = public.auth_user_org_id()
    AND public.auth_user_role() = 'client'
    AND EXISTS (
      SELECT 1
      FROM project_charters pc
      JOIN project_assignments pa ON pa.project_id = pc.project_id
      WHERE pc.id = governance_evidence_links.charter_id
        AND pc.status = 'approved'
        AND pc.visibility = 'client_safe'
        AND pa.user_id = public.current_user_id()
        AND pa.is_active = TRUE
        AND pa.deleted_at IS NULL
    )
  );

CREATE POLICY governance_evidence_links_charter_super_admin ON governance_evidence_links FOR ALL TO public
  USING (charter_id IS NOT NULL AND public.auth_user_role() = 'super_admin')
  WITH CHECK (charter_id IS NOT NULL AND public.auth_user_role() = 'super_admin');
