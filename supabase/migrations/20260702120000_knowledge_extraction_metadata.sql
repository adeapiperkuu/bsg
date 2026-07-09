-- Extraction diagnostics and richer chunk metadata for knowledge retrieval
ALTER TABLE knowledge_document_extractions
  ADD COLUMN IF NOT EXISTS diagnostics JSONB,
  ADD COLUMN IF NOT EXISTS quality_score INTEGER;

ALTER TABLE knowledge_document_chunks
  ADD COLUMN IF NOT EXISTS chunk_type TEXT NOT NULL DEFAULT 'text',
  ADD COLUMN IF NOT EXISTS section_path TEXT;
