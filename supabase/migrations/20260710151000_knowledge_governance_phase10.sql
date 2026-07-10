CREATE OR REPLACE FUNCTION public.can_access_knowledge_visibility(item_visibility knowledge_visibility)
RETURNS boolean AS $$
  SELECT CASE
    WHEN public.auth_user_role() = 'super_admin' THEN true
    WHEN public.auth_user_role() = 'bsg_leadership' THEN item_visibility IN ('internal_only', 'leadership_only', 'restricted', 'client_safe')
    WHEN public.auth_user_role() = 'delivery_manager' THEN item_visibility IN ('internal_only', 'client_safe')
    WHEN public.auth_user_role() = 'client' THEN item_visibility = 'client_safe'
    ELSE false
  END
$$ LANGUAGE sql STABLE SECURITY DEFINER SET search_path = public;

ALTER TABLE knowledge_documents
  ADD COLUMN IF NOT EXISTS created_by UUID REFERENCES users (id) ON DELETE SET NULL,
  ADD COLUMN IF NOT EXISTS submitted_by UUID REFERENCES users (id) ON DELETE SET NULL,
  ADD COLUMN IF NOT EXISTS submitted_at TIMESTAMPTZ,
  ADD COLUMN IF NOT EXISTS reviewed_by UUID REFERENCES users (id) ON DELETE SET NULL,
  ADD COLUMN IF NOT EXISTS reviewed_at TIMESTAMPTZ,
  ADD COLUMN IF NOT EXISTS rejection_reason TEXT,
  ADD COLUMN IF NOT EXISTS expiry_date DATE;

UPDATE knowledge_documents
SET created_by = COALESCE(created_by, uploaded_by)
WHERE created_by IS NULL;

ALTER TABLE knowledge_document_versions
  ADD COLUMN IF NOT EXISTS supersedes_version_id UUID REFERENCES knowledge_document_versions (id) ON DELETE SET NULL,
  ADD COLUMN IF NOT EXISTS superseded_by_version_id UUID REFERENCES knowledge_document_versions (id) ON DELETE SET NULL,
  ADD COLUMN IF NOT EXISTS approved_by UUID REFERENCES users (id) ON DELETE SET NULL,
  ADD COLUMN IF NOT EXISTS approved_at TIMESTAMPTZ;

CREATE TABLE IF NOT EXISTS knowledge_document_approval_events (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  org_id UUID NOT NULL REFERENCES organisations (id) ON DELETE RESTRICT,
  document_id UUID NOT NULL REFERENCES knowledge_documents (id) ON DELETE CASCADE,
  actor_id UUID REFERENCES users (id) ON DELETE SET NULL,
  from_status TEXT,
  to_status TEXT NOT NULL,
  action TEXT NOT NULL,
  note TEXT,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS knowledge_document_approval_events_document_idx
  ON knowledge_document_approval_events (document_id, created_at);

CREATE INDEX IF NOT EXISTS knowledge_document_approval_events_org_idx
  ON knowledge_document_approval_events (org_id, created_at);

ALTER TABLE knowledge_document_approval_events ENABLE ROW LEVEL SECURITY;

CREATE POLICY knowledge_document_approval_events_read ON knowledge_document_approval_events FOR SELECT TO public
  USING (
    org_id = public.auth_user_org_id()
    AND public.auth_user_role() IN ('delivery_manager', 'bsg_leadership', 'super_admin')
  );

CREATE POLICY knowledge_document_approval_events_insert ON knowledge_document_approval_events FOR INSERT TO public
  WITH CHECK (
    org_id = public.auth_user_org_id()
    AND public.auth_user_role() IN ('delivery_manager', 'bsg_leadership', 'super_admin')
  );

CREATE POLICY knowledge_document_approval_events_super_admin_all ON knowledge_document_approval_events FOR ALL TO public
  USING (public.auth_user_role() = 'super_admin')
  WITH CHECK (public.auth_user_role() = 'super_admin');
