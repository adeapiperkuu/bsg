-- Client Intelligence Phase 17/19 — scheduled reports + multi-stage governance.
-- Additive only; does not alter existing communications lifecycle.

CREATE TYPE client_report_cadence AS ENUM (
  'weekly',
  'monthly',
  'quarterly',
  'executive'
);

CREATE TYPE client_report_governance_status AS ENUM (
  'draft',
  'pending_manager',
  'pending_leadership',
  'pending_compliance',
  'published',
  'rejected'
);

CREATE TYPE client_report_delivery_status AS ENUM (
  'pending',
  'distributed',
  'failed'
);

CREATE TABLE client_report_schedules (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  org_id UUID NOT NULL REFERENCES organisations (id) ON DELETE RESTRICT,
  project_id UUID NOT NULL REFERENCES projects (id) ON DELETE CASCADE,
  cadence client_report_cadence NOT NULL,
  enabled BOOLEAN NOT NULL DEFAULT TRUE,
  section_config JSONB NOT NULL DEFAULT '[]'::jsonb,
  next_run_at TIMESTAMPTZ,
  last_run_at TIMESTAMPTZ,
  last_package_id UUID,
  created_by UUID REFERENCES users (id) ON DELETE SET NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  CONSTRAINT client_report_schedules_section_config_array_check
    CHECK (jsonb_typeof(section_config) = 'array'),
  CONSTRAINT client_report_schedules_org_project_cadence_key
    UNIQUE (org_id, project_id, cadence)
);

CREATE INDEX client_report_schedules_project_idx
  ON client_report_schedules (project_id, enabled, next_run_at);
CREATE INDEX client_report_schedules_org_next_run_idx
  ON client_report_schedules (org_id, next_run_at)
  WHERE enabled = TRUE;

CREATE TABLE client_intelligence_report_packages (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  org_id UUID NOT NULL REFERENCES organisations (id) ON DELETE RESTRICT,
  project_id UUID NOT NULL REFERENCES projects (id) ON DELETE CASCADE,
  schedule_id UUID REFERENCES client_report_schedules (id) ON DELETE SET NULL,
  communication_id UUID REFERENCES client_communications (id) ON DELETE SET NULL,
  report_type client_report_cadence NOT NULL,
  title TEXT NOT NULL,
  body_markdown TEXT NOT NULL,
  section_config JSONB NOT NULL DEFAULT '[]'::jsonb,
  version INTEGER NOT NULL DEFAULT 1,
  status client_report_governance_status NOT NULL DEFAULT 'draft',
  source_fingerprint TEXT
    CHECK (
      source_fingerprint IS NULL
      OR source_fingerprint ~ '^[0-9a-f]{64}$'
    ),
  rejection_reason TEXT,
  created_by UUID REFERENCES users (id) ON DELETE SET NULL,
  updated_by UUID REFERENCES users (id) ON DELETE SET NULL,
  published_at TIMESTAMPTZ,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  CONSTRAINT client_intelligence_report_packages_section_config_array_check
    CHECK (jsonb_typeof(section_config) = 'array'),
  CONSTRAINT client_intelligence_report_packages_version_positive_check
    CHECK (version >= 1)
);

CREATE INDEX client_intelligence_report_packages_project_status_idx
  ON client_intelligence_report_packages (project_id, status, created_at DESC);
CREATE INDEX client_intelligence_report_packages_org_created_idx
  ON client_intelligence_report_packages (org_id, created_at DESC);

ALTER TABLE client_report_schedules
  ADD CONSTRAINT client_report_schedules_last_package_fkey
  FOREIGN KEY (last_package_id)
  REFERENCES client_intelligence_report_packages (id)
  ON DELETE SET NULL;

CREATE TABLE client_intelligence_report_approvals (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  org_id UUID NOT NULL REFERENCES organisations (id) ON DELETE RESTRICT,
  package_id UUID NOT NULL
    REFERENCES client_intelligence_report_packages (id) ON DELETE CASCADE,
  from_status client_report_governance_status,
  to_status client_report_governance_status NOT NULL,
  actor_user_id UUID REFERENCES users (id) ON DELETE SET NULL,
  comment TEXT,
  rejection_reason TEXT,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX client_intelligence_report_approvals_package_idx
  ON client_intelligence_report_approvals (package_id, created_at);

CREATE TABLE client_intelligence_report_deliveries (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  org_id UUID NOT NULL REFERENCES organisations (id) ON DELETE RESTRICT,
  package_id UUID NOT NULL
    REFERENCES client_intelligence_report_packages (id) ON DELETE CASCADE,
  channel TEXT NOT NULL DEFAULT 'in_app',
  status client_report_delivery_status NOT NULL DEFAULT 'pending',
  recipient_summary TEXT,
  error_detail TEXT,
  delivered_at TIMESTAMPTZ,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX client_intelligence_report_deliveries_package_idx
  ON client_intelligence_report_deliveries (package_id, created_at DESC);

ALTER TABLE client_report_schedules ENABLE ROW LEVEL SECURITY;
ALTER TABLE client_intelligence_report_packages ENABLE ROW LEVEL SECURITY;
ALTER TABLE client_intelligence_report_approvals ENABLE ROW LEVEL SECURITY;
ALTER TABLE client_intelligence_report_deliveries ENABLE ROW LEVEL SECURITY;

-- Match existing CI / communications RLS: JWT claims via auth_user_* helpers.
CREATE POLICY client_report_schedules_dm_all
  ON client_report_schedules
  FOR ALL TO public
  USING (
    public.auth_user_role() = 'delivery_manager'
    AND org_id = public.auth_user_org_id()
  )
  WITH CHECK (
    public.auth_user_role() = 'delivery_manager'
    AND org_id = public.auth_user_org_id()
  );

CREATE POLICY client_report_schedules_leadership_select
  ON client_report_schedules
  FOR SELECT TO public
  USING (public.auth_user_role() = 'bsg_leadership');

CREATE POLICY client_report_schedules_super_admin_all
  ON client_report_schedules
  FOR ALL TO public
  USING (public.auth_user_role() = 'super_admin')
  WITH CHECK (public.auth_user_role() = 'super_admin');

CREATE POLICY client_intelligence_report_packages_dm_all
  ON client_intelligence_report_packages
  FOR ALL TO public
  USING (
    public.auth_user_role() = 'delivery_manager'
    AND org_id = public.auth_user_org_id()
  )
  WITH CHECK (
    public.auth_user_role() = 'delivery_manager'
    AND org_id = public.auth_user_org_id()
  );

CREATE POLICY client_intelligence_report_packages_leadership_all
  ON client_intelligence_report_packages
  FOR ALL TO public
  USING (public.auth_user_role() = 'bsg_leadership')
  WITH CHECK (public.auth_user_role() = 'bsg_leadership');

CREATE POLICY client_intelligence_report_packages_super_admin_all
  ON client_intelligence_report_packages
  FOR ALL TO public
  USING (public.auth_user_role() = 'super_admin')
  WITH CHECK (public.auth_user_role() = 'super_admin');

CREATE POLICY client_intelligence_report_approvals_dm_all
  ON client_intelligence_report_approvals
  FOR ALL TO public
  USING (
    public.auth_user_role() = 'delivery_manager'
    AND org_id = public.auth_user_org_id()
  )
  WITH CHECK (
    public.auth_user_role() = 'delivery_manager'
    AND org_id = public.auth_user_org_id()
  );

CREATE POLICY client_intelligence_report_approvals_leadership_all
  ON client_intelligence_report_approvals
  FOR ALL TO public
  USING (public.auth_user_role() = 'bsg_leadership')
  WITH CHECK (public.auth_user_role() = 'bsg_leadership');

CREATE POLICY client_intelligence_report_approvals_super_admin_all
  ON client_intelligence_report_approvals
  FOR ALL TO public
  USING (public.auth_user_role() = 'super_admin')
  WITH CHECK (public.auth_user_role() = 'super_admin');

CREATE POLICY client_intelligence_report_deliveries_dm_all
  ON client_intelligence_report_deliveries
  FOR ALL TO public
  USING (
    public.auth_user_role() = 'delivery_manager'
    AND org_id = public.auth_user_org_id()
  )
  WITH CHECK (
    public.auth_user_role() = 'delivery_manager'
    AND org_id = public.auth_user_org_id()
  );

CREATE POLICY client_intelligence_report_deliveries_leadership_select
  ON client_intelligence_report_deliveries
  FOR SELECT TO public
  USING (public.auth_user_role() = 'bsg_leadership');

CREATE POLICY client_intelligence_report_deliveries_super_admin_all
  ON client_intelligence_report_deliveries
  FOR ALL TO public
  USING (public.auth_user_role() = 'super_admin')
  WITH CHECK (public.auth_user_role() = 'super_admin');
