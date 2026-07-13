-- Phase 7: persistent knowledge ingestion job queue and progress tracking.

CREATE TYPE knowledge_ingestion_job_status AS ENUM (
  'pending',
  'processing',
  'completed',
  'failed'
);

CREATE TABLE knowledge_ingestion_jobs (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  org_id UUID NOT NULL REFERENCES organisations (id) ON DELETE RESTRICT,
  document_id UUID NOT NULL REFERENCES knowledge_documents (id) ON DELETE CASCADE,
  version_id UUID REFERENCES knowledge_document_versions (id) ON DELETE SET NULL,
  status knowledge_ingestion_job_status NOT NULL DEFAULT 'pending',
  progress_percentage INTEGER NOT NULL DEFAULT 0
    CHECK (progress_percentage >= 0 AND progress_percentage <= 100),
  retry_count INTEGER NOT NULL DEFAULT 0,
  max_retries INTEGER NOT NULL DEFAULT 3,
  failure_reason TEXT,
  extraction_warnings TEXT[] NOT NULL DEFAULT '{}',
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  started_at TIMESTAMPTZ,
  next_retry_at TIMESTAMPTZ,
  completed_at TIMESTAMPTZ,
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX knowledge_ingestion_jobs_status_idx
  ON knowledge_ingestion_jobs (status);

CREATE INDEX knowledge_ingestion_jobs_document_id_idx
  ON knowledge_ingestion_jobs (document_id);

CREATE INDEX knowledge_ingestion_jobs_next_retry_at_idx
  ON knowledge_ingestion_jobs (next_retry_at);

CREATE INDEX knowledge_ingestion_jobs_document_created_idx
  ON knowledge_ingestion_jobs (document_id, created_at DESC);

CREATE INDEX knowledge_ingestion_jobs_queue_idx
  ON knowledge_ingestion_jobs (status, next_retry_at, created_at)
  WHERE status = 'pending';
