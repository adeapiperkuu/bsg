-- PM org-scoped communications inbox (GET /api/v1/communications) latency indexes.
-- Supports ORDER BY created_at DESC within an org, plus evidence-count aggregation.

CREATE INDEX IF NOT EXISTS client_communications_org_created_idx
  ON client_communications (org_id, created_at DESC);

-- ORM maps communication_id with index=True; initial migration did not create one.
CREATE INDEX IF NOT EXISTS communication_evidence_links_communication_idx
  ON communication_evidence_links (communication_id);
