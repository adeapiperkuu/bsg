-- Lightweight Knowledge Agent evaluation and observability.

CREATE TABLE IF NOT EXISTS knowledge_eval_questions (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  org_id UUID NOT NULL REFERENCES organisations (id) ON DELETE RESTRICT,
  question_text TEXT NOT NULL,
  expected_document_ids UUID[] NOT NULL DEFAULT '{}',
  expected_answer_notes TEXT,
  is_active BOOLEAN NOT NULL DEFAULT true,
  created_by UUID REFERENCES users (id) ON DELETE SET NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS knowledge_eval_questions_org_idx
  ON knowledge_eval_questions (org_id, is_active, created_at DESC);

CREATE TABLE IF NOT EXISTS knowledge_eval_runs (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  org_id UUID NOT NULL REFERENCES organisations (id) ON DELETE RESTRICT,
  eval_question_id UUID NOT NULL REFERENCES knowledge_eval_questions (id) ON DELETE CASCADE,
  agent_query_id UUID REFERENCES agent_queries (id) ON DELETE SET NULL,
  expected_document_ids UUID[] NOT NULL DEFAULT '{}',
  observed_document_ids UUID[] NOT NULL DEFAULT '{}',
  citation_hit BOOLEAN NOT NULL DEFAULT false,
  empty_answer BOOLEAN NOT NULL DEFAULT false,
  latency_ms INTEGER,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS knowledge_eval_runs_org_idx
  ON knowledge_eval_runs (org_id, created_at DESC);
CREATE INDEX IF NOT EXISTS knowledge_eval_runs_question_idx
  ON knowledge_eval_runs (eval_question_id, created_at DESC);

CREATE TRIGGER knowledge_eval_questions_updated_at
  BEFORE UPDATE ON knowledge_eval_questions
  FOR EACH ROW EXECUTE FUNCTION set_updated_at();

ALTER TABLE knowledge_eval_questions ENABLE ROW LEVEL SECURITY;
ALTER TABLE knowledge_eval_runs ENABLE ROW LEVEL SECURITY;

CREATE POLICY knowledge_eval_questions_read ON knowledge_eval_questions FOR SELECT TO public
  USING (
    public.auth_user_role() IN ('bsg_leadership', 'super_admin')
    OR org_id = public.auth_user_org_id()
  );

CREATE POLICY knowledge_eval_questions_manage ON knowledge_eval_questions FOR ALL TO public
  USING (
    org_id = public.auth_user_org_id()
    AND public.auth_user_role() IN ('bsg_leadership', 'super_admin')
  )
  WITH CHECK (
    org_id = public.auth_user_org_id()
    AND public.auth_user_role() IN ('bsg_leadership', 'super_admin')
  );

CREATE POLICY knowledge_eval_runs_read ON knowledge_eval_runs FOR SELECT TO public
  USING (
    public.auth_user_role() IN ('bsg_leadership', 'super_admin')
    OR org_id = public.auth_user_org_id()
  );

CREATE POLICY knowledge_eval_runs_manage ON knowledge_eval_runs FOR ALL TO public
  USING (
    org_id = public.auth_user_org_id()
    AND public.auth_user_role() IN ('bsg_leadership', 'super_admin')
  )
  WITH CHECK (
    org_id = public.auth_user_org_id()
    AND public.auth_user_role() IN ('bsg_leadership', 'super_admin')
  );
