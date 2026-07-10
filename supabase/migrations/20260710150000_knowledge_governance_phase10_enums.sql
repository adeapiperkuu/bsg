-- Phase 10 enums must commit before later statements can reference new labels.
ALTER TYPE knowledge_document_status ADD VALUE IF NOT EXISTS 'submitted_for_review';
ALTER TYPE knowledge_document_status ADD VALUE IF NOT EXISTS 'rejected';
ALTER TYPE knowledge_document_status ADD VALUE IF NOT EXISTS 'needs_reindex';
ALTER TYPE knowledge_document_status ADD VALUE IF NOT EXISTS 'expired';

ALTER TYPE knowledge_visibility ADD VALUE IF NOT EXISTS 'restricted';
