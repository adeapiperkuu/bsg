-- Persisted knowledge gaps surfaced as library todos.

CREATE TYPE knowledge_gap_status AS ENUM ('open', 'resolved');

CREATE TABLE knowledge_gaps (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  org_id UUID NOT NULL REFERENCES organisations (id) ON DELETE RESTRICT,
  agent_query_id UUID REFERENCES agent_queries (id) ON DELETE SET NULL,
  query_text TEXT NOT NULL,
  message TEXT NOT NULL,
  suggested_title TEXT,
  suggested_source_type TEXT,
  suggested_folder_kind TEXT,
  status knowledge_gap_status NOT NULL DEFAULT 'open',
  resolved_at TIMESTAMPTZ,
  resolved_by UUID REFERENCES users (id) ON DELETE SET NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX knowledge_gaps_org_status_idx ON knowledge_gaps (org_id, status);
CREATE INDEX knowledge_gaps_query_idx ON knowledge_gaps (agent_query_id);

CREATE TRIGGER knowledge_gaps_updated_at
  BEFORE UPDATE ON knowledge_gaps
  FOR EACH ROW EXECUTE FUNCTION set_updated_at();

ALTER TABLE knowledge_gaps ENABLE ROW LEVEL SECURITY;

CREATE POLICY knowledge_gaps_read ON knowledge_gaps FOR SELECT TO public
  USING (
    public.auth_user_role() IN ('bsg_leadership', 'super_admin')
    OR org_id = public.auth_user_org_id()
  );

CREATE POLICY knowledge_gaps_insert ON knowledge_gaps FOR INSERT TO public
  WITH CHECK (
    org_id = public.auth_user_org_id()
    AND public.auth_user_role() IN ('delivery_manager', 'bsg_leadership', 'super_admin')
  );

CREATE POLICY knowledge_gaps_update ON knowledge_gaps FOR UPDATE TO public
  USING (
    org_id = public.auth_user_org_id()
    AND public.auth_user_role() IN ('delivery_manager', 'bsg_leadership', 'super_admin')
  )
  WITH CHECK (
    org_id = public.auth_user_org_id()
    AND public.auth_user_role() IN ('delivery_manager', 'bsg_leadership', 'super_admin')
  );

CREATE POLICY knowledge_gaps_super_admin_all ON knowledge_gaps FOR ALL TO public
  USING (public.auth_user_role() = 'super_admin')
  WITH CHECK (public.auth_user_role() = 'super_admin');
