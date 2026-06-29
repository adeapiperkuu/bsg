-- Knowledge agent feedback loop: user ratings tied to agent_queries for eval datasets.

CREATE TYPE knowledge_feedback_rating AS ENUM ('up', 'down');

ALTER TABLE agent_queries
  ADD COLUMN retrieval_params JSONB;

CREATE TABLE knowledge_query_feedback (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  org_id UUID NOT NULL REFERENCES organisations (id) ON DELETE RESTRICT,
  agent_query_id UUID NOT NULL REFERENCES agent_queries (id) ON DELETE CASCADE,
  user_id UUID NOT NULL REFERENCES users (id) ON DELETE RESTRICT,
  rating knowledge_feedback_rating NOT NULL,
  comment TEXT,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  CONSTRAINT knowledge_query_feedback_query_user_key UNIQUE (agent_query_id, user_id)
);

CREATE INDEX knowledge_query_feedback_org_idx ON knowledge_query_feedback (org_id);
CREATE INDEX knowledge_query_feedback_query_idx ON knowledge_query_feedback (agent_query_id);
CREATE INDEX knowledge_query_feedback_rating_idx ON knowledge_query_feedback (org_id, rating);

CREATE TRIGGER knowledge_query_feedback_updated_at
  BEFORE UPDATE ON knowledge_query_feedback
  FOR EACH ROW EXECUTE FUNCTION set_updated_at();

ALTER TABLE knowledge_query_feedback ENABLE ROW LEVEL SECURITY;

CREATE POLICY knowledge_feedback_read ON knowledge_query_feedback FOR SELECT TO public
  USING (
    public.auth_user_role() IN ('bsg_leadership', 'super_admin')
    OR (org_id = public.auth_user_org_id() AND user_id = public.current_user_id())
  );

CREATE POLICY knowledge_feedback_insert ON knowledge_query_feedback FOR INSERT TO public
  WITH CHECK (
    org_id = public.auth_user_org_id()
    AND user_id = public.current_user_id()
    AND public.auth_user_role() IN ('delivery_manager', 'bsg_leadership', 'super_admin')
    AND EXISTS (
      SELECT 1
      FROM agent_queries aq
      WHERE aq.id = agent_query_id
        AND aq.org_id = public.auth_user_org_id()
        AND aq.agent_name = 'operational_knowledge_agent'
    )
  );

CREATE POLICY knowledge_feedback_update ON knowledge_query_feedback FOR UPDATE TO public
  USING (
    org_id = public.auth_user_org_id()
    AND user_id = public.current_user_id()
    AND public.auth_user_role() IN ('delivery_manager', 'bsg_leadership', 'super_admin')
  )
  WITH CHECK (
    org_id = public.auth_user_org_id()
    AND user_id = public.current_user_id()
    AND public.auth_user_role() IN ('delivery_manager', 'bsg_leadership', 'super_admin')
  );

CREATE POLICY knowledge_feedback_super_admin_all ON knowledge_query_feedback FOR ALL TO public
  USING (public.auth_user_role() = 'super_admin')
  WITH CHECK (public.auth_user_role() = 'super_admin');
