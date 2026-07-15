-- Phase 15: quality→governance auto-escalation source type + client-safe escalation summaries.

ALTER TYPE governance_escalation_source_type ADD VALUE IF NOT EXISTS 'quality_risk';

ALTER TABLE governance_escalations
  ADD COLUMN IF NOT EXISTS client_summary text,
  ADD COLUMN IF NOT EXISTS client_visible boolean NOT NULL DEFAULT false,
  ADD COLUMN IF NOT EXISTS client_published_by uuid REFERENCES users (id) ON DELETE SET NULL,
  ADD COLUMN IF NOT EXISTS client_published_at timestamptz;

CREATE INDEX IF NOT EXISTS governance_escalations_client_visible_idx
  ON governance_escalations (org_id, project_id, client_visible)
  WHERE deleted_at IS NULL AND client_visible = true;

COMMENT ON COLUMN governance_escalations.client_summary IS
  'Approved client-safe narrative shown instead of internal description.';
COMMENT ON COLUMN governance_escalations.client_visible IS
  'When true, assigned clients may see this escalation with client_summary.';
