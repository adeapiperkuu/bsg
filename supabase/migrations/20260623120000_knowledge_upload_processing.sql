-- Operational Knowledge Agent upload processing, extraction, chunking, and versioning.

CREATE TYPE knowledge_processing_status AS ENUM ('uploaded', 'extracting', 'extracted', 'chunking', 'chunked', 'failed');
CREATE TYPE knowledge_extraction_status AS ENUM ('pending', 'extracting', 'succeeded', 'failed');

INSERT INTO storage.buckets (id, name, public)
VALUES ('knowledge-documents', 'knowledge-documents', false)
ON CONFLICT (id) DO NOTHING;

ALTER TABLE knowledge_documents
  ADD COLUMN IF NOT EXISTS description TEXT,
  ADD COLUMN IF NOT EXISTS owner TEXT,
  ADD COLUMN IF NOT EXISTS approver TEXT,
  ADD COLUMN IF NOT EXISTS file_url TEXT,
  ADD COLUMN IF NOT EXISTS upload_date TIMESTAMPTZ NOT NULL DEFAULT now(),
  ADD COLUMN IF NOT EXISTS processing_status knowledge_processing_status NOT NULL DEFAULT 'uploaded';

UPDATE knowledge_documents
SET owner = COALESCE(owner, owner_approver),
    approver = COALESCE(approver, owner_approver)
WHERE owner IS NULL OR approver IS NULL;

CREATE TABLE knowledge_document_versions (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  org_id UUID NOT NULL REFERENCES organisations (id) ON DELETE RESTRICT,
  document_id UUID NOT NULL REFERENCES knowledge_documents (id) ON DELETE CASCADE,
  version TEXT NOT NULL,
  file_name TEXT NOT NULL,
  file_mime_type TEXT NOT NULL,
  file_size_bytes BIGINT CHECK (file_size_bytes IS NULL OR file_size_bytes >= 0),
  file_url TEXT,
  storage_path TEXT,
  checksum_sha256 TEXT,
  is_active BOOLEAN NOT NULL DEFAULT FALSE,
  uploaded_by UUID REFERENCES users (id) ON DELETE SET NULL,
  uploaded_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  CONSTRAINT knowledge_document_versions_document_version_key UNIQUE (document_id, version)
);

ALTER TABLE knowledge_documents
  ADD COLUMN IF NOT EXISTS active_version_id UUID REFERENCES knowledge_document_versions (id) ON DELETE SET NULL;

CREATE TABLE knowledge_document_extractions (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  org_id UUID NOT NULL REFERENCES organisations (id) ON DELETE RESTRICT,
  document_id UUID NOT NULL REFERENCES knowledge_documents (id) ON DELETE CASCADE,
  version_id UUID NOT NULL REFERENCES knowledge_document_versions (id) ON DELETE CASCADE,
  extracted_text TEXT,
  extraction_status knowledge_extraction_status NOT NULL DEFAULT 'pending',
  extraction_error TEXT,
  extracted_at TIMESTAMPTZ,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  CONSTRAINT knowledge_document_extractions_version_key UNIQUE (version_id)
);

ALTER TABLE knowledge_document_chunks
  ADD COLUMN IF NOT EXISTS version_id UUID REFERENCES knowledge_document_versions (id) ON DELETE CASCADE,
  ADD COLUMN IF NOT EXISTS chunk_text TEXT,
  ADD COLUMN IF NOT EXISTS section_title TEXT;

UPDATE knowledge_document_chunks
SET chunk_text = COALESCE(chunk_text, content),
    section_title = COALESCE(section_title, heading)
WHERE chunk_text IS NULL OR section_title IS NULL;

ALTER TABLE knowledge_document_chunks
  ALTER COLUMN chunk_text SET NOT NULL;

ALTER TABLE knowledge_document_chunks
  DROP CONSTRAINT IF EXISTS knowledge_document_chunks_document_index_key;

ALTER TABLE knowledge_document_chunks
  ADD CONSTRAINT knowledge_document_chunks_version_index_key UNIQUE (version_id, chunk_index);

CREATE INDEX knowledge_document_versions_document_idx ON knowledge_document_versions (document_id);
CREATE INDEX knowledge_document_versions_active_idx ON knowledge_document_versions (document_id, is_active);
CREATE INDEX knowledge_document_extractions_document_idx ON knowledge_document_extractions (document_id);
CREATE INDEX knowledge_document_extractions_version_idx ON knowledge_document_extractions (version_id);
CREATE INDEX knowledge_document_chunks_version_idx ON knowledge_document_chunks (version_id);
CREATE INDEX knowledge_documents_processing_status_idx ON knowledge_documents (org_id, processing_status);

CREATE TRIGGER knowledge_document_versions_updated_at BEFORE UPDATE ON knowledge_document_versions FOR EACH ROW EXECUTE FUNCTION set_updated_at();
CREATE TRIGGER knowledge_document_extractions_updated_at BEFORE UPDATE ON knowledge_document_extractions FOR EACH ROW EXECUTE FUNCTION set_updated_at();

ALTER TABLE knowledge_document_versions ENABLE ROW LEVEL SECURITY;
ALTER TABLE knowledge_document_extractions ENABLE ROW LEVEL SECURITY;

CREATE POLICY knowledge_versions_read ON knowledge_document_versions FOR SELECT TO public
  USING (
    EXISTS (
      SELECT 1 FROM knowledge_documents kd
      WHERE kd.id = knowledge_document_versions.document_id
        AND kd.deleted_at IS NULL
        AND public.can_access_knowledge_visibility(kd.visibility)
        AND (public.auth_user_role() IN ('bsg_leadership', 'super_admin') OR kd.org_id = public.auth_user_org_id())
    )
  );

CREATE POLICY knowledge_versions_dm_write ON knowledge_document_versions FOR ALL TO public
  USING (public.auth_user_role() = 'delivery_manager' AND org_id = public.auth_user_org_id())
  WITH CHECK (public.auth_user_role() = 'delivery_manager' AND org_id = public.auth_user_org_id());

CREATE POLICY knowledge_versions_super_admin_all ON knowledge_document_versions FOR ALL TO public
  USING (public.auth_user_role() = 'super_admin') WITH CHECK (public.auth_user_role() = 'super_admin');

CREATE POLICY knowledge_extractions_read ON knowledge_document_extractions FOR SELECT TO public
  USING (
    EXISTS (
      SELECT 1 FROM knowledge_documents kd
      WHERE kd.id = knowledge_document_extractions.document_id
        AND kd.deleted_at IS NULL
        AND public.can_access_knowledge_visibility(kd.visibility)
        AND (public.auth_user_role() IN ('bsg_leadership', 'super_admin') OR kd.org_id = public.auth_user_org_id())
    )
  );

CREATE POLICY knowledge_extractions_dm_write ON knowledge_document_extractions FOR ALL TO public
  USING (public.auth_user_role() = 'delivery_manager' AND org_id = public.auth_user_org_id())
  WITH CHECK (public.auth_user_role() = 'delivery_manager' AND org_id = public.auth_user_org_id());

CREATE POLICY knowledge_extractions_super_admin_all ON knowledge_document_extractions FOR ALL TO public
  USING (public.auth_user_role() = 'super_admin') WITH CHECK (public.auth_user_role() = 'super_admin');
