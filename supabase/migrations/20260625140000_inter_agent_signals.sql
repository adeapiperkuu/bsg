-- Inter-agent signal bus for Quality Intelligence Phase 2

ALTER TYPE notification_type ADD VALUE IF NOT EXISTS 'calibration_required';
ALTER TYPE notification_type ADD VALUE IF NOT EXISTS 'sop_ambiguity_flagged';

CREATE TABLE IF NOT EXISTS inter_agent_signals (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  signal_type TEXT NOT NULL CHECK (signal_type IN ('quality_risk', 'skill_gap', 'quality_escalation')),
  source_agent TEXT NOT NULL DEFAULT 'quality_intelligence_agent',
  target_agent TEXT NOT NULL,
  payload JSONB NOT NULL DEFAULT '{}'::jsonb,
  status TEXT NOT NULL DEFAULT 'pending' CHECK (status IN ('pending', 'consumed')),
  project_id UUID REFERENCES projects (id) ON DELETE CASCADE,
  org_id UUID REFERENCES organisations (id) ON DELETE RESTRICT,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS inter_agent_signals_project_idx ON inter_agent_signals (project_id);
CREATE INDEX IF NOT EXISTS inter_agent_signals_status_idx ON inter_agent_signals (status);
CREATE INDEX IF NOT EXISTS inter_agent_signals_type_idx ON inter_agent_signals (signal_type);

ALTER TABLE inter_agent_signals ENABLE ROW LEVEL SECURITY;
CREATE POLICY inter_agent_signals_super_admin ON inter_agent_signals FOR ALL TO public
  USING (public.auth_user_role() = 'super_admin')
  WITH CHECK (public.auth_user_role() = 'super_admin');
CREATE POLICY inter_agent_signals_dm_select ON inter_agent_signals FOR SELECT TO public
  USING (public.auth_user_role() = 'delivery_manager' AND org_id = public.auth_user_org_id());
