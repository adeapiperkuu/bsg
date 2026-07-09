-- Add source linkage columns to risk_alerts for idempotent alert creation
ALTER TABLE risk_alerts ADD COLUMN IF NOT EXISTS source_table TEXT;
ALTER TABLE risk_alerts ADD COLUMN IF NOT EXISTS source_row_id UUID;
CREATE INDEX IF NOT EXISTS risk_alerts_source_idx ON risk_alerts (source_table, source_row_id);
