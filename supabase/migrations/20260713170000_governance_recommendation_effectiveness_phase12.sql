-- Phase 12: Recommendation Effectiveness & Learning
-- Additive columns + lifecycle events + learning rules. No auto-accept / auto-escalation.

DO $$ BEGIN
  CREATE TYPE governance_false_positive_status AS ENUM (
    'confirmed_false_positive',
    'likely_false_positive',
    'not_false_positive',
    'insufficient_evidence'
  );
EXCEPTION WHEN duplicate_object THEN NULL;
END $$;

DO $$ BEGIN
  CREATE TYPE governance_recommendation_lifecycle_event_type AS ENUM (
    'created',
    'accepted',
    'dismissed',
    'snoozed',
    'converted',
    'resolved',
    'reopened',
    'feedback_submitted',
    'false_positive_confirmed'
  );
EXCEPTION WHEN duplicate_object THEN NULL;
END $$;

DO $$ BEGIN
  CREATE TYPE governance_learning_rule_status AS ENUM (
    'draft',
    'pending_approval',
    'approved',
    'active',
    'reverted',
    'rejected'
  );
EXCEPTION WHEN duplicate_object THEN NULL;
END $$;

ALTER TABLE governance_ai_recommendations
  ADD COLUMN IF NOT EXISTS false_positive_status governance_false_positive_status,
  ADD COLUMN IF NOT EXISTS false_positive_reason TEXT,
  ADD COLUMN IF NOT EXISTS false_positive_confirmed_at TIMESTAMPTZ,
  ADD COLUMN IF NOT EXISTS false_positive_confirmed_by_user_id UUID REFERENCES users(id) ON DELETE SET NULL,
  ADD COLUMN IF NOT EXISTS resolved_at TIMESTAMPTZ,
  ADD COLUMN IF NOT EXISTS resolved_by_user_id UUID REFERENCES users(id) ON DELETE SET NULL,
  ADD COLUMN IF NOT EXISTS reopened_at TIMESTAMPTZ,
  ADD COLUMN IF NOT EXISTS quality_score NUMERIC(5, 2),
  ADD COLUMN IF NOT EXISTS quality_band TEXT,
  ADD COLUMN IF NOT EXISTS quality_score_version TEXT,
  ADD COLUMN IF NOT EXISTS quality_components JSONB NOT NULL DEFAULT '{}'::jsonb,
  ADD COLUMN IF NOT EXISTS quality_provisional BOOLEAN NOT NULL DEFAULT true,
  ADD COLUMN IF NOT EXISTS calibrated_confidence NUMERIC(4, 3),
  ADD COLUMN IF NOT EXISTS confidence_band TEXT,
  ADD COLUMN IF NOT EXISTS calibration_version TEXT,
  ADD COLUMN IF NOT EXISTS calibration_gap NUMERIC(6, 4),
  ADD COLUMN IF NOT EXISTS observed_success_rate NUMERIC(5, 4),
  ADD COLUMN IF NOT EXISTS expected_calibration_error NUMERIC(6, 4),
  ADD COLUMN IF NOT EXISTS brier_score NUMERIC(6, 4),
  ADD COLUMN IF NOT EXISTS explanation_version TEXT NOT NULL DEFAULT 'v1',
  ADD COLUMN IF NOT EXISTS recurrence_after_acceptance_count INTEGER NOT NULL DEFAULT 0,
  ADD COLUMN IF NOT EXISTS recurrence_after_dismissal_count INTEGER NOT NULL DEFAULT 0;

CREATE INDEX IF NOT EXISTS governance_ai_recommendations_org_fp_status_idx
  ON governance_ai_recommendations (org_id, false_positive_status)
  WHERE deleted_at IS NULL;

CREATE INDEX IF NOT EXISTS governance_ai_recommendations_org_quality_band_idx
  ON governance_ai_recommendations (org_id, quality_band)
  WHERE deleted_at IS NULL;

CREATE INDEX IF NOT EXISTS governance_ai_recommendations_org_trigger_generated_idx
  ON governance_ai_recommendations (org_id, trigger_type, generated_at DESC)
  WHERE deleted_at IS NULL;

ALTER TABLE governance_ai_recommendation_feedback
  ADD COLUMN IF NOT EXISTS accurate BOOLEAN,
  ADD COLUMN IF NOT EXISTS useful BOOLEAN,
  ADD COLUMN IF NOT EXISTS actionable BOOLEAN,
  ADD COLUMN IF NOT EXISTS clear BOOLEAN,
  ADD COLUMN IF NOT EXISTS missing_evidence BOOLEAN NOT NULL DEFAULT false,
  ADD COLUMN IF NOT EXISTS duplicate BOOLEAN NOT NULL DEFAULT false,
  ADD COLUMN IF NOT EXISTS already_handled BOOLEAN NOT NULL DEFAULT false,
  ADD COLUMN IF NOT EXISTS rating SMALLINT,
  ADD COLUMN IF NOT EXISTS comment TEXT,
  ADD COLUMN IF NOT EXISTS feedback_version TEXT NOT NULL DEFAULT 'v1';

ALTER TABLE governance_ai_recommendation_feedback
  DROP CONSTRAINT IF EXISTS governance_ai_recommendation_feedback_rating_check;
ALTER TABLE governance_ai_recommendation_feedback
  ADD CONSTRAINT governance_ai_recommendation_feedback_rating_check
  CHECK (rating IS NULL OR (rating >= 1 AND rating <= 5));

CREATE TABLE IF NOT EXISTS governance_recommendation_lifecycle_events (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  org_id UUID NOT NULL REFERENCES organisations(id) ON DELETE RESTRICT,
  recommendation_id UUID NOT NULL REFERENCES governance_ai_recommendations(id) ON DELETE CASCADE,
  event_type governance_recommendation_lifecycle_event_type NOT NULL,
  actor_user_id UUID REFERENCES users(id) ON DELETE SET NULL,
  conversion_target TEXT,
  conversion_target_id UUID,
  metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS governance_recommendation_lifecycle_events_rec_idx
  ON governance_recommendation_lifecycle_events (recommendation_id, created_at DESC);

CREATE INDEX IF NOT EXISTS governance_recommendation_lifecycle_events_org_type_idx
  ON governance_recommendation_lifecycle_events (org_id, event_type, created_at DESC);

CREATE TABLE IF NOT EXISTS governance_recommendation_learning_rules (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  org_id UUID NOT NULL REFERENCES organisations(id) ON DELETE RESTRICT,
  rule_type TEXT NOT NULL,
  rule_payload JSONB NOT NULL DEFAULT '{}'::jsonb,
  version INTEGER NOT NULL DEFAULT 1,
  status governance_learning_rule_status NOT NULL DEFAULT 'draft',
  created_by_user_id UUID REFERENCES users(id) ON DELETE SET NULL,
  approved_by_user_id UUID REFERENCES users(id) ON DELETE SET NULL,
  approved_at TIMESTAMPTZ,
  reverted_by_user_id UUID REFERENCES users(id) ON DELETE SET NULL,
  reverted_at TIMESTAMPTZ,
  supersedes_rule_id UUID REFERENCES governance_recommendation_learning_rules(id) ON DELETE SET NULL,
  change_summary TEXT,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  deleted_at TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS governance_recommendation_learning_rules_org_status_idx
  ON governance_recommendation_learning_rules (org_id, status)
  WHERE deleted_at IS NULL;

ALTER TABLE governance_recommendation_lifecycle_events ENABLE ROW LEVEL SECURITY;
ALTER TABLE governance_recommendation_learning_rules ENABLE ROW LEVEL SECURITY;

CREATE POLICY governance_recommendation_lifecycle_events_internal_all
  ON governance_recommendation_lifecycle_events FOR ALL TO public
  USING (
    auth.jwt() ->> 'role' IN ('delivery_manager', 'bsg_leadership', 'super_admin')
    AND (
      auth.jwt() ->> 'role' = 'super_admin'
      OR org_id = (auth.jwt() ->> 'org_id')::uuid
    )
  )
  WITH CHECK (
    auth.jwt() ->> 'role' IN ('delivery_manager', 'bsg_leadership', 'super_admin')
    AND (
      auth.jwt() ->> 'role' = 'super_admin'
      OR org_id = (auth.jwt() ->> 'org_id')::uuid
    )
  );

CREATE POLICY governance_recommendation_learning_rules_internal_all
  ON governance_recommendation_learning_rules FOR ALL TO public
  USING (
    auth.jwt() ->> 'role' IN ('delivery_manager', 'bsg_leadership', 'super_admin')
    AND (
      auth.jwt() ->> 'role' = 'super_admin'
      OR org_id = (auth.jwt() ->> 'org_id')::uuid
    )
  )
  WITH CHECK (
    auth.jwt() ->> 'role' IN ('delivery_manager', 'bsg_leadership', 'super_admin')
    AND (
      auth.jwt() ->> 'role' = 'super_admin'
      OR org_id = (auth.jwt() ->> 'org_id')::uuid
    )
  );
