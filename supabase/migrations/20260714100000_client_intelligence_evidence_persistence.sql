-- Client Intelligence Phase 1 — validated evidence-pack snapshot persistence substrate.
-- Does NOT create readiness assessments, insights, recommendations, or report tables
-- (CI-DQ08 / Phase 2+ remain unresolved).
-- Append-only: SELECT + INSERT policies only (no UPDATE/DELETE policies).

CREATE TABLE client_intelligence_snapshots (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  org_id UUID NOT NULL REFERENCES organisations (id) ON DELETE RESTRICT,
  project_id UUID NOT NULL REFERENCES projects (id) ON DELETE CASCADE,
  reporting_period_start DATE NOT NULL,
  reporting_period_end DATE NOT NULL,
  reporting_period_previous_start DATE NOT NULL,
  reporting_period_previous_end DATE NOT NULL,
  reporting_period_as_of DATE NOT NULL,
  visibility_mode TEXT NOT NULL
    CHECK (visibility_mode IN ('internal', 'client_safe')),
  source_fingerprint TEXT NOT NULL
    CHECK (source_fingerprint ~ '^[0-9a-f]{64}$'),
  policy_fingerprint TEXT
    CHECK (
      policy_fingerprint IS NULL
      OR policy_fingerprint ~ '^[0-9a-f]{64}$'
    ),
  overall_data_quality TEXT NOT NULL
    CHECK (
      overall_data_quality IN (
        'complete',
        'partial',
        'stale',
        'conflicting',
        'unavailable'
      )
    ),
  pack_payload JSONB NOT NULL,
  generated_at TIMESTAMPTZ NOT NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  created_by UUID REFERENCES users (id) ON DELETE SET NULL,
  -- Parent identity for composite evidence-link FK (id alone is PK; this uniqueness
  -- guarantees link org/project/fingerprint must match the snapshot row).
  CONSTRAINT client_intelligence_snapshots_link_identity_key UNIQUE (
    id,
    org_id,
    project_id,
    source_fingerprint
  ),
  -- Idempotency: include policy_fingerprint with NULLS NOT DISTINCT so NULL policies
  -- collide with NULL and remain distinct from non-NULL policies.
  CONSTRAINT client_intelligence_snapshots_idempotency_key
    UNIQUE NULLS NOT DISTINCT (
      org_id,
      project_id,
      visibility_mode,
      reporting_period_start,
      reporting_period_end,
      reporting_period_previous_start,
      reporting_period_previous_end,
      reporting_period_as_of,
      source_fingerprint,
      policy_fingerprint
    )
);

CREATE INDEX client_intelligence_snapshots_org_id_idx
  ON client_intelligence_snapshots (org_id);
CREATE INDEX client_intelligence_snapshots_project_id_idx
  ON client_intelligence_snapshots (project_id, created_at DESC);
CREATE INDEX client_intelligence_snapshots_org_project_period_idx
  ON client_intelligence_snapshots (
    org_id,
    project_id,
    reporting_period_as_of,
    visibility_mode
  );
CREATE INDEX client_intelligence_snapshots_fingerprint_idx
  ON client_intelligence_snapshots (org_id, source_fingerprint);

CREATE TABLE client_intelligence_evidence_links (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  org_id UUID NOT NULL REFERENCES organisations (id) ON DELETE RESTRICT,
  project_id UUID NOT NULL REFERENCES projects (id) ON DELETE CASCADE,
  snapshot_id UUID NOT NULL,
  source_agent TEXT NOT NULL
    CHECK (
      source_agent IN (
        'delivery_performance',
        'quality_intelligence',
        'workforce_capability',
        'project_governance',
        'operational_knowledge',
        'client_intelligence'
      )
    ),
  source_table TEXT NOT NULL,
  source_row_id UUID NOT NULL,
  visibility TEXT NOT NULL
    CHECK (visibility IN ('internal', 'client_safe')),
  observed_at TIMESTAMPTZ,
  claim_keys JSONB NOT NULL DEFAULT '[]'::jsonb
    CHECK (jsonb_typeof(claim_keys) = 'array'),
  description TEXT NOT NULL,
  source_fingerprint TEXT NOT NULL
    CHECK (source_fingerprint ~ '^[0-9a-f]{64}$'),
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  CONSTRAINT client_intelligence_evidence_links_snapshot_identity_fkey
    FOREIGN KEY (snapshot_id, org_id, project_id, source_fingerprint)
    REFERENCES client_intelligence_snapshots (id, org_id, project_id, source_fingerprint)
    ON DELETE CASCADE,
  CONSTRAINT client_intelligence_evidence_links_snapshot_source_key UNIQUE (
    snapshot_id,
    source_agent,
    source_table,
    source_row_id,
    visibility
  )
);

CREATE INDEX client_intelligence_evidence_links_org_idx
  ON client_intelligence_evidence_links (org_id);
CREATE INDEX client_intelligence_evidence_links_project_idx
  ON client_intelligence_evidence_links (project_id);
CREATE INDEX client_intelligence_evidence_links_snapshot_idx
  ON client_intelligence_evidence_links (snapshot_id);
CREATE INDEX client_intelligence_evidence_links_source_idx
  ON client_intelligence_evidence_links (source_table, source_row_id);

ALTER TABLE client_intelligence_snapshots ENABLE ROW LEVEL SECURITY;
ALTER TABLE client_intelligence_evidence_links ENABLE ROW LEVEL SECURITY;

-- Snapshots: append-only (SELECT + INSERT only; no UPDATE/DELETE policies).
CREATE POLICY client_intelligence_snapshots_dm_select ON client_intelligence_snapshots
  FOR SELECT TO public
  USING (
    public.auth_user_role() = 'delivery_manager'
    AND org_id = public.auth_user_org_id()
  );

CREATE POLICY client_intelligence_snapshots_dm_insert ON client_intelligence_snapshots
  FOR INSERT TO public
  WITH CHECK (
    public.auth_user_role() = 'delivery_manager'
    AND org_id = public.auth_user_org_id()
  );

CREATE POLICY client_intelligence_snapshots_leadership_select ON client_intelligence_snapshots
  FOR SELECT TO public
  USING (
    public.auth_user_role() = 'bsg_leadership'
    AND visibility_mode = 'client_safe'
  );

CREATE POLICY client_intelligence_snapshots_client_select ON client_intelligence_snapshots
  FOR SELECT TO public
  USING (
    public.auth_user_role() = 'client'
    AND org_id = public.auth_user_org_id()
    AND visibility_mode = 'client_safe'
    AND EXISTS (
      SELECT 1
      FROM project_assignments pa
      WHERE pa.project_id = client_intelligence_snapshots.project_id
        AND pa.user_id = public.current_user_id()
        AND pa.is_active = TRUE
        AND pa.deleted_at IS NULL
    )
  );

CREATE POLICY client_intelligence_snapshots_super_admin_select ON client_intelligence_snapshots
  FOR SELECT TO public
  USING (public.auth_user_role() = 'super_admin');

CREATE POLICY client_intelligence_snapshots_super_admin_insert ON client_intelligence_snapshots
  FOR INSERT TO public
  WITH CHECK (public.auth_user_role() = 'super_admin');

-- Evidence links: append-only (SELECT + INSERT only; no UPDATE/DELETE policies).
CREATE POLICY client_intelligence_evidence_links_dm_select
  ON client_intelligence_evidence_links
  FOR SELECT TO public
  USING (
    public.auth_user_role() = 'delivery_manager'
    AND org_id = public.auth_user_org_id()
  );

CREATE POLICY client_intelligence_evidence_links_dm_insert
  ON client_intelligence_evidence_links
  FOR INSERT TO public
  WITH CHECK (
    public.auth_user_role() = 'delivery_manager'
    AND org_id = public.auth_user_org_id()
  );

CREATE POLICY client_intelligence_evidence_links_leadership_select
  ON client_intelligence_evidence_links
  FOR SELECT TO public
  USING (
    public.auth_user_role() = 'bsg_leadership'
    AND visibility = 'client_safe'
    AND EXISTS (
      SELECT 1
      FROM client_intelligence_snapshots s
      WHERE s.id = client_intelligence_evidence_links.snapshot_id
        AND s.visibility_mode = 'client_safe'
    )
  );

CREATE POLICY client_intelligence_evidence_links_client_select
  ON client_intelligence_evidence_links
  FOR SELECT TO public
  USING (
    public.auth_user_role() = 'client'
    AND org_id = public.auth_user_org_id()
    AND visibility = 'client_safe'
    AND EXISTS (
      SELECT 1
      FROM client_intelligence_snapshots s
      JOIN project_assignments pa ON pa.project_id = s.project_id
      WHERE s.id = client_intelligence_evidence_links.snapshot_id
        AND s.visibility_mode = 'client_safe'
        AND pa.user_id = public.current_user_id()
        AND pa.is_active = TRUE
        AND pa.deleted_at IS NULL
    )
  );

CREATE POLICY client_intelligence_evidence_links_super_admin_select
  ON client_intelligence_evidence_links
  FOR SELECT TO public
  USING (public.auth_user_role() = 'super_admin');

CREATE POLICY client_intelligence_evidence_links_super_admin_insert
  ON client_intelligence_evidence_links
  FOR INSERT TO public
  WITH CHECK (public.auth_user_role() = 'super_admin');

-- Safe downgrade (manual):
-- DROP POLICY IF EXISTS client_intelligence_evidence_links_super_admin_insert ON client_intelligence_evidence_links;
-- DROP POLICY IF EXISTS client_intelligence_evidence_links_super_admin_select ON client_intelligence_evidence_links;
-- DROP POLICY IF EXISTS client_intelligence_evidence_links_client_select ON client_intelligence_evidence_links;
-- DROP POLICY IF EXISTS client_intelligence_evidence_links_leadership_select ON client_intelligence_evidence_links;
-- DROP POLICY IF EXISTS client_intelligence_evidence_links_dm_insert ON client_intelligence_evidence_links;
-- DROP POLICY IF EXISTS client_intelligence_evidence_links_dm_select ON client_intelligence_evidence_links;
-- DROP POLICY IF EXISTS client_intelligence_snapshots_super_admin_insert ON client_intelligence_snapshots;
-- DROP POLICY IF EXISTS client_intelligence_snapshots_super_admin_select ON client_intelligence_snapshots;
-- DROP POLICY IF EXISTS client_intelligence_snapshots_client_select ON client_intelligence_snapshots;
-- DROP POLICY IF EXISTS client_intelligence_snapshots_leadership_select ON client_intelligence_snapshots;
-- DROP POLICY IF EXISTS client_intelligence_snapshots_dm_insert ON client_intelligence_snapshots;
-- DROP POLICY IF EXISTS client_intelligence_snapshots_dm_select ON client_intelligence_snapshots;
-- DROP TABLE IF EXISTS client_intelligence_evidence_links;
-- DROP TABLE IF EXISTS client_intelligence_snapshots;
