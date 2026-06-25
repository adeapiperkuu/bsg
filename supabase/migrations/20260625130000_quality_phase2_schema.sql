-- Quality Intelligence Agent Phase 2 — reviewer-level and SOP tracking

CREATE TABLE reviewer_scorecards (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  annotator_id UUID NOT NULL REFERENCES annotators (id) ON DELETE CASCADE,
  project_id UUID NOT NULL REFERENCES projects (id) ON DELETE CASCADE,
  org_id UUID NOT NULL REFERENCES organisations (id) ON DELETE RESTRICT,
  iso_year INT NOT NULL CHECK (iso_year >= 2024),
  iso_week INT NOT NULL CHECK (iso_week BETWEEN 1 AND 53),
  items_evaluated INT NOT NULL DEFAULT 0 CHECK (items_evaluated >= 0),
  accuracy_pct NUMERIC(5, 2) CHECK (accuracy_pct BETWEEN 0 AND 100),
  error_breakdown JSONB,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  CONSTRAINT reviewer_scorecards_unique_week UNIQUE (annotator_id, project_id, iso_year, iso_week)
);

CREATE TABLE gold_set_evaluation_logs (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  annotator_id UUID NOT NULL REFERENCES annotators (id) ON DELETE CASCADE,
  project_id UUID NOT NULL REFERENCES projects (id) ON DELETE CASCADE,
  org_id UUID NOT NULL REFERENCES organisations (id) ON DELETE RESTRICT,
  item_id TEXT NOT NULL,
  score NUMERIC(5, 2),
  error_category TEXT,
  evaluated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE iaa_measurement_records (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  project_id UUID NOT NULL REFERENCES projects (id) ON DELETE CASCADE,
  org_id UUID NOT NULL REFERENCES organisations (id) ON DELETE RESTRICT,
  team_id UUID REFERENCES teams (id) ON DELETE SET NULL,
  reviewer_a_id UUID NOT NULL REFERENCES annotators (id) ON DELETE CASCADE,
  reviewer_b_id UUID NOT NULL REFERENCES annotators (id) ON DELETE CASCADE,
  task_type TEXT,
  krippendorff_alpha NUMERIC(4, 3) CHECK (krippendorff_alpha BETWEEN 0 AND 1),
  iso_year INT NOT NULL CHECK (iso_year >= 2024),
  iso_week INT NOT NULL CHECK (iso_week BETWEEN 1 AND 53),
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE rework_logs (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  project_id UUID NOT NULL REFERENCES projects (id) ON DELETE CASCADE,
  org_id UUID NOT NULL REFERENCES organisations (id) ON DELETE RESTRICT,
  annotator_id UUID REFERENCES annotators (id) ON DELETE SET NULL,
  item_id TEXT NOT NULL,
  reason TEXT,
  rework_date DATE NOT NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE onboarding_records (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  annotator_id UUID NOT NULL REFERENCES annotators (id) ON DELETE CASCADE,
  org_id UUID NOT NULL REFERENCES organisations (id) ON DELETE RESTRICT,
  onboarding_date DATE NOT NULL,
  calibration_status TEXT NOT NULL DEFAULT 'pending' CHECK (calibration_status IN ('pending', 'in_progress', 'completed')),
  notes TEXT,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE sop_version_history (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  sop_document_id UUID NOT NULL REFERENCES sop_documents (id) ON DELETE CASCADE,
  org_id UUID NOT NULL REFERENCES organisations (id) ON DELETE RESTRICT,
  version TEXT NOT NULL,
  change_summary TEXT,
  effective_date DATE NOT NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE gold_set_metadata (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  project_id UUID NOT NULL REFERENCES projects (id) ON DELETE CASCADE,
  org_id UUID NOT NULL REFERENCES organisations (id) ON DELETE RESTRICT,
  version TEXT NOT NULL,
  item_count INT NOT NULL CHECK (item_count >= 0),
  last_updated TIMESTAMPTZ NOT NULL DEFAULT now(),
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE quality_lesson_links (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  org_id UUID NOT NULL REFERENCES organisations (id) ON DELETE RESTRICT,
  quality_snapshot_id UUID REFERENCES quality_snapshots (id) ON DELETE SET NULL,
  risk_alert_id UUID REFERENCES risk_alerts (id) ON DELETE SET NULL,
  knowledge_lesson_id UUID NOT NULL REFERENCES knowledge_lessons (id) ON DELETE CASCADE,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX reviewer_scorecards_annotator_idx ON reviewer_scorecards (annotator_id);
CREATE INDEX reviewer_scorecards_project_idx ON reviewer_scorecards (project_id);
CREATE INDEX gold_set_eval_project_idx ON gold_set_evaluation_logs (project_id);
CREATE INDEX iaa_measurement_project_idx ON iaa_measurement_records (project_id);
CREATE INDEX rework_logs_project_idx ON rework_logs (project_id);
CREATE INDEX onboarding_records_annotator_idx ON onboarding_records (annotator_id);
CREATE INDEX sop_version_history_doc_idx ON sop_version_history (sop_document_id);
CREATE INDEX gold_set_metadata_project_idx ON gold_set_metadata (project_id);
CREATE INDEX quality_lesson_links_lesson_idx ON quality_lesson_links (knowledge_lesson_id);

CREATE TRIGGER reviewer_scorecards_updated_at BEFORE UPDATE ON reviewer_scorecards FOR EACH ROW EXECUTE FUNCTION set_updated_at();
CREATE TRIGGER onboarding_records_updated_at BEFORE UPDATE ON onboarding_records FOR EACH ROW EXECUTE FUNCTION set_updated_at();
CREATE TRIGGER gold_set_metadata_updated_at BEFORE UPDATE ON gold_set_metadata FOR EACH ROW EXECUTE FUNCTION set_updated_at();

ALTER TABLE reviewer_scorecards ENABLE ROW LEVEL SECURITY;
ALTER TABLE gold_set_evaluation_logs ENABLE ROW LEVEL SECURITY;
ALTER TABLE iaa_measurement_records ENABLE ROW LEVEL SECURITY;
ALTER TABLE rework_logs ENABLE ROW LEVEL SECURITY;
ALTER TABLE onboarding_records ENABLE ROW LEVEL SECURITY;
ALTER TABLE sop_version_history ENABLE ROW LEVEL SECURITY;
ALTER TABLE gold_set_metadata ENABLE ROW LEVEL SECURITY;
ALTER TABLE quality_lesson_links ENABLE ROW LEVEL SECURITY;

-- Org-scoped read/write patterns (internal quality data — no client access)
CREATE POLICY reviewer_scorecards_dm_all ON reviewer_scorecards FOR ALL TO public
  USING (public.auth_user_role() = 'delivery_manager' AND org_id = public.auth_user_org_id())
  WITH CHECK (public.auth_user_role() = 'delivery_manager' AND org_id = public.auth_user_org_id());
CREATE POLICY reviewer_scorecards_leadership_select ON reviewer_scorecards FOR SELECT TO public
  USING (public.auth_user_role() = 'bsg_leadership');
CREATE POLICY reviewer_scorecards_super_admin_select ON reviewer_scorecards FOR SELECT TO public
  USING (public.auth_user_role() = 'super_admin');

CREATE POLICY gold_set_eval_dm_all ON gold_set_evaluation_logs FOR ALL TO public
  USING (public.auth_user_role() = 'delivery_manager' AND org_id = public.auth_user_org_id())
  WITH CHECK (public.auth_user_role() = 'delivery_manager' AND org_id = public.auth_user_org_id());
CREATE POLICY gold_set_eval_leadership_select ON gold_set_evaluation_logs FOR SELECT TO public
  USING (public.auth_user_role() = 'bsg_leadership');
CREATE POLICY gold_set_eval_super_admin_select ON gold_set_evaluation_logs FOR SELECT TO public
  USING (public.auth_user_role() = 'super_admin');

CREATE POLICY iaa_records_dm_all ON iaa_measurement_records FOR ALL TO public
  USING (public.auth_user_role() = 'delivery_manager' AND org_id = public.auth_user_org_id())
  WITH CHECK (public.auth_user_role() = 'delivery_manager' AND org_id = public.auth_user_org_id());
CREATE POLICY iaa_records_leadership_select ON iaa_measurement_records FOR SELECT TO public
  USING (public.auth_user_role() = 'bsg_leadership');
CREATE POLICY iaa_records_super_admin_select ON iaa_measurement_records FOR SELECT TO public
  USING (public.auth_user_role() = 'super_admin');

CREATE POLICY rework_logs_dm_all ON rework_logs FOR ALL TO public
  USING (public.auth_user_role() = 'delivery_manager' AND org_id = public.auth_user_org_id())
  WITH CHECK (public.auth_user_role() = 'delivery_manager' AND org_id = public.auth_user_org_id());
CREATE POLICY rework_logs_leadership_select ON rework_logs FOR SELECT TO public
  USING (public.auth_user_role() = 'bsg_leadership');
CREATE POLICY rework_logs_super_admin_select ON rework_logs FOR SELECT TO public
  USING (public.auth_user_role() = 'super_admin');

CREATE POLICY onboarding_dm_all ON onboarding_records FOR ALL TO public
  USING (public.auth_user_role() = 'delivery_manager' AND org_id = public.auth_user_org_id())
  WITH CHECK (public.auth_user_role() = 'delivery_manager' AND org_id = public.auth_user_org_id());
CREATE POLICY onboarding_leadership_select ON onboarding_records FOR SELECT TO public
  USING (public.auth_user_role() = 'bsg_leadership');
CREATE POLICY onboarding_super_admin_select ON onboarding_records FOR SELECT TO public
  USING (public.auth_user_role() = 'super_admin');

CREATE POLICY sop_version_dm_all ON sop_version_history FOR ALL TO public
  USING (public.auth_user_role() = 'delivery_manager' AND org_id = public.auth_user_org_id())
  WITH CHECK (public.auth_user_role() = 'delivery_manager' AND org_id = public.auth_user_org_id());
CREATE POLICY sop_version_leadership_select ON sop_version_history FOR SELECT TO public
  USING (public.auth_user_role() = 'bsg_leadership');
CREATE POLICY sop_version_super_admin_select ON sop_version_history FOR SELECT TO public
  USING (public.auth_user_role() = 'super_admin');

CREATE POLICY gold_set_meta_dm_all ON gold_set_metadata FOR ALL TO public
  USING (public.auth_user_role() = 'delivery_manager' AND org_id = public.auth_user_org_id())
  WITH CHECK (public.auth_user_role() = 'delivery_manager' AND org_id = public.auth_user_org_id());
CREATE POLICY gold_set_meta_leadership_select ON gold_set_metadata FOR SELECT TO public
  USING (public.auth_user_role() = 'bsg_leadership');
CREATE POLICY gold_set_meta_super_admin_select ON gold_set_metadata FOR SELECT TO public
  USING (public.auth_user_role() = 'super_admin');

CREATE POLICY quality_lesson_links_dm_all ON quality_lesson_links FOR ALL TO public
  USING (public.auth_user_role() = 'delivery_manager' AND org_id = public.auth_user_org_id())
  WITH CHECK (public.auth_user_role() = 'delivery_manager' AND org_id = public.auth_user_org_id());
CREATE POLICY quality_lesson_links_leadership_select ON quality_lesson_links FOR SELECT TO public
  USING (public.auth_user_role() = 'bsg_leadership');
CREATE POLICY quality_lesson_links_super_admin_select ON quality_lesson_links FOR SELECT TO public
  USING (public.auth_user_role() = 'super_admin');
