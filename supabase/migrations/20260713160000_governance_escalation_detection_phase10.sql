-- Phase 10: advanced deterministic escalation detection diagnostics.

CREATE TABLE IF NOT EXISTS governance_escalation_suggestion_scans (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  org_id UUID NOT NULL REFERENCES organisations(id) ON DELETE RESTRICT,
  project_id UUID REFERENCES projects(id) ON DELETE SET NULL,
  scan_type TEXT NOT NULL DEFAULT 'manual',
  status TEXT NOT NULL DEFAULT 'running',
  started_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  completed_at TIMESTAMPTZ,
  requested_by_user_id UUID REFERENCES users(id) ON DELETE SET NULL,
  projects_checked INTEGER NOT NULL DEFAULT 0,
  signals_evaluated INTEGER NOT NULL DEFAULT 0,
  suggestions_created INTEGER NOT NULL DEFAULT 0,
  suggestions_refreshed INTEGER NOT NULL DEFAULT 0,
  suggestions_skipped_by_cooldown INTEGER NOT NULL DEFAULT 0,
  suggestions_suppressed_existing_escalation INTEGER NOT NULL DEFAULT 0,
  provider_failures JSONB NOT NULL DEFAULT '{}'::jsonb,
  result_summary JSONB NOT NULL DEFAULT '{}'::jsonb,
  duration_ms NUMERIC(10, 1),
  failure_reason TEXT,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS governance_escalation_suggestion_scans_org_started_idx
  ON governance_escalation_suggestion_scans (org_id, started_at DESC);

CREATE INDEX IF NOT EXISTS governance_escalation_suggestion_scans_project_started_idx
  ON governance_escalation_suggestion_scans (project_id, started_at DESC);

CREATE INDEX IF NOT EXISTS governance_escalation_suggestion_scans_status_idx
  ON governance_escalation_suggestion_scans (status);

ALTER TABLE governance_escalation_suggestion_scans ENABLE ROW LEVEL SECURITY;

CREATE POLICY governance_escalation_suggestion_scans_dm_all
  ON governance_escalation_suggestion_scans FOR ALL TO public
  USING (
    auth.jwt() ->> 'role' = 'delivery_manager'
    AND org_id = (auth.jwt() ->> 'org_id')::uuid
  )
  WITH CHECK (
    auth.jwt() ->> 'role' = 'delivery_manager'
    AND org_id = (auth.jwt() ->> 'org_id')::uuid
  );

CREATE POLICY governance_escalation_suggestion_scans_leadership_select
  ON governance_escalation_suggestion_scans FOR SELECT TO public
  USING (
    auth.jwt() ->> 'role' = 'bsg_leadership'
    AND org_id = (auth.jwt() ->> 'org_id')::uuid
  );

CREATE POLICY governance_escalation_suggestion_scans_super_admin_all
  ON governance_escalation_suggestion_scans FOR ALL TO public
  USING (auth.jwt() ->> 'role' = 'super_admin')
  WITH CHECK (auth.jwt() ->> 'role' = 'super_admin');
