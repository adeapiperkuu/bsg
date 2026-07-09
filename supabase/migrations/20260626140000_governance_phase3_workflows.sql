-- Project Governance Agent — Phase 3 workflow fields

CREATE TYPE governance_escalation_source_type AS ENUM ('delivery_risk', 'knowledge_document');

ALTER TABLE governance_escalations
  ADD COLUMN source_type governance_escalation_source_type,
  ADD COLUMN source_id UUID;

CREATE INDEX governance_escalations_source_idx
  ON governance_escalations (org_id, source_type, source_id)
  WHERE source_id IS NOT NULL;

ALTER TABLE governance_actions
  ADD COLUMN linked_knowledge_document_id UUID REFERENCES knowledge_documents (id) ON DELETE SET NULL;

ALTER TABLE project_scope_states
  ADD COLUMN linked_charter_document_id UUID REFERENCES knowledge_documents (id) ON DELETE SET NULL;
