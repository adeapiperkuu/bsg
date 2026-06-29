CREATE TABLE certifications (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  org_id UUID NOT NULL REFERENCES organisations (id) ON DELETE RESTRICT,
  name TEXT NOT NULL,
  issuing_body TEXT,
  description TEXT,
  validity_months INTEGER CHECK (validity_months IS NULL OR validity_months >= 0),
  is_required_for_sme BOOLEAN NOT NULL DEFAULT false,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  deleted_at TIMESTAMPTZ
);

CREATE INDEX certifications_org_id_idx ON certifications (org_id);
CREATE INDEX certifications_name_idx ON certifications (name);

CREATE TRIGGER certifications_updated_at
  BEFORE UPDATE ON certifications
  FOR EACH ROW EXECUTE FUNCTION set_updated_at();

CREATE TABLE employee_certifications (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  org_id UUID NOT NULL REFERENCES organisations (id) ON DELETE RESTRICT,
  annotator_id UUID NOT NULL REFERENCES annotators (id) ON DELETE CASCADE,
  certification_id UUID NOT NULL REFERENCES certifications (id) ON DELETE RESTRICT,
  issued_at DATE,
  expires_at DATE,
  status TEXT NOT NULL DEFAULT 'active' CHECK (
    status IN ('active', 'expired', 'pending_review', 'revoked')
  ),
  evidence_url TEXT,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  deleted_at TIMESTAMPTZ
);

CREATE INDEX employee_certifications_org_id_idx ON employee_certifications (org_id);
CREATE INDEX employee_certifications_annotator_id_idx ON employee_certifications (annotator_id);
CREATE INDEX employee_certifications_certification_id_idx ON employee_certifications (certification_id);
CREATE INDEX employee_certifications_expires_at_idx ON employee_certifications (expires_at);

CREATE UNIQUE INDEX employee_certifications_annotator_cert_active_key
  ON employee_certifications (annotator_id, certification_id)
  WHERE deleted_at IS NULL;

CREATE TRIGGER employee_certifications_updated_at
  BEFORE UPDATE ON employee_certifications
  FOR EACH ROW EXECUTE FUNCTION set_updated_at();

CREATE TABLE training_programs (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  org_id UUID NOT NULL REFERENCES organisations (id) ON DELETE RESTRICT,
  skill_id UUID REFERENCES skills (id) ON DELETE SET NULL,
  name TEXT NOT NULL,
  description TEXT,
  required_for_skill_level TEXT CHECK (
    required_for_skill_level IS NULL
    OR required_for_skill_level IN ('beginner', 'intermediate', 'advanced', 'expert')
  ),
  is_mandatory BOOLEAN NOT NULL DEFAULT false,
  knowledge_document_id UUID REFERENCES knowledge_documents (id) ON DELETE SET NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  deleted_at TIMESTAMPTZ
);

CREATE INDEX training_programs_org_id_idx ON training_programs (org_id);
CREATE INDEX training_programs_skill_id_idx ON training_programs (skill_id);
CREATE INDEX training_programs_name_idx ON training_programs (name);

CREATE TRIGGER training_programs_updated_at
  BEFORE UPDATE ON training_programs
  FOR EACH ROW EXECUTE FUNCTION set_updated_at();

CREATE TABLE training_records (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  org_id UUID NOT NULL REFERENCES organisations (id) ON DELETE RESTRICT,
  annotator_id UUID NOT NULL REFERENCES annotators (id) ON DELETE CASCADE,
  training_program_id UUID NOT NULL REFERENCES training_programs (id) ON DELETE RESTRICT,
  status TEXT NOT NULL DEFAULT 'not_started' CHECK (
    status IN ('not_started', 'in_progress', 'completed', 'failed', 'expired')
  ),
  started_at TIMESTAMPTZ,
  completed_at TIMESTAMPTZ,
  score_pct NUMERIC(5, 2) CHECK (score_pct IS NULL OR (score_pct >= 0 AND score_pct <= 100)),
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  deleted_at TIMESTAMPTZ
);

CREATE INDEX training_records_org_id_idx ON training_records (org_id);
CREATE INDEX training_records_annotator_id_idx ON training_records (annotator_id);
CREATE INDEX training_records_training_program_id_idx ON training_records (training_program_id);

CREATE UNIQUE INDEX training_records_annotator_program_active_key
  ON training_records (annotator_id, training_program_id)
  WHERE deleted_at IS NULL;

CREATE TRIGGER training_records_updated_at
  BEFORE UPDATE ON training_records
  FOR EACH ROW EXECUTE FUNCTION set_updated_at();

ALTER TABLE certifications ENABLE ROW LEVEL SECURITY;
ALTER TABLE employee_certifications ENABLE ROW LEVEL SECURITY;
ALTER TABLE training_programs ENABLE ROW LEVEL SECURITY;
ALTER TABLE training_records ENABLE ROW LEVEL SECURITY;

CREATE POLICY certifications_dm_all ON certifications FOR ALL TO public
  USING (public.auth_user_role() = 'delivery_manager' AND org_id = public.auth_user_org_id())
  WITH CHECK (public.auth_user_role() = 'delivery_manager' AND org_id = public.auth_user_org_id());
CREATE POLICY certifications_leadership_select ON certifications FOR SELECT TO public
  USING (public.auth_user_role() = 'bsg_leadership' AND deleted_at IS NULL);
CREATE POLICY certifications_super_admin_all ON certifications FOR ALL TO public
  USING (public.auth_user_role() = 'super_admin') WITH CHECK (public.auth_user_role() = 'super_admin');

CREATE POLICY employee_certifications_dm_all ON employee_certifications FOR ALL TO public
  USING (public.auth_user_role() = 'delivery_manager' AND org_id = public.auth_user_org_id())
  WITH CHECK (public.auth_user_role() = 'delivery_manager' AND org_id = public.auth_user_org_id());
CREATE POLICY employee_certifications_leadership_select ON employee_certifications FOR SELECT TO public
  USING (public.auth_user_role() = 'bsg_leadership' AND deleted_at IS NULL);
CREATE POLICY employee_certifications_super_admin_all ON employee_certifications FOR ALL TO public
  USING (public.auth_user_role() = 'super_admin') WITH CHECK (public.auth_user_role() = 'super_admin');

CREATE POLICY training_programs_dm_all ON training_programs FOR ALL TO public
  USING (public.auth_user_role() = 'delivery_manager' AND org_id = public.auth_user_org_id())
  WITH CHECK (public.auth_user_role() = 'delivery_manager' AND org_id = public.auth_user_org_id());
CREATE POLICY training_programs_leadership_select ON training_programs FOR SELECT TO public
  USING (public.auth_user_role() = 'bsg_leadership' AND deleted_at IS NULL);
CREATE POLICY training_programs_super_admin_all ON training_programs FOR ALL TO public
  USING (public.auth_user_role() = 'super_admin') WITH CHECK (public.auth_user_role() = 'super_admin');

CREATE POLICY training_records_dm_all ON training_records FOR ALL TO public
  USING (public.auth_user_role() = 'delivery_manager' AND org_id = public.auth_user_org_id())
  WITH CHECK (public.auth_user_role() = 'delivery_manager' AND org_id = public.auth_user_org_id());
CREATE POLICY training_records_leadership_select ON training_records FOR SELECT TO public
  USING (public.auth_user_role() = 'bsg_leadership' AND deleted_at IS NULL);
CREATE POLICY training_records_super_admin_all ON training_records FOR ALL TO public
  USING (public.auth_user_role() = 'super_admin') WITH CHECK (public.auth_user_role() = 'super_admin');
