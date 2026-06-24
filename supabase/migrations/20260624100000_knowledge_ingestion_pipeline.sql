-- Operational Knowledge Agent ingestion pipeline: cleaned text, pgvector embeddings,
-- lifecycle status, and retrieval metadata.

CREATE EXTENSION IF NOT EXISTS vector;

ALTER TYPE knowledge_processing_status ADD VALUE IF NOT EXISTS 'embedding';
ALTER TYPE knowledge_processing_status ADD VALUE IF NOT EXISTS 'ready';

ALTER TABLE knowledge_documents
  ADD COLUMN IF NOT EXISTS document_type TEXT,
  ADD COLUMN IF NOT EXISTS project TEXT,
  ADD COLUMN IF NOT EXISTS department TEXT,
  ADD COLUMN IF NOT EXISTS extracted_text TEXT,
  ADD COLUMN IF NOT EXISTS processing_error TEXT;

UPDATE knowledge_documents
SET document_type = COALESCE(document_type, source_type::text)
WHERE document_type IS NULL;

ALTER TABLE knowledge_document_chunks
  ADD COLUMN IF NOT EXISTS folder_id UUID REFERENCES knowledge_folders (id) ON DELETE RESTRICT,
  ADD COLUMN IF NOT EXISTS visibility knowledge_visibility,
  ADD COLUMN IF NOT EXISTS project TEXT,
  ADD COLUMN IF NOT EXISTS department TEXT,
  ADD COLUMN IF NOT EXISTS embedding vector(1536);

UPDATE knowledge_document_chunks kc
SET folder_id = COALESCE(kc.folder_id, kd.folder_id),
    visibility = COALESCE(kc.visibility, kd.visibility),
    project = COALESCE(kc.project, kd.project),
    department = COALESCE(kc.department, kd.department)
FROM knowledge_documents kd
WHERE kc.document_id = kd.id
  AND (kc.folder_id IS NULL OR kc.visibility IS NULL);

CREATE INDEX IF NOT EXISTS knowledge_document_chunks_embedding_hnsw_idx
  ON knowledge_document_chunks
  USING hnsw (embedding vector_cosine_ops)
  WHERE embedding IS NOT NULL;

CREATE INDEX IF NOT EXISTS knowledge_document_chunks_security_idx
  ON knowledge_document_chunks (org_id, folder_id, visibility, project, department);

CREATE INDEX IF NOT EXISTS knowledge_documents_processing_ready_idx
  ON knowledge_documents (org_id, processing_status, status, visibility)
  WHERE deleted_at IS NULL;
