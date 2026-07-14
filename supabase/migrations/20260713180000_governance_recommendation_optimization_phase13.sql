-- Phase 13: Controlled Recommendation Optimization
-- Strategy versions, shadow evaluations, drift alerts, scheduled reports,
-- lifecycle event extensions, learning-rule application metadata.
-- No automatic governance actions.

DO $$ BEGIN
  ALTER TYPE governance_recommendation_lifecycle_event_type ADD VALUE 'resolution_cancelled';
EXCEPTION WHEN duplicate_object THEN NULL;
END $$;

DO $$ BEGIN
  ALTER TYPE governance_recommendation_lifecycle_event_type ADD VALUE 'conversion_target_changed';
EXCEPTION WHEN duplicate_object THEN NULL;
END $$;

DO $$ BEGIN
  ALTER TYPE governance_learning_rule_status ADD VALUE 'shadow';
EXCEPTION WHEN duplicate_object THEN NULL;
END $$;

DO $$ BEGIN
  ALTER TYPE governance_learning_rule_status ADD VALUE 'disabled';
EXCEPTION WHEN duplicate_object THEN NULL;
END $$;

DO $$ BEGIN
  CREATE TYPE governance_recommendation_shadow_status AS ENUM (
    'pending',
    'running',
    'completed',
    'failed',
    'cancelled'
  );
EXCEPTION WHEN duplicate_object THEN NULL;
END $$;

DO $$ BEGIN
  CREATE TYPE governance_recommendation_evaluation_period AS ENUM (
    'weekly',
    'monthly',
    'quarterly'
  );
EXCEPTION WHEN duplicate_object THEN NULL;
END $$;

DO $$ BEGIN
  CREATE TYPE governance_recommendation_drift_severity AS ENUM (
    'info',
    'warning',
    'critical'
  );
EXCEPTION WHEN duplicate_object THEN NULL;
END $$;

-- Strategy version registry (org-scoped, reproducible)
CREATE TABLE IF NOT EXISTS governance_recommendation_strategy_versions (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  org_id UUID NOT NULL REFERENCES organisations(id) ON DELETE RESTRICT,
  strategy_version TEXT NOT NULL,
  confidence_version TEXT NOT NULL DEFAULT 'v1',
  quality_version TEXT NOT NULL DEFAULT 'v1',
  explanation_version TEXT NOT NULL DEFAULT 'v1',
  learning_rule_version TEXT,
  change_summary TEXT,
  is_active BOOLEAN NOT NULL DEFAULT false,
  activated_at TIMESTAMPTZ,
  activated_by_user_id UUID REFERENCES users(id) ON DELETE SET NULL,
  config_snapshot JSONB NOT NULL DEFAULT '{}'::jsonb,
  created_by_user_id UUID REFERENCES users(id) ON DELETE SET NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  deleted_at TIMESTAMPTZ,
  UNIQUE (org_id, strategy_version)
);

CREATE INDEX IF NOT EXISTS governance_recommendation_strategy_versions_org_active_idx
  ON governance_recommendation_strategy_versions (org_id, is_active)
  WHERE deleted_at IS NULL;

-- Shadow evaluations (never affect production rankings)
CREATE TABLE IF NOT EXISTS governance_recommendation_shadow_evaluations (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  org_id UUID NOT NULL REFERENCES organisations(id) ON DELETE RESTRICT,
  learning_rule_id UUID REFERENCES governance_recommendation_learning_rules(id) ON DELETE SET NULL,
  strategy_version_id UUID REFERENCES governance_recommendation_strategy_versions(id) ON DELETE SET NULL,
  status governance_recommendation_shadow_status NOT NULL DEFAULT 'pending',
  sample_size INTEGER NOT NULL DEFAULT 0,
  baseline_metrics JSONB NOT NULL DEFAULT '{}'::jsonb,
  shadow_metrics JSONB NOT NULL DEFAULT '{}'::jsonb,
  comparison_summary JSONB NOT NULL DEFAULT '{}'::jsonb,
  expected_impact JSONB NOT NULL DEFAULT '{}'::jsonb,
  started_at TIMESTAMPTZ,
  completed_at TIMESTAMPTZ,
  created_by_user_id UUID REFERENCES users(id) ON DELETE SET NULL,
  error_message TEXT,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS governance_recommendation_shadow_evaluations_org_status_idx
  ON governance_recommendation_shadow_evaluations (org_id, status, created_at DESC);

CREATE INDEX IF NOT EXISTS governance_recommendation_shadow_evaluations_rule_idx
  ON governance_recommendation_shadow_evaluations (learning_rule_id, created_at DESC);

-- Drift alerts (warnings only — no automatic rule changes)
CREATE TABLE IF NOT EXISTS governance_recommendation_drift_alerts (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  org_id UUID NOT NULL REFERENCES organisations(id) ON DELETE RESTRICT,
  alert_type TEXT NOT NULL,
  severity governance_recommendation_drift_severity NOT NULL DEFAULT 'warning',
  metric_name TEXT NOT NULL,
  baseline_value NUMERIC(12, 4),
  current_value NUMERIC(12, 4),
  threshold_value NUMERIC(12, 4),
  message TEXT NOT NULL,
  details JSONB NOT NULL DEFAULT '{}'::jsonb,
  strategy_version TEXT,
  acknowledged_at TIMESTAMPTZ,
  acknowledged_by_user_id UUID REFERENCES users(id) ON DELETE SET NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS governance_recommendation_drift_alerts_org_created_idx
  ON governance_recommendation_drift_alerts (org_id, created_at DESC);

CREATE INDEX IF NOT EXISTS governance_recommendation_drift_alerts_org_unacked_idx
  ON governance_recommendation_drift_alerts (org_id, created_at DESC)
  WHERE acknowledged_at IS NULL;

-- Scheduled / generated evaluation reports
CREATE TABLE IF NOT EXISTS governance_recommendation_evaluation_reports (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  org_id UUID NOT NULL REFERENCES organisations(id) ON DELETE RESTRICT,
  period governance_recommendation_evaluation_period NOT NULL,
  period_start DATE NOT NULL,
  period_end DATE NOT NULL,
  strategy_version TEXT,
  report_payload JSONB NOT NULL DEFAULT '{}'::jsonb,
  generated_by_user_id UUID REFERENCES users(id) ON DELETE SET NULL,
  generated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  UNIQUE (org_id, period, period_start, period_end)
);

CREATE INDEX IF NOT EXISTS governance_recommendation_evaluation_reports_org_period_idx
  ON governance_recommendation_evaluation_reports (org_id, period, generated_at DESC);

-- Recommendation reproducibility stamps
ALTER TABLE governance_ai_recommendations
  ADD COLUMN IF NOT EXISTS strategy_version TEXT NOT NULL DEFAULT 'v1',
  ADD COLUMN IF NOT EXISTS confidence_version TEXT NOT NULL DEFAULT 'v1',
  ADD COLUMN IF NOT EXISTS learning_rule_version TEXT,
  ADD COLUMN IF NOT EXISTS resolution_cancelled_at TIMESTAMPTZ,
  ADD COLUMN IF NOT EXISTS resolution_note TEXT;

CREATE INDEX IF NOT EXISTS governance_ai_recommendations_org_strategy_version_idx
  ON governance_ai_recommendations (org_id, strategy_version, generated_at DESC)
  WHERE deleted_at IS NULL;

-- Learning rule application / rollback metadata
ALTER TABLE governance_recommendation_learning_rules
  ADD COLUMN IF NOT EXISTS evaluation_mode TEXT NOT NULL DEFAULT 'none',
  ADD COLUMN IF NOT EXISTS shadow_evaluation_id UUID REFERENCES governance_recommendation_shadow_evaluations(id) ON DELETE SET NULL,
  ADD COLUMN IF NOT EXISTS activated_at TIMESTAMPTZ,
  ADD COLUMN IF NOT EXISTS activated_by_user_id UUID REFERENCES users(id) ON DELETE SET NULL,
  ADD COLUMN IF NOT EXISTS disabled_at TIMESTAMPTZ,
  ADD COLUMN IF NOT EXISTS disabled_by_user_id UUID REFERENCES users(id) ON DELETE SET NULL,
  ADD COLUMN IF NOT EXISTS config_snapshot JSONB NOT NULL DEFAULT '{}'::jsonb,
  ADD COLUMN IF NOT EXISTS previous_config_snapshot JSONB,
  ADD COLUMN IF NOT EXISTS performance_before JSONB,
  ADD COLUMN IF NOT EXISTS performance_after JSONB,
  ADD COLUMN IF NOT EXISTS allowed_effects TEXT[] NOT NULL DEFAULT ARRAY[
    'ranking',
    'confidence_adjustment',
    'duplicate_suppression',
    'cooldown',
    'explanation_strategy',
    'evidence_requirements'
  ]::TEXT[];

-- RLS
ALTER TABLE governance_recommendation_strategy_versions ENABLE ROW LEVEL SECURITY;
ALTER TABLE governance_recommendation_shadow_evaluations ENABLE ROW LEVEL SECURITY;
ALTER TABLE governance_recommendation_drift_alerts ENABLE ROW LEVEL SECURITY;
ALTER TABLE governance_recommendation_evaluation_reports ENABLE ROW LEVEL SECURITY;

CREATE POLICY governance_recommendation_strategy_versions_leadership_all
  ON governance_recommendation_strategy_versions FOR ALL TO public
  USING (
    auth.jwt() ->> 'role' IN ('bsg_leadership', 'super_admin')
    AND (
      auth.jwt() ->> 'role' = 'super_admin'
      OR org_id = (auth.jwt() ->> 'org_id')::uuid
    )
  )
  WITH CHECK (
    auth.jwt() ->> 'role' IN ('bsg_leadership', 'super_admin')
    AND (
      auth.jwt() ->> 'role' = 'super_admin'
      OR org_id = (auth.jwt() ->> 'org_id')::uuid
    )
  );

CREATE POLICY governance_recommendation_shadow_evaluations_leadership_all
  ON governance_recommendation_shadow_evaluations FOR ALL TO public
  USING (
    auth.jwt() ->> 'role' IN ('bsg_leadership', 'super_admin')
    AND (
      auth.jwt() ->> 'role' = 'super_admin'
      OR org_id = (auth.jwt() ->> 'org_id')::uuid
    )
  )
  WITH CHECK (
    auth.jwt() ->> 'role' IN ('bsg_leadership', 'super_admin')
    AND (
      auth.jwt() ->> 'role' = 'super_admin'
      OR org_id = (auth.jwt() ->> 'org_id')::uuid
    )
  );

CREATE POLICY governance_recommendation_drift_alerts_leadership_all
  ON governance_recommendation_drift_alerts FOR ALL TO public
  USING (
    auth.jwt() ->> 'role' IN ('bsg_leadership', 'super_admin')
    AND (
      auth.jwt() ->> 'role' = 'super_admin'
      OR org_id = (auth.jwt() ->> 'org_id')::uuid
    )
  )
  WITH CHECK (
    auth.jwt() ->> 'role' IN ('bsg_leadership', 'super_admin')
    AND (
      auth.jwt() ->> 'role' = 'super_admin'
      OR org_id = (auth.jwt() ->> 'org_id')::uuid
    )
  );

CREATE POLICY governance_recommendation_evaluation_reports_leadership_all
  ON governance_recommendation_evaluation_reports FOR ALL TO public
  USING (
    auth.jwt() ->> 'role' IN ('bsg_leadership', 'super_admin')
    AND (
      auth.jwt() ->> 'role' = 'super_admin'
      OR org_id = (auth.jwt() ->> 'org_id')::uuid
    )
  )
  WITH CHECK (
    auth.jwt() ->> 'role' IN ('bsg_leadership', 'super_admin')
    AND (
      auth.jwt() ->> 'role' = 'super_admin'
      OR org_id = (auth.jwt() ->> 'org_id')::uuid
    )
  );
