-- Project Governance Agent — Phase 8: Record provenance / evidence links

CREATE TYPE governance_record_target_type AS ENUM ('action', 'escalation');

CREATE TYPE governance_record_evidence_source_type AS ENUM (
  'ai_recommendation',
  'project',
  'dependency',
  'escalation',
  'action',
  'scope_state',
  'delivery_signal',
  'milestone',
  'trend',
  'governance_metric',
  'recent_activity'
);

CREATE TYPE governance_record_link_type AS ENUM (
  'ai_recommendation_source',
  'supporting_evidence',
  'converted_from',
  'related_dependency',
  'related_escalation',
  'related_action',
  'related_scope_state',
  'related_delivery_signal'
);

CREATE TABLE governance_record_evidence_links (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  org_id UUID NOT NULL REFERENCES organisations (id) ON DELETE RESTRICT,
  target_type governance_record_target_type NOT NULL,
  target_id UUID NOT NULL,
  source_type governance_record_evidence_source_type NOT NULL,
  source_id UUID,
  recommendation_id UUID REFERENCES governance_ai_recommendations (id) ON DELETE SET NULL,
  conversion_id UUID REFERENCES governance_ai_recommendation_conversions (id) ON DELETE SET NULL,
  evidence_id TEXT,
  link_type governance_record_link_type NOT NULL,
  title TEXT,
  description TEXT,
  status_snapshot TEXT,
  severity_snapshot TEXT,
  project_id UUID REFERENCES projects (id) ON DELETE SET NULL,
  occurred_at TIMESTAMPTZ,
  metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
  created_by_user_id UUID REFERENCES users (id) ON DELETE SET NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  deleted_at TIMESTAMPTZ,
  CONSTRAINT governance_record_evidence_links_target_check CHECK (
    (target_type = 'action' AND target_id IS NOT NULL)
    OR (target_type = 'escalation' AND target_id IS NOT NULL)
  )
);

-- One source-recommendation link per target.
CREATE UNIQUE INDEX governance_record_evidence_links_source_rec_uidx
  ON governance_record_evidence_links (target_type, target_id, link_type)
  WHERE deleted_at IS NULL
    AND link_type IN ('ai_recommendation_source', 'converted_from');

-- Deduplicate supporting entity links.
CREATE UNIQUE INDEX governance_record_evidence_links_entity_uidx
  ON governance_record_evidence_links (
    target_type,
    target_id,
    link_type,
    source_type,
    COALESCE(source_id, '00000000-0000-0000-0000-000000000000'::uuid),
    COALESCE(evidence_id, '')
  )
  WHERE deleted_at IS NULL
    AND link_type NOT IN ('ai_recommendation_source', 'converted_from');

CREATE INDEX governance_record_evidence_links_target_idx
  ON governance_record_evidence_links (org_id, target_type, target_id)
  WHERE deleted_at IS NULL;

CREATE INDEX governance_record_evidence_links_recommendation_idx
  ON governance_record_evidence_links (org_id, recommendation_id)
  WHERE deleted_at IS NULL;

CREATE INDEX governance_record_evidence_links_source_idx
  ON governance_record_evidence_links (source_type, source_id)
  WHERE deleted_at IS NULL;

ALTER TABLE governance_record_evidence_links ENABLE ROW LEVEL SECURITY;

CREATE POLICY governance_record_evidence_links_dm_all ON governance_record_evidence_links FOR ALL TO public
  USING (
    public.auth_user_role() = 'delivery_manager'
    AND org_id = public.auth_user_org_id()
  )
  WITH CHECK (
    public.auth_user_role() = 'delivery_manager'
    AND org_id = public.auth_user_org_id()
  );

CREATE POLICY governance_record_evidence_links_leadership_select ON governance_record_evidence_links FOR SELECT TO public
  USING (
    public.auth_user_role() = 'bsg_leadership'
    AND deleted_at IS NULL
  );

CREATE POLICY governance_record_evidence_links_super_admin_all ON governance_record_evidence_links FOR ALL TO public
  USING (public.auth_user_role() = 'super_admin')
  WITH CHECK (public.auth_user_role() = 'super_admin');
