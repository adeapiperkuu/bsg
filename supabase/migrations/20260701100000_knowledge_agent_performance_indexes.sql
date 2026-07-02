-- Composite indexes for Knowledge Agent hot paths.
-- These are additive and idempotent; existing single-column/broader indexes are left in place.

CREATE INDEX IF NOT EXISTS agent_queries_org_agent_created_idx
  ON agent_queries (org_id, agent_name, created_at DESC);

CREATE INDEX IF NOT EXISTS agent_queries_org_user_agent_project_created_idx
  ON agent_queries (org_id, user_id, agent_name, project_id, created_at DESC);

CREATE INDEX IF NOT EXISTS knowledge_documents_org_deleted_title_idx
  ON knowledge_documents (org_id, deleted_at, title);

CREATE INDEX IF NOT EXISTS knowledge_folders_org_deleted_order_idx
  ON knowledge_folders (org_id, deleted_at, display_order);

CREATE INDEX IF NOT EXISTS knowledge_documents_org_folder_deleted_title_idx
  ON knowledge_documents (org_id, folder_id, deleted_at, title);

CREATE INDEX IF NOT EXISTS knowledge_documents_org_uploaded_created_idx
  ON knowledge_documents (org_id, uploaded_by, created_at DESC)
  WHERE deleted_at IS NULL;

CREATE INDEX IF NOT EXISTS knowledge_documents_org_status_created_idx
  ON knowledge_documents (org_id, status, created_at DESC)
  WHERE deleted_at IS NULL;

CREATE INDEX IF NOT EXISTS knowledge_documents_org_document_type_created_idx
  ON knowledge_documents (org_id, document_type, created_at DESC)
  WHERE deleted_at IS NULL;

CREATE INDEX IF NOT EXISTS knowledge_documents_org_source_updated_idx
  ON knowledge_documents (org_id, status, source_type, updated_at DESC)
  WHERE deleted_at IS NULL;

CREATE INDEX IF NOT EXISTS knowledge_documents_retrieval_scope_idx
  ON knowledge_documents (
    org_id,
    status,
    indexing_status,
    processing_status,
    visibility,
    project,
    department
  )
  WHERE deleted_at IS NULL;

CREATE INDEX IF NOT EXISTS knowledge_document_versions_document_uploaded_idx
  ON knowledge_document_versions (document_id, uploaded_at DESC);

CREATE INDEX IF NOT EXISTS knowledge_document_chunks_document_version_index_idx
  ON knowledge_document_chunks (document_id, version_id, chunk_index);

CREATE INDEX IF NOT EXISTS knowledge_document_chunks_org_document_index_idx
  ON knowledge_document_chunks (org_id, document_id, chunk_index);

CREATE INDEX IF NOT EXISTS knowledge_evidence_links_query_document_idx
  ON knowledge_evidence_links (agent_query_id, document_id);

CREATE INDEX IF NOT EXISTS knowledge_evidence_links_org_document_created_idx
  ON knowledge_evidence_links (org_id, document_id, created_at DESC);

CREATE INDEX IF NOT EXISTS knowledge_gaps_org_status_created_idx
  ON knowledge_gaps (org_id, status, created_at DESC);
