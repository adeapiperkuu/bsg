-- Delivery Performance Agent Phase 15.3: PM Daily Action Planner.
-- Ranked day-scoped focus list. Complements mitigation_recommendations (does not replace).

-- Composite FK (project_id, org_id) needs unique (id, org_id). Idempotent if earlier
-- Delivery migrations already created this index.
CREATE UNIQUE INDEX IF NOT EXISTS projects_id_org_uidx
  ON projects (id, org_id);

CREATE TYPE pm_daily_action_status AS ENUM (
  'todo',
  'done',
  'skipped',
  'deferred'
);

CREATE TYPE pm_daily_action_source_type AS ENUM (
  'root_cause_factor',
  'risk_alert',
  'bottleneck',
  'mitigation',
  'milestone'
);

CREATE TYPE pm_daily_action_urgency AS ENUM (
  'low',
  'medium',
  'high',
  'critical'
);

CREATE TABLE delivery_pm_daily_actions (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  org_id UUID NOT NULL,
  project_id UUID NOT NULL,
  plan_date DATE NOT NULL,
  rank INTEGER NOT NULL CHECK (rank >= 1),
  title TEXT NOT NULL CHECK (char_length(title) BETWEEN 1 AND 300),
  description TEXT CHECK (char_length(description) <= 4000),
  deterministic_rationale TEXT NOT NULL CHECK (char_length(deterministic_rationale) BETWEEN 1 AND 4000),
  ai_rationale TEXT CHECK (ai_rationale IS NULL OR char_length(ai_rationale) <= 4000),
  urgency pm_daily_action_urgency NOT NULL DEFAULT 'medium',
  estimated_impact_points NUMERIC(6, 2) NOT NULL DEFAULT 0
    CHECK (estimated_impact_points >= 0 AND estimated_impact_points <= 100),
  due_date DATE NOT NULL,
  status pm_daily_action_status NOT NULL DEFAULT 'todo',
  source_type pm_daily_action_source_type NOT NULL,
  source_key TEXT NOT NULL CHECK (char_length(source_key) BETWEEN 1 AND 500),
  root_cause_factor TEXT,
  mitigation_recommendation_id UUID REFERENCES mitigation_recommendations (id) ON DELETE SET NULL,
  evidence_json JSONB NOT NULL DEFAULT '{}'::jsonb,
  completed_at TIMESTAMPTZ,
  completed_by UUID REFERENCES users (id) ON DELETE SET NULL,
  completion_note TEXT CHECK (completion_note IS NULL OR char_length(completion_note) <= 2000),
  model_version TEXT NOT NULL DEFAULT 'pm_daily_action_v1',
  generated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  deleted_at TIMESTAMPTZ,
  CONSTRAINT delivery_pm_daily_actions_project_org_fkey
    FOREIGN KEY (project_id, org_id) REFERENCES projects (id, org_id) ON DELETE CASCADE
);

-- One open logical action per source per project/day (history rows keep completed/skipped).
CREATE UNIQUE INDEX delivery_pm_daily_actions_open_source_uidx
  ON delivery_pm_daily_actions (project_id, plan_date, source_key)
  WHERE deleted_at IS NULL AND status = 'todo';

CREATE INDEX delivery_pm_daily_actions_org_plan_date_idx
  ON delivery_pm_daily_actions (org_id, plan_date DESC);

CREATE INDEX delivery_pm_daily_actions_project_plan_date_idx
  ON delivery_pm_daily_actions (project_id, plan_date DESC, rank);

CREATE INDEX delivery_pm_daily_actions_project_status_idx
  ON delivery_pm_daily_actions (project_id, status)
  WHERE deleted_at IS NULL;

CREATE TRIGGER delivery_pm_daily_actions_updated_at
  BEFORE UPDATE ON delivery_pm_daily_actions
  FOR EACH ROW EXECUTE FUNCTION set_updated_at();

ALTER TABLE delivery_pm_daily_actions ENABLE ROW LEVEL SECURITY;

CREATE POLICY delivery_pm_daily_actions_dm_all
  ON delivery_pm_daily_actions FOR ALL TO public
  USING (
    public.auth_user_role() = 'delivery_manager'
    AND org_id = public.auth_user_org_id()
  )
  WITH CHECK (
    public.auth_user_role() = 'delivery_manager'
    AND org_id = public.auth_user_org_id()
  );

CREATE POLICY delivery_pm_daily_actions_leadership_select
  ON delivery_pm_daily_actions FOR SELECT TO public
  USING (
    public.auth_user_role() = 'bsg_leadership'
    AND org_id = public.auth_user_org_id()
  );

CREATE POLICY delivery_pm_daily_actions_super_admin_all
  ON delivery_pm_daily_actions FOR ALL TO public
  USING (public.auth_user_role() = 'super_admin')
  WITH CHECK (public.auth_user_role() = 'super_admin');

COMMENT ON TABLE delivery_pm_daily_actions IS
  'Phase 15.3 ranked PM daily focus actions. Deterministic ranking; optional AI rationale grounded in evidence_json.';
