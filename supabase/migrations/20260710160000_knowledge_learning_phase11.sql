-- Phase 11: continuous learning — document summaries + reviewable AI suggestions.

ALTER TABLE knowledge_documents
  ADD COLUMN IF NOT EXISTS executive_summary TEXT,
  ADD COLUMN IF NOT EXISTS key_procedures TEXT[] NOT NULL DEFAULT '{}',
  ADD COLUMN IF NOT EXISTS important_warnings TEXT[] NOT NULL DEFAULT '{}',
  ADD COLUMN IF NOT EXISTS affected_departments TEXT[] NOT NULL DEFAULT '{}',
  ADD COLUMN IF NOT EXISTS related_document_ids UUID[] NOT NULL DEFAULT '{}',
  ADD COLUMN IF NOT EXISTS summary_generated_at TIMESTAMPTZ;

CREATE TABLE IF NOT EXISTS knowledge_suggestions (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  org_id UUID NOT NULL REFERENCES organisations (id) ON DELETE RESTRICT,
  document_id UUID REFERENCES knowledge_documents (id) ON DELETE CASCADE,
  suggestion_type TEXT NOT NULL,
  title TEXT NOT NULL,
  detail TEXT NOT NULL,
  proposed_changes JSONB NOT NULL DEFAULT '{}'::jsonb,
  evidence JSONB NOT NULL DEFAULT '{}'::jsonb,
  status TEXT NOT NULL DEFAULT 'open'
    CHECK (status IN ('open', 'accepted', 'dismissed', 'applied')),
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  reviewed_by UUID REFERENCES users (id) ON DELETE SET NULL,
  reviewed_at TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS knowledge_suggestions_org_status_idx
  ON knowledge_suggestions (org_id, status, created_at DESC);

CREATE INDEX IF NOT EXISTS knowledge_suggestions_document_idx
  ON knowledge_suggestions (document_id, created_at DESC);

ALTER TABLE knowledge_suggestions ENABLE ROW LEVEL SECURITY;

DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM pg_policies
    WHERE schemaname = 'public'
      AND tablename = 'knowledge_suggestions'
      AND policyname = 'knowledge_suggestions_read'
  ) THEN
    CREATE POLICY knowledge_suggestions_read ON knowledge_suggestions FOR SELECT TO public
      USING (
        org_id = public.auth_user_org_id()
        AND public.auth_user_role() IN ('delivery_manager', 'bsg_leadership', 'super_admin')
      );
  END IF;

  IF NOT EXISTS (
    SELECT 1 FROM pg_policies
    WHERE schemaname = 'public'
      AND tablename = 'knowledge_suggestions'
      AND policyname = 'knowledge_suggestions_write'
  ) THEN
    CREATE POLICY knowledge_suggestions_write ON knowledge_suggestions FOR ALL TO public
      USING (
        org_id = public.auth_user_org_id()
        AND public.auth_user_role() IN ('delivery_manager', 'bsg_leadership', 'super_admin')
      )
      WITH CHECK (
        org_id = public.auth_user_org_id()
        AND public.auth_user_role() IN ('delivery_manager', 'bsg_leadership', 'super_admin')
      );
  END IF;

  IF NOT EXISTS (
    SELECT 1 FROM pg_policies
    WHERE schemaname = 'public'
      AND tablename = 'knowledge_suggestions'
      AND policyname = 'knowledge_suggestions_super_admin_all'
  ) THEN
    CREATE POLICY knowledge_suggestions_super_admin_all ON knowledge_suggestions FOR ALL TO public
      USING (public.auth_user_role() = 'super_admin')
      WITH CHECK (public.auth_user_role() = 'super_admin');
  END IF;
END $$;
