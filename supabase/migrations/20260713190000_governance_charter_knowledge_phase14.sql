-- Phase 14: Governance ↔ Knowledge Integration
-- Publish approved Project Charters into Operational Knowledge as versioned documents.
-- Additive only; approval status is never rolled back on publish failure.

DO $$ BEGIN
  CREATE TYPE governance_charter_publication_status AS ENUM (
    'not_published',
    'publishing',
    'published',
    'failed',
    'superseded'
  );
EXCEPTION WHEN duplicate_object THEN NULL;
END $$;

DO $$ BEGIN
  CREATE TYPE governance_charter_publication_event_type AS ENUM (
    'charter_published',
    'knowledge_version_created',
    'knowledge_publication_failed',
    'knowledge_republished',
    'knowledge_publication_retried',
    'knowledge_version_superseded',
    'already_published',
    'knowledge_unpublished'
  );
EXCEPTION WHEN duplicate_object THEN NULL;
END $$;

ALTER TABLE project_charters
  ADD COLUMN IF NOT EXISTS publication_status governance_charter_publication_status
    NOT NULL DEFAULT 'not_published',
  ADD COLUMN IF NOT EXISTS knowledge_version_id UUID
    REFERENCES knowledge_document_versions (id) ON DELETE SET NULL,
  ADD COLUMN IF NOT EXISTS published_at TIMESTAMPTZ,
  ADD COLUMN IF NOT EXISTS published_by UUID REFERENCES users (id) ON DELETE SET NULL,
  ADD COLUMN IF NOT EXISTS publication_error TEXT,
  ADD COLUMN IF NOT EXISTS publication_attempt_count INTEGER NOT NULL DEFAULT 0,
  ADD COLUMN IF NOT EXISTS last_publication_attempt_at TIMESTAMPTZ;

CREATE INDEX IF NOT EXISTS project_charters_publication_status_idx
  ON project_charters (org_id, publication_status);

CREATE INDEX IF NOT EXISTS project_charters_knowledge_document_idx
  ON project_charters (knowledge_document_id)
  WHERE knowledge_document_id IS NOT NULL;

-- Idempotency: one published Knowledge version per charter row.
CREATE UNIQUE INDEX IF NOT EXISTS project_charters_published_knowledge_version_uidx
  ON project_charters (knowledge_version_id)
  WHERE knowledge_version_id IS NOT NULL;

-- Immutable publication timeline (Governance Timeline extension for charters)
CREATE TABLE IF NOT EXISTS governance_charter_publication_events (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  org_id UUID NOT NULL REFERENCES organisations (id) ON DELETE RESTRICT,
  charter_id UUID NOT NULL REFERENCES project_charters (id) ON DELETE CASCADE,
  project_id UUID NOT NULL REFERENCES projects (id) ON DELETE CASCADE,
  event_type governance_charter_publication_event_type NOT NULL,
  actor_user_id UUID REFERENCES users (id) ON DELETE SET NULL,
  knowledge_document_id UUID REFERENCES knowledge_documents (id) ON DELETE SET NULL,
  knowledge_version_id UUID REFERENCES knowledge_document_versions (id) ON DELETE SET NULL,
  previous_knowledge_version_id UUID REFERENCES knowledge_document_versions (id) ON DELETE SET NULL,
  charter_version TEXT,
  reason TEXT,
  event_metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS governance_charter_publication_events_charter_idx
  ON governance_charter_publication_events (charter_id, created_at);

CREATE INDEX IF NOT EXISTS governance_charter_publication_events_org_type_idx
  ON governance_charter_publication_events (org_id, event_type, created_at);

-- Append-only publication audit trail
CREATE TABLE IF NOT EXISTS governance_charter_publication_audits (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  org_id UUID NOT NULL REFERENCES organisations (id) ON DELETE RESTRICT,
  charter_id UUID NOT NULL REFERENCES project_charters (id) ON DELETE CASCADE,
  project_id UUID NOT NULL REFERENCES projects (id) ON DELETE CASCADE,
  actor_user_id UUID REFERENCES users (id) ON DELETE SET NULL,
  action TEXT NOT NULL,
  knowledge_document_id UUID REFERENCES knowledge_documents (id) ON DELETE SET NULL,
  knowledge_version_id UUID REFERENCES knowledge_document_versions (id) ON DELETE SET NULL,
  previous_knowledge_version_id UUID REFERENCES knowledge_document_versions (id) ON DELETE SET NULL,
  charter_version TEXT,
  reason TEXT,
  audit_metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS governance_charter_publication_audits_charter_idx
  ON governance_charter_publication_audits (charter_id, created_at);

ALTER TABLE governance_charter_publication_events ENABLE ROW LEVEL SECURITY;
ALTER TABLE governance_charter_publication_audits ENABLE ROW LEVEL SECURITY;

CREATE POLICY governance_charter_publication_events_org_select
  ON governance_charter_publication_events FOR SELECT TO public
  USING (
    public.auth_user_role() = 'super_admin'
    OR (
      org_id = public.auth_user_org_id()
      AND public.auth_user_role() IN ('delivery_manager', 'bsg_leadership', 'client')
    )
  );

CREATE POLICY governance_charter_publication_events_service_all
  ON governance_charter_publication_events FOR ALL TO public
  USING (public.auth_user_role() IN ('delivery_manager', 'bsg_leadership', 'super_admin'))
  WITH CHECK (public.auth_user_role() IN ('delivery_manager', 'bsg_leadership', 'super_admin'));

CREATE POLICY governance_charter_publication_audits_org_select
  ON governance_charter_publication_audits FOR SELECT TO public
  USING (
    public.auth_user_role() = 'super_admin'
    OR (
      org_id = public.auth_user_org_id()
      AND public.auth_user_role() IN ('delivery_manager', 'bsg_leadership', 'client')
    )
  );

CREATE POLICY governance_charter_publication_audits_service_all
  ON governance_charter_publication_audits FOR ALL TO public
  USING (public.auth_user_role() IN ('delivery_manager', 'bsg_leadership', 'super_admin'))
  WITH CHECK (public.auth_user_role() IN ('delivery_manager', 'bsg_leadership', 'super_admin'));
