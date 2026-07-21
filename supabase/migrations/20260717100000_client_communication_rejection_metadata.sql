-- Forward-only rejection metadata for client communication lifecycle.
ALTER TABLE client_communications
  ADD COLUMN IF NOT EXISTS rejection_reason TEXT,
  ADD COLUMN IF NOT EXISTS rejected_by UUID REFERENCES users (id) ON DELETE SET NULL,
  ADD COLUMN IF NOT EXISTS rejected_at TIMESTAMPTZ;

CREATE INDEX IF NOT EXISTS client_communications_rejected_by_idx
  ON client_communications (rejected_by)
  WHERE rejected_by IS NOT NULL;
