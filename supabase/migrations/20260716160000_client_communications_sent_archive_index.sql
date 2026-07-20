-- Client published archive (GET /api/v1/client/communications) latency index.
-- Supports org-scoped sent-only listing ordered by sent_at / created_at.

CREATE INDEX IF NOT EXISTS client_communications_org_sent_idx
  ON client_communications (org_id, status, sent_at DESC NULLS LAST, created_at DESC);
