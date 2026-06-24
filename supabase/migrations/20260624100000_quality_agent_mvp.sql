-- Quality Intelligence Agent MVP schema extensions

ALTER TABLE quality_snapshots
  ADD COLUMN IF NOT EXISTS evaluated_item_count INT CHECK (evaluated_item_count >= 0),
  ADD COLUMN IF NOT EXISTS root_cause JSONB,
  ADD COLUMN IF NOT EXISTS confidence_level TEXT CHECK (confidence_level IN ('high', 'medium', 'low'));

ALTER TABLE metric_configurations
  ADD COLUMN IF NOT EXISTS threshold_config JSONB;
