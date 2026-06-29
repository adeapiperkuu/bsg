-- Operational Knowledge Agent document store and retrieval evidence schema.
-- Depends on public.app_role and public.users from the initial backend schema.
-- RLS helpers below are idempotent copies of 20260623100000_rls_policies.sql.

CREATE OR REPLACE FUNCTION public.current_user_id() RETURNS uuid AS $$
  SELECT NULLIF(current_setting('request.jwt.claims', true)::json->>'sub', '')::uuid
$$ LANGUAGE sql STABLE;

CREATE OR REPLACE FUNCTION public.auth_user_role() RETURNS app_role AS $$
  SELECT role FROM public.users WHERE id = public.current_user_id()
$$ LANGUAGE sql STABLE SECURITY DEFINER SET search_path = public;

CREATE OR REPLACE FUNCTION public.auth_user_org_id() RETURNS uuid AS $$
  SELECT org_id FROM public.users WHERE id = public.current_user_id()
$$ LANGUAGE sql STABLE SECURITY DEFINER SET search_path = public;

CREATE TYPE knowledge_folder_kind AS ENUM ('sops', 'guides', 'histories');
CREATE TYPE knowledge_source_type AS ENUM (
  'sop',
  'guide',
  'training_document',
  'project_charter',
  'escalation_note',
  'lesson_learned'
);
CREATE TYPE knowledge_visibility AS ENUM ('internal_only', 'leadership_only', 'client_safe');
CREATE TYPE knowledge_document_status AS ENUM ('draft', 'approved', 'archived');
CREATE TYPE knowledge_indexing_status AS ENUM ('not_indexed', 'indexing', 'indexed', 'failed');

CREATE TABLE knowledge_folders (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  org_id UUID NOT NULL REFERENCES organisations (id) ON DELETE RESTRICT,
  name TEXT NOT NULL,
  folder_kind knowledge_folder_kind NOT NULL,
  display_order INT NOT NULL DEFAULT 0,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  deleted_at TIMESTAMPTZ,
  CONSTRAINT knowledge_folders_org_kind_key UNIQUE (org_id, folder_kind)
);

CREATE TABLE knowledge_documents (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  org_id UUID NOT NULL REFERENCES organisations (id) ON DELETE RESTRICT,
  folder_id UUID NOT NULL REFERENCES knowledge_folders (id) ON DELETE RESTRICT,
  title TEXT NOT NULL,
  source_type knowledge_source_type NOT NULL,
  version TEXT NOT NULL,
  visibility knowledge_visibility NOT NULL DEFAULT 'internal_only',
  status knowledge_document_status NOT NULL DEFAULT 'draft',
  owner_approver TEXT NOT NULL,
  effective_date DATE,
  file_name TEXT NOT NULL,
  file_mime_type TEXT NOT NULL,
  file_size_bytes BIGINT CHECK (file_size_bytes IS NULL OR file_size_bytes >= 0),
  storage_path TEXT,
  checksum_sha256 TEXT,
  indexing_status knowledge_indexing_status NOT NULL DEFAULT 'not_indexed',
  indexed_at TIMESTAMPTZ,
  uploaded_by UUID REFERENCES users (id) ON DELETE SET NULL,
  approved_by UUID REFERENCES users (id) ON DELETE SET NULL,
  approved_at TIMESTAMPTZ,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  deleted_at TIMESTAMPTZ
);

CREATE TABLE knowledge_document_chunks (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  org_id UUID NOT NULL REFERENCES organisations (id) ON DELETE RESTRICT,
  document_id UUID NOT NULL REFERENCES knowledge_documents (id) ON DELETE CASCADE,
  chunk_index INT NOT NULL CHECK (chunk_index >= 0),
  heading TEXT,
  page_number INT CHECK (page_number IS NULL OR page_number > 0),
  content TEXT NOT NULL,
  token_count INT CHECK (token_count IS NULL OR token_count >= 0),
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  CONSTRAINT knowledge_document_chunks_document_index_key UNIQUE (document_id, chunk_index)
);

CREATE TABLE knowledge_document_embeddings (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  org_id UUID NOT NULL REFERENCES organisations (id) ON DELETE RESTRICT,
  document_id UUID NOT NULL REFERENCES knowledge_documents (id) ON DELETE CASCADE,
  chunk_id UUID NOT NULL REFERENCES knowledge_document_chunks (id) ON DELETE CASCADE,
  embedding_model TEXT NOT NULL,
  embedding_dimensions INT NOT NULL CHECK (embedding_dimensions > 0),
  embedding JSONB NOT NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  CONSTRAINT knowledge_document_embeddings_chunk_model_key UNIQUE (chunk_id, embedding_model)
);

CREATE TABLE knowledge_evidence_links (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  org_id UUID NOT NULL REFERENCES organisations (id) ON DELETE RESTRICT,
  agent_query_id UUID NOT NULL REFERENCES agent_queries (id) ON DELETE CASCADE,
  document_id UUID NOT NULL REFERENCES knowledge_documents (id) ON DELETE RESTRICT,
  chunk_id UUID REFERENCES knowledge_document_chunks (id) ON DELETE SET NULL,
  citation_label TEXT NOT NULL,
  relevance_score NUMERIC(5,4) CHECK (relevance_score IS NULL OR relevance_score BETWEEN 0 AND 1),
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX knowledge_folders_org_idx ON knowledge_folders (org_id);
CREATE INDEX knowledge_documents_org_folder_idx ON knowledge_documents (org_id, folder_id);
CREATE INDEX knowledge_documents_retrieval_idx ON knowledge_documents (org_id, status, indexing_status, visibility)
  WHERE deleted_at IS NULL;
CREATE INDEX knowledge_document_chunks_document_idx ON knowledge_document_chunks (document_id);
CREATE INDEX knowledge_document_embeddings_document_idx ON knowledge_document_embeddings (document_id);
CREATE INDEX knowledge_evidence_links_query_idx ON knowledge_evidence_links (agent_query_id);
CREATE INDEX knowledge_evidence_links_document_idx ON knowledge_evidence_links (document_id);

CREATE TRIGGER knowledge_folders_updated_at BEFORE UPDATE ON knowledge_folders FOR EACH ROW EXECUTE FUNCTION set_updated_at();
CREATE TRIGGER knowledge_documents_updated_at BEFORE UPDATE ON knowledge_documents FOR EACH ROW EXECUTE FUNCTION set_updated_at();
CREATE TRIGGER knowledge_document_chunks_updated_at BEFORE UPDATE ON knowledge_document_chunks FOR EACH ROW EXECUTE FUNCTION set_updated_at();

ALTER TABLE knowledge_folders ENABLE ROW LEVEL SECURITY;
ALTER TABLE knowledge_documents ENABLE ROW LEVEL SECURITY;
ALTER TABLE knowledge_document_chunks ENABLE ROW LEVEL SECURITY;
ALTER TABLE knowledge_document_embeddings ENABLE ROW LEVEL SECURITY;
ALTER TABLE knowledge_evidence_links ENABLE ROW LEVEL SECURITY;

CREATE OR REPLACE FUNCTION public.can_access_knowledge_visibility(item_visibility knowledge_visibility)
RETURNS boolean AS $$
  SELECT CASE
    WHEN public.auth_user_role() = 'super_admin' THEN true
    WHEN public.auth_user_role() = 'bsg_leadership' THEN item_visibility IN ('internal_only', 'leadership_only', 'client_safe')
    WHEN public.auth_user_role() = 'delivery_manager' THEN item_visibility IN ('internal_only', 'client_safe')
    WHEN public.auth_user_role() = 'client' THEN item_visibility = 'client_safe'
    ELSE false
  END
$$ LANGUAGE sql STABLE SECURITY DEFINER SET search_path = public;

CREATE OR REPLACE FUNCTION public.is_approved_indexed_knowledge_document(document_id uuid)
RETURNS boolean AS $$
  SELECT EXISTS (
    SELECT 1
    FROM public.knowledge_documents kd
    WHERE kd.id = document_id
      AND kd.deleted_at IS NULL
      AND kd.status = 'approved'
      AND kd.indexing_status = 'indexed'
      AND public.can_access_knowledge_visibility(kd.visibility)
  )
$$ LANGUAGE sql STABLE SECURITY DEFINER SET search_path = public;

CREATE POLICY knowledge_folders_read ON knowledge_folders FOR SELECT TO public
  USING (
    public.current_user_id() IS NOT NULL
    AND deleted_at IS NULL
    AND (public.auth_user_role() IN ('bsg_leadership', 'super_admin') OR org_id = public.auth_user_org_id())
  );

CREATE POLICY knowledge_folders_dm_write ON knowledge_folders FOR ALL TO public
  USING (public.auth_user_role() = 'delivery_manager' AND org_id = public.auth_user_org_id())
  WITH CHECK (public.auth_user_role() = 'delivery_manager' AND org_id = public.auth_user_org_id());

CREATE POLICY knowledge_folders_super_admin_all ON knowledge_folders FOR ALL TO public
  USING (public.auth_user_role() = 'super_admin') WITH CHECK (public.auth_user_role() = 'super_admin');

CREATE POLICY knowledge_documents_read ON knowledge_documents FOR SELECT TO public
  USING (
    deleted_at IS NULL
    AND public.can_access_knowledge_visibility(visibility)
    AND (public.auth_user_role() IN ('bsg_leadership', 'super_admin') OR org_id = public.auth_user_org_id())
  );

CREATE POLICY knowledge_documents_dm_write ON knowledge_documents FOR ALL TO public
  USING (public.auth_user_role() = 'delivery_manager' AND org_id = public.auth_user_org_id())
  WITH CHECK (public.auth_user_role() = 'delivery_manager' AND org_id = public.auth_user_org_id());

CREATE POLICY knowledge_documents_super_admin_all ON knowledge_documents FOR ALL TO public
  USING (public.auth_user_role() = 'super_admin') WITH CHECK (public.auth_user_role() = 'super_admin');

CREATE POLICY knowledge_chunks_retrieval_read ON knowledge_document_chunks FOR SELECT TO public
  USING (
    (public.auth_user_role() IN ('bsg_leadership', 'super_admin') OR org_id = public.auth_user_org_id())
    AND public.is_approved_indexed_knowledge_document(document_id)
  );

CREATE POLICY knowledge_chunks_dm_write ON knowledge_document_chunks FOR ALL TO public
  USING (public.auth_user_role() = 'delivery_manager' AND org_id = public.auth_user_org_id())
  WITH CHECK (public.auth_user_role() = 'delivery_manager' AND org_id = public.auth_user_org_id());

CREATE POLICY knowledge_chunks_super_admin_all ON knowledge_document_chunks FOR ALL TO public
  USING (public.auth_user_role() = 'super_admin') WITH CHECK (public.auth_user_role() = 'super_admin');

CREATE POLICY knowledge_embeddings_retrieval_read ON knowledge_document_embeddings FOR SELECT TO public
  USING (
    (public.auth_user_role() IN ('bsg_leadership', 'super_admin') OR org_id = public.auth_user_org_id())
    AND public.is_approved_indexed_knowledge_document(document_id)
  );

CREATE POLICY knowledge_embeddings_dm_write ON knowledge_document_embeddings FOR ALL TO public
  USING (public.auth_user_role() = 'delivery_manager' AND org_id = public.auth_user_org_id())
  WITH CHECK (public.auth_user_role() = 'delivery_manager' AND org_id = public.auth_user_org_id());

CREATE POLICY knowledge_embeddings_super_admin_all ON knowledge_document_embeddings FOR ALL TO public
  USING (public.auth_user_role() = 'super_admin') WITH CHECK (public.auth_user_role() = 'super_admin');

CREATE POLICY knowledge_evidence_read ON knowledge_evidence_links FOR SELECT TO public
  USING (
    (public.auth_user_role() IN ('bsg_leadership', 'super_admin') OR org_id = public.auth_user_org_id())
    AND public.is_approved_indexed_knowledge_document(document_id)
  );

CREATE POLICY knowledge_evidence_insert ON knowledge_evidence_links FOR INSERT TO public
  WITH CHECK (
    org_id = public.auth_user_org_id()
    AND public.is_approved_indexed_knowledge_document(document_id)
  );

CREATE POLICY knowledge_evidence_super_admin_all ON knowledge_evidence_links FOR ALL TO public
  USING (public.auth_user_role() = 'super_admin') WITH CHECK (public.auth_user_role() = 'super_admin');
