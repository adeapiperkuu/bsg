-- Delivery Performance Agent Phase 15.1: deterministic root-cause intelligence.
-- Explains confidence loss; does not replace scoring. No client RLS on raw tables.

-- Composite FK (project_id, org_id) needs unique (id, org_id). Idempotent if Phase 2
-- (team throughput) already created this index.
CREATE UNIQUE INDEX IF NOT EXISTS projects_id_org_uidx
  ON projects (id, org_id);

CREATE TABLE delivery_root_cause_snapshots (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  org_id UUID NOT NULL REFERENCES organisations (id) ON DELETE RESTRICT,
  project_id UUID NOT NULL,
  snapshot_date DATE NOT NULL,
  overall_confidence NUMERIC(5, 2) NOT NULL
    CHECK (overall_confidence >= 0 AND overall_confidence <= 100),
  confidence_loss NUMERIC(5, 2) NOT NULL
    CHECK (confidence_loss >= 0 AND confidence_loss <= 100),
  model_version TEXT NOT NULL DEFAULT 'delivery_root_cause_v1',
  generated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  CONSTRAINT delivery_root_cause_snapshots_project_org_fkey
    FOREIGN KEY (project_id, org_id)
    REFERENCES projects (id, org_id) ON DELETE CASCADE,
  CONSTRAINT delivery_root_cause_snapshots_project_date_key
    UNIQUE (project_id, snapshot_date)
);

CREATE INDEX delivery_root_cause_snapshots_org_date_idx
  ON delivery_root_cause_snapshots (org_id, snapshot_date DESC);

CREATE INDEX delivery_root_cause_snapshots_project_date_idx
  ON delivery_root_cause_snapshots (project_id, snapshot_date DESC);

CREATE TRIGGER delivery_root_cause_snapshots_updated_at
  BEFORE UPDATE ON delivery_root_cause_snapshots
  FOR EACH ROW EXECUTE FUNCTION set_updated_at();

CREATE TABLE delivery_root_cause_factors (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  snapshot_id UUID NOT NULL REFERENCES delivery_root_cause_snapshots (id) ON DELETE CASCADE,
  factor TEXT NOT NULL,
  impact_percent NUMERIC(5, 2) NOT NULL
    CHECK (impact_percent >= 0 AND impact_percent <= 100),
  impact_points NUMERIC(6, 2) NOT NULL,
  severity risk_tier NOT NULL DEFAULT 'low',
  explanation TEXT NOT NULL,
  evidence_json JSONB NOT NULL DEFAULT '{}'::jsonb,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  CONSTRAINT delivery_root_cause_factors_snapshot_factor_key
    UNIQUE (snapshot_id, factor)
);

CREATE INDEX delivery_root_cause_factors_snapshot_idx
  ON delivery_root_cause_factors (snapshot_id);

CREATE INDEX delivery_root_cause_factors_factor_idx
  ON delivery_root_cause_factors (factor);

ALTER TABLE delivery_root_cause_snapshots ENABLE ROW LEVEL SECURITY;
ALTER TABLE delivery_root_cause_factors ENABLE ROW LEVEL SECURITY;

CREATE POLICY delivery_root_cause_snapshots_dm_all
  ON delivery_root_cause_snapshots FOR ALL TO public
  USING (
    public.auth_user_role() = 'delivery_manager'
    AND org_id = public.auth_user_org_id()
  )
  WITH CHECK (
    public.auth_user_role() = 'delivery_manager'
    AND org_id = public.auth_user_org_id()
    AND EXISTS (
      SELECT 1 FROM projects p
      WHERE p.id = project_id AND p.org_id = org_id AND p.deleted_at IS NULL
    )
  );

CREATE POLICY delivery_root_cause_snapshots_leadership_select
  ON delivery_root_cause_snapshots FOR SELECT TO public
  USING (
    public.auth_user_role() = 'bsg_leadership'
    AND org_id = public.auth_user_org_id()
  );

CREATE POLICY delivery_root_cause_snapshots_super_admin_all
  ON delivery_root_cause_snapshots FOR ALL TO public
  USING (public.auth_user_role() = 'super_admin')
  WITH CHECK (public.auth_user_role() = 'super_admin');

CREATE POLICY delivery_root_cause_factors_dm_all
  ON delivery_root_cause_factors FOR ALL TO public
  USING (
    public.auth_user_role() = 'delivery_manager'
    AND EXISTS (
      SELECT 1 FROM delivery_root_cause_snapshots s
      WHERE s.id = snapshot_id
        AND s.org_id = public.auth_user_org_id()
    )
  )
  WITH CHECK (
    public.auth_user_role() = 'delivery_manager'
    AND EXISTS (
      SELECT 1 FROM delivery_root_cause_snapshots s
      WHERE s.id = snapshot_id
        AND s.org_id = public.auth_user_org_id()
    )
  );

CREATE POLICY delivery_root_cause_factors_leadership_select
  ON delivery_root_cause_factors FOR SELECT TO public
  USING (
    public.auth_user_role() = 'bsg_leadership'
    AND EXISTS (
      SELECT 1 FROM delivery_root_cause_snapshots s
      WHERE s.id = snapshot_id
        AND s.org_id = public.auth_user_org_id()
    )
  );

CREATE POLICY delivery_root_cause_factors_super_admin_all
  ON delivery_root_cause_factors FOR ALL TO public
  USING (public.auth_user_role() = 'super_admin')
  WITH CHECK (public.auth_user_role() = 'super_admin');

INSERT INTO metric_configurations (
  metric_key,
  display_label,
  is_client_visible,
  display_order,
  description,
  threshold_config
)
SELECT values_to_add.*
FROM (
  VALUES
    (
      'delivery_root_cause',
      'Delivery root-cause weights',
      false,
      140,
      'Configurable factor weights and severity bands for Delivery root-cause intelligence.',
      '{
        "weights": {
          "review_turnaround": 0.25,
          "rework": 0.20,
          "capacity": 0.15,
          "queue": 0.10,
          "blocked_work": 0.10,
          "milestone_slippage": 0.08,
          "quality_regression": 0.07,
          "absenteeism": 0.03,
          "dependency_delays": 0.01,
          "scope_volatility": 0.01
        },
        "severity_medium_points": 3,
        "severity_high_points": 6,
        "severity_critical_points": 10
      }'::jsonb
    )
) AS values_to_add (
  metric_key,
  display_label,
  is_client_visible,
  display_order,
  description,
  threshold_config
)
WHERE NOT EXISTS (
  SELECT 1
  FROM metric_configurations existing
  WHERE existing.metric_key = values_to_add.metric_key
    AND existing.org_id IS NULL
    AND existing.deleted_at IS NULL
);

COMMENT ON TABLE delivery_root_cause_snapshots IS
  'Daily deterministic root-cause breakdown explaining delivery confidence loss.';

COMMENT ON TABLE delivery_root_cause_factors IS
  'Per-factor impact rows for a delivery_root_cause_snapshots row.';
