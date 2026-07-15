-- Project Governance Agent — Phase 6: Grounded AI Recommendations

CREATE TYPE governance_ai_recommendation_scope AS ENUM ('project', 'portfolio');

CREATE TYPE governance_ai_recommendation_type AS ENUM (
  'dependency_mitigation',
  'escalation_required',
  'action_follow_up',
  'scope_control',
  'delivery_risk',
  'milestone_risk',
  'ownership_alignment',
  'governance_cadence',
  'portfolio_pattern',
  'resource_or_team_signal',
  'general_governance'
);

CREATE TYPE governance_ai_recommendation_priority AS ENUM (
  'low',
  'medium',
  'high',
  'critical'
);

CREATE TYPE governance_ai_recommendation_status AS ENUM (
  'active',
  'dismissed',
  'superseded',
  'generation_failed',
  'stale'
);

CREATE TABLE governance_ai_recommendations (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  org_id UUID NOT NULL REFERENCES organisations (id) ON DELETE RESTRICT,
  project_id UUID REFERENCES projects (id) ON DELETE CASCADE,
  scope governance_ai_recommendation_scope NOT NULL,
  recommendation_type governance_ai_recommendation_type NOT NULL,
  title TEXT NOT NULL,
  narrative TEXT NOT NULL,
  rationale TEXT NOT NULL,
  priority governance_ai_recommendation_priority NOT NULL DEFAULT 'medium',
  confidence NUMERIC(4, 3) NOT NULL,
  status governance_ai_recommendation_status NOT NULL DEFAULT 'active',
  suggested_actions JSONB NOT NULL DEFAULT '[]'::jsonb,
  evidence_refs JSONB NOT NULL DEFAULT '[]'::jsonb,
  evidence_hash TEXT NOT NULL,
  fingerprint TEXT NOT NULL,
  source_snapshot JSONB NOT NULL DEFAULT '{}'::jsonb,
  model_name TEXT,
  model_version TEXT,
  prompt_version TEXT NOT NULL,
  generation_request_id UUID,
  generated_by_user_id UUID REFERENCES users (id) ON DELETE SET NULL,
  dismissed_by_user_id UUID REFERENCES users (id) ON DELETE SET NULL,
  dismissed_at TIMESTAMPTZ,
  dismiss_reason TEXT,
  expires_at TIMESTAMPTZ,
  generated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  deleted_at TIMESTAMPTZ,
  CONSTRAINT governance_ai_recommendations_scope_project_check CHECK (
    (scope = 'project' AND project_id IS NOT NULL)
    OR (scope = 'portfolio' AND project_id IS NULL)
  ),
  CONSTRAINT governance_ai_recommendations_confidence_check CHECK (
    confidence >= 0 AND confidence <= 1
  )
);

CREATE INDEX governance_ai_recommendations_org_status_generated_idx
  ON governance_ai_recommendations (org_id, status, generated_at DESC)
  WHERE deleted_at IS NULL;

CREATE INDEX governance_ai_recommendations_org_project_status_idx
  ON governance_ai_recommendations (org_id, project_id, status)
  WHERE deleted_at IS NULL;

CREATE INDEX governance_ai_recommendations_evidence_hash_idx
  ON governance_ai_recommendations (org_id, evidence_hash)
  WHERE deleted_at IS NULL;

CREATE UNIQUE INDEX governance_ai_recommendations_active_fingerprint_uidx
  ON governance_ai_recommendations (org_id, fingerprint)
  WHERE deleted_at IS NULL AND status = 'active';

CREATE INDEX governance_ai_recommendations_generation_key_idx
  ON governance_ai_recommendations (org_id, scope, project_id, evidence_hash, prompt_version)
  WHERE deleted_at IS NULL AND status = 'active';

CREATE TRIGGER governance_ai_recommendations_updated_at
  BEFORE UPDATE ON governance_ai_recommendations
  FOR EACH ROW EXECUTE FUNCTION set_updated_at();

CREATE TABLE governance_ai_recommendation_feedback (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  recommendation_id UUID NOT NULL REFERENCES governance_ai_recommendations (id) ON DELETE CASCADE,
  org_id UUID NOT NULL REFERENCES organisations (id) ON DELETE RESTRICT,
  user_id UUID NOT NULL REFERENCES users (id) ON DELETE RESTRICT,
  helpful BOOLEAN NOT NULL,
  reason TEXT,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  CONSTRAINT governance_ai_recommendation_feedback_user_key UNIQUE (recommendation_id, user_id)
);

CREATE INDEX governance_ai_recommendation_feedback_recommendation_idx
  ON governance_ai_recommendation_feedback (recommendation_id);

CREATE INDEX governance_ai_recommendation_feedback_org_idx
  ON governance_ai_recommendation_feedback (org_id);

ALTER TABLE governance_ai_recommendations ENABLE ROW LEVEL SECURITY;
ALTER TABLE governance_ai_recommendation_feedback ENABLE ROW LEVEL SECURITY;

CREATE POLICY governance_ai_recommendations_dm_all ON governance_ai_recommendations FOR ALL TO public
  USING (
    public.auth_user_role() = 'delivery_manager'
    AND org_id = public.auth_user_org_id()
  )
  WITH CHECK (
    public.auth_user_role() = 'delivery_manager'
    AND org_id = public.auth_user_org_id()
  );

CREATE POLICY governance_ai_recommendations_leadership_select ON governance_ai_recommendations FOR SELECT TO public
  USING (
    public.auth_user_role() = 'bsg_leadership'
    AND deleted_at IS NULL
  );

CREATE POLICY governance_ai_recommendations_leadership_write ON governance_ai_recommendations FOR INSERT TO public
  WITH CHECK (public.auth_user_role() = 'bsg_leadership');

CREATE POLICY governance_ai_recommendations_leadership_update ON governance_ai_recommendations FOR UPDATE TO public
  USING (public.auth_user_role() = 'bsg_leadership')
  WITH CHECK (public.auth_user_role() = 'bsg_leadership');

CREATE POLICY governance_ai_recommendations_super_admin_all ON governance_ai_recommendations FOR ALL TO public
  USING (public.auth_user_role() = 'super_admin')
  WITH CHECK (public.auth_user_role() = 'super_admin');

CREATE POLICY governance_ai_recommendation_feedback_read ON governance_ai_recommendation_feedback FOR SELECT TO public
  USING (
    public.auth_user_role() IN ('bsg_leadership', 'super_admin')
    OR (
      org_id = public.auth_user_org_id()
      AND user_id = public.current_user_id()
    )
  );

CREATE POLICY governance_ai_recommendation_feedback_insert ON governance_ai_recommendation_feedback FOR INSERT TO public
  WITH CHECK (
    org_id = public.auth_user_org_id()
    AND user_id = public.current_user_id()
    AND public.auth_user_role() IN ('delivery_manager', 'bsg_leadership', 'super_admin')
  );

CREATE POLICY governance_ai_recommendation_feedback_update ON governance_ai_recommendation_feedback FOR UPDATE TO public
  USING (
    org_id = public.auth_user_org_id()
    AND user_id = public.current_user_id()
    AND public.auth_user_role() IN ('delivery_manager', 'bsg_leadership', 'super_admin')
  )
  WITH CHECK (
    org_id = public.auth_user_org_id()
    AND user_id = public.current_user_id()
    AND public.auth_user_role() IN ('delivery_manager', 'bsg_leadership', 'super_admin')
  );

CREATE POLICY governance_ai_recommendation_feedback_super_admin_all ON governance_ai_recommendation_feedback FOR ALL TO public
  USING (public.auth_user_role() = 'super_admin')
  WITH CHECK (public.auth_user_role() = 'super_admin');
