-- Delivery Performance Agent Phase 1: global scoring templates plus org overrides.
-- Existing rows remain global templates; no historical scores are rewritten.

ALTER TABLE metric_configurations
  ADD COLUMN IF NOT EXISTS org_id UUID REFERENCES organisations (id) ON DELETE CASCADE;

ALTER TABLE metric_configurations
  DROP CONSTRAINT IF EXISTS metric_configurations_metric_key_key;

CREATE UNIQUE INDEX IF NOT EXISTS metric_configurations_global_key_active_uidx
  ON metric_configurations (metric_key)
  WHERE org_id IS NULL AND deleted_at IS NULL;

CREATE UNIQUE INDEX IF NOT EXISTS metric_configurations_org_key_active_uidx
  ON metric_configurations (org_id, metric_key)
  WHERE org_id IS NOT NULL AND deleted_at IS NULL;

CREATE INDEX IF NOT EXISTS metric_configurations_org_id_idx
  ON metric_configurations (org_id);

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
      'delivery_confidence',
      'Delivery confidence thresholds',
      false,
      100,
      'Confidence band boundaries used by Delivery scoring.',
      '{"on_track": 80, "critical": 50}'::jsonb
    ),
    (
      'delivery_risk',
      'Delivery risk thresholds',
      false,
      110,
      'Risk bands, trend tolerance, and milestone warning window used by Delivery scoring.',
      '{"medium": 30, "high": 60, "critical": 85, "trend_tolerance": 5, "throughput_decline_tolerance": 0, "milestone_warning_window_days": 14}'::jsonb
    ),
    (
      'delivery_traffic_light',
      'Delivery traffic-light rules',
      false,
      120,
      'Combined deterministic rules for green, yellow, and red Delivery status.',
      '{"red_on_critical_confidence": true, "red_on_critical_risk": true, "red_on_critical_open_risk": true, "red_on_missed_milestone": true, "yellow_on_warning_confidence": true, "yellow_on_warning_risk": true, "yellow_on_warning_open_risk": true, "yellow_on_open_bottleneck": true}'::jsonb
    ),
    (
      'delivery_bottleneck',
      'Delivery bottleneck thresholds',
      false,
      130,
      'Reserved Phase 2 bottleneck observation and recovery thresholds; no detector is enabled.',
      '{"observation_days": 5, "decline_threshold_pct": 20, "recovery_days": 3}'::jsonb
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

DROP POLICY IF EXISTS metrics_read ON metric_configurations;
CREATE POLICY metrics_read ON metric_configurations FOR SELECT TO public
  USING (
    public.current_user_id() IS NOT NULL
    AND deleted_at IS NULL
    AND (
      org_id IS NULL
      OR org_id = public.auth_user_org_id()
      OR public.auth_user_role() = 'super_admin'
    )
  );

COMMENT ON COLUMN metric_configurations.org_id IS
  'NULL for global defaults; set for an organisation-specific override.';
