-- Project Governance Agent - Phase 7: AI recommendation conversions

CREATE TYPE governance_recommendation_acceptance_status AS ENUM (
  'not_accepted',
  'partially_accepted',
  'accepted_as_action',
  'accepted_as_escalation'
);

CREATE TYPE governance_recommendation_conversion_target AS ENUM (
  'action',
  'escalation'
);

ALTER TABLE governance_ai_recommendations
  ADD COLUMN acceptance_status governance_recommendation_acceptance_status NOT NULL DEFAULT 'not_accepted',
  ADD COLUMN accepted_at TIMESTAMPTZ,
  ADD COLUMN accepted_by_user_id UUID REFERENCES users (id) ON DELETE SET NULL,
  ADD COLUMN converted_action_id UUID REFERENCES governance_actions (id) ON DELETE SET NULL,
  ADD COLUMN converted_escalation_id UUID REFERENCES governance_escalations (id) ON DELETE SET NULL,
  ADD COLUMN accepted_suggested_action_index INTEGER,
  ADD COLUMN acceptance_note TEXT;

CREATE TABLE governance_ai_recommendation_conversions (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  org_id UUID NOT NULL REFERENCES organisations (id) ON DELETE RESTRICT,
  recommendation_id UUID NOT NULL REFERENCES governance_ai_recommendations (id) ON DELETE CASCADE,
  suggested_action_index INTEGER NOT NULL,
  conversion_target governance_recommendation_conversion_target NOT NULL,
  created_action_id UUID REFERENCES governance_actions (id) ON DELETE SET NULL,
  created_escalation_id UUID REFERENCES governance_escalations (id) ON DELETE SET NULL,
  created_by_user_id UUID REFERENCES users (id) ON DELETE SET NULL,
  request_fingerprint TEXT NOT NULL,
  idempotency_key TEXT,
  note TEXT,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  CONSTRAINT governance_ai_recommendation_conversions_suggestion_key
    UNIQUE (recommendation_id, suggested_action_index),
  CONSTRAINT governance_ai_recommendation_conversions_idempotency_key
    UNIQUE (org_id, idempotency_key),
  CONSTRAINT governance_ai_recommendation_conversions_target_record_check CHECK (
    (conversion_target = 'action' AND created_action_id IS NOT NULL AND created_escalation_id IS NULL)
    OR
    (conversion_target = 'escalation' AND created_escalation_id IS NOT NULL AND created_action_id IS NULL)
  )
);

CREATE INDEX governance_ai_recommendation_conversions_recommendation_idx
  ON governance_ai_recommendation_conversions (recommendation_id);

CREATE INDEX governance_ai_recommendation_conversions_org_idx
  ON governance_ai_recommendation_conversions (org_id);

ALTER TABLE governance_ai_recommendation_conversions ENABLE ROW LEVEL SECURITY;

CREATE POLICY governance_ai_recommendation_conversions_dm_all
  ON governance_ai_recommendation_conversions FOR ALL TO public
  USING (
    public.auth_user_role() = 'delivery_manager'
    AND org_id = public.auth_user_org_id()
  )
  WITH CHECK (
    public.auth_user_role() = 'delivery_manager'
    AND org_id = public.auth_user_org_id()
  );

CREATE POLICY governance_ai_recommendation_conversions_leadership_select
  ON governance_ai_recommendation_conversions FOR SELECT TO public
  USING (public.auth_user_role() = 'bsg_leadership');

CREATE POLICY governance_ai_recommendation_conversions_leadership_write
  ON governance_ai_recommendation_conversions FOR INSERT TO public
  WITH CHECK (public.auth_user_role() = 'bsg_leadership');

CREATE POLICY governance_ai_recommendation_conversions_super_admin_all
  ON governance_ai_recommendation_conversions FOR ALL TO public
  USING (public.auth_user_role() = 'super_admin')
  WITH CHECK (public.auth_user_role() = 'super_admin');
