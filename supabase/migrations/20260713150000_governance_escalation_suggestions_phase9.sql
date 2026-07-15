-- Project Governance Agent — Phase 9: Escalation suggestions (auto-detect, reviewable)

ALTER TYPE governance_ai_recommendation_status ADD VALUE IF NOT EXISTS 'snoozed';

CREATE TYPE governance_escalation_trigger_type AS ENUM (
  'overdue_blocking_dependency',
  'repeated_overdue_dependency',
  'multiple_blocking_dependencies',
  'critical_delivery_risk',
  'declining_delivery_confidence',
  'unresolved_scope_risk',
  'overdue_critical_action',
  'repeated_mitigation_failure',
  'milestone_at_risk',
  'combined_governance_risk'
);

ALTER TABLE governance_ai_recommendations
  ADD COLUMN IF NOT EXISTS auto_detected BOOLEAN NOT NULL DEFAULT false,
  ADD COLUMN IF NOT EXISTS trigger_type governance_escalation_trigger_type,
  ADD COLUMN IF NOT EXISTS trigger_entity_type TEXT,
  ADD COLUMN IF NOT EXISTS trigger_entity_id UUID,
  ADD COLUMN IF NOT EXISTS trigger_fingerprint TEXT,
  ADD COLUMN IF NOT EXISTS severity_score NUMERIC(6, 3),
  ADD COLUMN IF NOT EXISTS detected_at TIMESTAMPTZ,
  ADD COLUMN IF NOT EXISTS snoozed_until TIMESTAMPTZ,
  ADD COLUMN IF NOT EXISTS snooze_reason TEXT;

CREATE INDEX IF NOT EXISTS governance_ai_recommendations_escalation_sug_idx
  ON governance_ai_recommendations (org_id, status, auto_detected, recommendation_type)
  WHERE deleted_at IS NULL
    AND auto_detected = true
    AND recommendation_type = 'escalation_required';

CREATE INDEX IF NOT EXISTS governance_ai_recommendations_trigger_fp_idx
  ON governance_ai_recommendations (org_id, trigger_fingerprint)
  WHERE deleted_at IS NULL
    AND trigger_fingerprint IS NOT NULL;

CREATE INDEX IF NOT EXISTS governance_ai_recommendations_project_trigger_idx
  ON governance_ai_recommendations (org_id, project_id, trigger_type, status)
  WHERE deleted_at IS NULL
    AND auto_detected = true;

CREATE UNIQUE INDEX IF NOT EXISTS governance_ai_recommendations_active_trigger_fp_uidx
  ON governance_ai_recommendations (org_id, trigger_fingerprint)
  WHERE deleted_at IS NULL
    AND status = 'active'
    AND auto_detected = true
    AND trigger_fingerprint IS NOT NULL;
