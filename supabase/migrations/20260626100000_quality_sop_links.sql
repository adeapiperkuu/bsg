-- Quality event → SOP version audit links (UC-04 / BR-09)

CREATE TABLE quality_sop_links (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  org_id UUID NOT NULL REFERENCES organisations (id) ON DELETE RESTRICT,
  risk_alert_id UUID NOT NULL REFERENCES risk_alerts (id) ON DELETE CASCADE,
  sop_version_id UUID NOT NULL REFERENCES sop_version_history (id) ON DELETE CASCADE,
  confirmed_by UUID REFERENCES users (id) ON DELETE SET NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX quality_sop_links_alert_idx ON quality_sop_links (risk_alert_id);
CREATE INDEX quality_sop_links_version_idx ON quality_sop_links (sop_version_id);

ALTER TABLE quality_sop_links ENABLE ROW LEVEL SECURITY;

CREATE POLICY quality_sop_links_dm_all ON quality_sop_links FOR ALL TO public
  USING (public.auth_user_role() = 'delivery_manager' AND org_id = public.auth_user_org_id())
  WITH CHECK (public.auth_user_role() = 'delivery_manager' AND org_id = public.auth_user_org_id());
CREATE POLICY quality_sop_links_super_admin_select ON quality_sop_links FOR SELECT TO public
  USING (public.auth_user_role() = 'super_admin');
