-- Client Intelligence evidence provenance + stale-approval fingerprint.
-- Forward-only, nullable legacy fields. Do not fabricate historical provenance.
-- Deduplicate legacy evidence links before unique indexes so upgrades succeed.

ALTER TABLE client_communications
  ADD COLUMN IF NOT EXISTS evidence_source_fingerprint TEXT;

ALTER TABLE client_communications
  DROP CONSTRAINT IF EXISTS client_communications_evidence_source_fingerprint_check;

ALTER TABLE client_communications
  ADD CONSTRAINT client_communications_evidence_source_fingerprint_check
  CHECK (
    evidence_source_fingerprint IS NULL
    OR evidence_source_fingerprint ~ '^[0-9a-f]{64}$'
  );

CREATE INDEX IF NOT EXISTS client_communications_evidence_source_fingerprint_idx
  ON client_communications (evidence_source_fingerprint)
  WHERE evidence_source_fingerprint IS NOT NULL;

ALTER TABLE communication_evidence_links
  ADD COLUMN IF NOT EXISTS visibility TEXT,
  ADD COLUMN IF NOT EXISTS observed_at TIMESTAMPTZ,
  ADD COLUMN IF NOT EXISTS claim_keys JSONB NOT NULL DEFAULT '[]'::jsonb,
  ADD COLUMN IF NOT EXISTS pack_source_fingerprint TEXT;

ALTER TABLE communication_evidence_links
  DROP CONSTRAINT IF EXISTS communication_evidence_links_visibility_check;

ALTER TABLE communication_evidence_links
  ADD CONSTRAINT communication_evidence_links_visibility_check
  CHECK (visibility IS NULL OR visibility IN ('internal', 'client_safe'));

ALTER TABLE communication_evidence_links
  DROP CONSTRAINT IF EXISTS communication_evidence_links_claim_keys_check;

ALTER TABLE communication_evidence_links
  ADD CONSTRAINT communication_evidence_links_claim_keys_check
  CHECK (jsonb_typeof(claim_keys) = 'array');

ALTER TABLE communication_evidence_links
  DROP CONSTRAINT IF EXISTS communication_evidence_links_pack_source_fingerprint_check;

ALTER TABLE communication_evidence_links
  ADD CONSTRAINT communication_evidence_links_pack_source_fingerprint_check
  CHECK (
    pack_source_fingerprint IS NULL
    OR pack_source_fingerprint ~ '^[0-9a-f]{64}$'
  );

-- Keep the oldest canonical row per (communication_id, source_table, source_row_id).
-- Do not invent provenance while deduplicating.
DELETE FROM communication_evidence_links AS duplicate
USING communication_evidence_links AS canonical
WHERE duplicate.communication_id = canonical.communication_id
  AND duplicate.source_table = canonical.source_table
  AND duplicate.source_row_id = canonical.source_row_id
  AND (
    duplicate.created_at > canonical.created_at
    OR (
      duplicate.created_at = canonical.created_at
      AND duplicate.id > canonical.id
    )
  );

CREATE UNIQUE INDEX IF NOT EXISTS communication_evidence_links_parent_source_uidx
  ON communication_evidence_links (communication_id, source_table, source_row_id);

CREATE INDEX IF NOT EXISTS communication_evidence_links_source_idx
  ON communication_evidence_links (source_table, source_row_id);

ALTER TABLE agent_query_evidence_links
  ADD COLUMN IF NOT EXISTS visibility TEXT,
  ADD COLUMN IF NOT EXISTS observed_at TIMESTAMPTZ,
  ADD COLUMN IF NOT EXISTS claim_keys JSONB NOT NULL DEFAULT '[]'::jsonb,
  ADD COLUMN IF NOT EXISTS pack_source_fingerprint TEXT;

ALTER TABLE agent_query_evidence_links
  DROP CONSTRAINT IF EXISTS agent_query_evidence_links_visibility_check;

ALTER TABLE agent_query_evidence_links
  ADD CONSTRAINT agent_query_evidence_links_visibility_check
  CHECK (visibility IS NULL OR visibility IN ('internal', 'client_safe'));

ALTER TABLE agent_query_evidence_links
  DROP CONSTRAINT IF EXISTS agent_query_evidence_links_claim_keys_check;

ALTER TABLE agent_query_evidence_links
  ADD CONSTRAINT agent_query_evidence_links_claim_keys_check
  CHECK (jsonb_typeof(claim_keys) = 'array');

ALTER TABLE agent_query_evidence_links
  DROP CONSTRAINT IF EXISTS agent_query_evidence_links_pack_source_fingerprint_check;

ALTER TABLE agent_query_evidence_links
  ADD CONSTRAINT agent_query_evidence_links_pack_source_fingerprint_check
  CHECK (
    pack_source_fingerprint IS NULL
    OR pack_source_fingerprint ~ '^[0-9a-f]{64}$'
  );

DELETE FROM agent_query_evidence_links AS duplicate
USING agent_query_evidence_links AS canonical
WHERE duplicate.agent_query_id = canonical.agent_query_id
  AND duplicate.source_table = canonical.source_table
  AND duplicate.source_row_id = canonical.source_row_id
  AND (
    duplicate.created_at > canonical.created_at
    OR (
      duplicate.created_at = canonical.created_at
      AND duplicate.id > canonical.id
    )
  );

CREATE UNIQUE INDEX IF NOT EXISTS agent_query_evidence_links_parent_source_uidx
  ON agent_query_evidence_links (agent_query_id, source_table, source_row_id);

CREATE INDEX IF NOT EXISTS agent_query_evidence_links_source_idx
  ON agent_query_evidence_links (source_table, source_row_id);

-- RLS policies for these tables are owned by earlier migrations and are unchanged.
-- Provenance columns remain subject to the same tenant policies; this migration
-- does not create a cross-tenant policy bypass.
