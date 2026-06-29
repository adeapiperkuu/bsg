CREATE TYPE recommendation_severity AS ENUM ('low', 'medium', 'high');
CREATE TYPE recommendation_status AS ENUM ('pending', 'accepted', 'rejected');
CREATE TYPE owner_type AS ENUM ('user', 'team');

CREATE TABLE mitigation_recommendations (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  project_id UUID NOT NULL REFERENCES projects (id) ON DELETE CASCADE,
  org_id UUID NOT NULL REFERENCES organisations (id) ON DELETE RESTRICT,
  title TEXT NOT NULL,
  description TEXT,
  severity recommendation_severity NOT NULL,
  confidence_score NUMERIC(4, 3) NOT NULL CHECK (confidence_score BETWEEN 0 AND 1),
  status recommendation_status NOT NULL DEFAULT 'pending',
  owner_type owner_type,
  owner_id UUID,
  source_risk_id UUID REFERENCES risk_alerts (id) ON DELETE SET NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  deleted_at TIMESTAMPTZ
);

CREATE INDEX mitigation_recommendations_project_id_idx ON mitigation_recommendations (project_id);
CREATE INDEX mitigation_recommendations_org_id_idx ON mitigation_recommendations (org_id);
CREATE INDEX mitigation_recommendations_source_risk_id_idx ON mitigation_recommendations (source_risk_id);
CREATE INDEX mitigation_recommendations_status_idx ON mitigation_recommendations (status);

CREATE TRIGGER mitigation_recommendations_updated_at
  BEFORE UPDATE ON mitigation_recommendations
  FOR EACH ROW EXECUTE FUNCTION set_updated_at();

ALTER TABLE mitigation_recommendations ENABLE ROW LEVEL SECURITY;

CREATE POLICY mitigation_recommendations_client_select ON mitigation_recommendations FOR SELECT TO public
  USING (public.auth_user_role() = 'client' AND org_id = public.auth_user_org_id() AND deleted_at IS NULL);
CREATE POLICY mitigation_recommendations_dm_all ON mitigation_recommendations FOR ALL TO public
  USING (public.auth_user_role() = 'delivery_manager' AND org_id = public.auth_user_org_id())
  WITH CHECK (public.auth_user_role() = 'delivery_manager' AND org_id = public.auth_user_org_id());
CREATE POLICY mitigation_recommendations_leadership_select ON mitigation_recommendations FOR SELECT TO public
  USING (public.auth_user_role() = 'bsg_leadership' AND deleted_at IS NULL);
CREATE POLICY mitigation_recommendations_super_admin_all ON mitigation_recommendations FOR ALL TO public
  USING (public.auth_user_role() = 'super_admin') WITH CHECK (public.auth_user_role() = 'super_admin');
