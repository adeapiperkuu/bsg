-- Operational Knowledge Agent — lessons and SOP documents

CREATE TABLE knowledge_lessons (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  org_id UUID NOT NULL REFERENCES organisations (id) ON DELETE RESTRICT,
  title TEXT NOT NULL,
  body TEXT NOT NULL,
  tags JSONB NOT NULL DEFAULT '[]'::jsonb,
  linked_quality_event_id UUID,
  linked_alert_id UUID REFERENCES risk_alerts (id) ON DELETE SET NULL,
  created_by UUID NOT NULL REFERENCES users (id) ON DELETE RESTRICT,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE sop_documents (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  org_id UUID NOT NULL REFERENCES organisations (id) ON DELETE RESTRICT,
  title TEXT NOT NULL,
  version TEXT NOT NULL,
  content_text TEXT NOT NULL,
  tags JSONB NOT NULL DEFAULT '[]'::jsonb,
  effective_date DATE NOT NULL,
  is_active BOOLEAN NOT NULL DEFAULT TRUE,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX knowledge_lessons_org_id_idx ON knowledge_lessons (org_id);
CREATE INDEX knowledge_lessons_alert_id_idx ON knowledge_lessons (linked_alert_id);
CREATE INDEX sop_documents_org_id_idx ON sop_documents (org_id);

CREATE TRIGGER knowledge_lessons_updated_at BEFORE UPDATE ON knowledge_lessons FOR EACH ROW EXECUTE FUNCTION set_updated_at();
CREATE TRIGGER sop_documents_updated_at BEFORE UPDATE ON sop_documents FOR EACH ROW EXECUTE FUNCTION set_updated_at();

ALTER TABLE knowledge_lessons ENABLE ROW LEVEL SECURITY;
ALTER TABLE sop_documents ENABLE ROW LEVEL SECURITY;

CREATE POLICY knowledge_lessons_dm_all ON knowledge_lessons FOR ALL TO public
  USING (public.auth_user_role() = 'delivery_manager' AND org_id = public.auth_user_org_id())
  WITH CHECK (public.auth_user_role() = 'delivery_manager' AND org_id = public.auth_user_org_id());
CREATE POLICY knowledge_lessons_leadership_select ON knowledge_lessons FOR SELECT TO public
  USING (public.auth_user_role() = 'bsg_leadership');
CREATE POLICY knowledge_lessons_super_admin_select ON knowledge_lessons FOR SELECT TO public
  USING (public.auth_user_role() = 'super_admin');

CREATE POLICY sop_documents_dm_all ON sop_documents FOR ALL TO public
  USING (public.auth_user_role() = 'delivery_manager' AND org_id = public.auth_user_org_id())
  WITH CHECK (public.auth_user_role() = 'delivery_manager' AND org_id = public.auth_user_org_id());
CREATE POLICY sop_documents_leadership_select ON sop_documents FOR SELECT TO public
  USING (public.auth_user_role() = 'bsg_leadership');
CREATE POLICY sop_documents_super_admin_select ON sop_documents FOR SELECT TO public
  USING (public.auth_user_role() = 'super_admin');
