-- Client portal workspace: track client-submitted changes and publish structured
-- deliverables/meetings. Read access is assignment-scoped for clients.

CREATE TYPE client_change_request_status AS ENUM (
  'submitted',
  'under_review',
  'approved',
  'rejected',
  'implemented'
);

CREATE TYPE client_deliverable_status AS ENUM (
  'planned',
  'in_progress',
  'completed'
);

CREATE TYPE client_meeting_status AS ENUM (
  'scheduled',
  'completed',
  'cancelled'
);

CREATE TABLE client_change_requests (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  project_id UUID NOT NULL REFERENCES projects (id) ON DELETE CASCADE,
  org_id UUID NOT NULL REFERENCES organisations (id) ON DELETE RESTRICT,
  submitted_by UUID REFERENCES users (id) ON DELETE SET NULL,
  title TEXT NOT NULL CHECK (char_length(title) BETWEEN 3 AND 160),
  description TEXT NOT NULL CHECK (char_length(description) BETWEEN 10 AND 5000),
  business_justification TEXT CHECK (
    business_justification IS NULL OR char_length(business_justification) <= 3000
  ),
  priority TEXT NOT NULL DEFAULT 'medium'
    CHECK (priority IN ('low', 'medium', 'high', 'critical')),
  status client_change_request_status NOT NULL DEFAULT 'submitted',
  decision_notes TEXT,
  implemented_at TIMESTAMPTZ,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  deleted_at TIMESTAMPTZ
);

CREATE INDEX client_change_requests_project_created_idx
  ON client_change_requests (project_id, created_at DESC);
CREATE INDEX client_change_requests_org_status_idx
  ON client_change_requests (org_id, status);

CREATE TABLE client_deliverables (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  project_id UUID NOT NULL REFERENCES projects (id) ON DELETE CASCADE,
  org_id UUID NOT NULL REFERENCES organisations (id) ON DELETE RESTRICT,
  title TEXT NOT NULL,
  description TEXT,
  status client_deliverable_status NOT NULL DEFAULT 'planned',
  due_date DATE,
  completed_at TIMESTAMPTZ,
  file_name TEXT,
  file_url TEXT,
  client_visible BOOLEAN NOT NULL DEFAULT TRUE,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  deleted_at TIMESTAMPTZ
);

CREATE INDEX client_deliverables_project_status_idx
  ON client_deliverables (project_id, status);
CREATE INDEX client_deliverables_project_due_idx
  ON client_deliverables (project_id, due_date);

CREATE TABLE client_meetings (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  project_id UUID NOT NULL REFERENCES projects (id) ON DELETE CASCADE,
  org_id UUID NOT NULL REFERENCES organisations (id) ON DELETE RESTRICT,
  title TEXT NOT NULL,
  starts_at TIMESTAMPTZ NOT NULL,
  duration_minutes INTEGER NOT NULL DEFAULT 30
    CHECK (duration_minutes BETWEEN 5 AND 480),
  meeting_url TEXT,
  agenda TEXT,
  minutes TEXT,
  action_items JSONB NOT NULL DEFAULT '[]'::jsonb
    CHECK (jsonb_typeof(action_items) = 'array'),
  status client_meeting_status NOT NULL DEFAULT 'scheduled',
  client_visible BOOLEAN NOT NULL DEFAULT TRUE,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  deleted_at TIMESTAMPTZ
);

CREATE INDEX client_meetings_project_starts_idx
  ON client_meetings (project_id, starts_at);
CREATE INDEX client_meetings_org_status_idx
  ON client_meetings (org_id, status);

ALTER TABLE client_change_requests ENABLE ROW LEVEL SECURITY;
ALTER TABLE client_deliverables ENABLE ROW LEVEL SECURITY;
ALTER TABLE client_meetings ENABLE ROW LEVEL SECURITY;

CREATE POLICY client_change_requests_client_select ON client_change_requests
  FOR SELECT TO public
  USING (
    public.auth_user_role() = 'client'
    AND org_id = public.auth_user_org_id()
    AND deleted_at IS NULL
    AND EXISTS (
      SELECT 1
      FROM project_assignments pa
      WHERE pa.project_id = client_change_requests.project_id
        AND pa.user_id = public.current_user_id()
        AND pa.is_active = TRUE
        AND pa.deleted_at IS NULL
    )
  );

CREATE POLICY client_change_requests_client_insert ON client_change_requests
  FOR INSERT TO public
  WITH CHECK (
    public.auth_user_role() = 'client'
    AND org_id = public.auth_user_org_id()
    AND submitted_by = public.current_user_id()
    AND EXISTS (
      SELECT 1
      FROM project_assignments pa
      WHERE pa.project_id = client_change_requests.project_id
        AND pa.user_id = public.current_user_id()
        AND pa.is_active = TRUE
        AND pa.deleted_at IS NULL
    )
  );

CREATE POLICY client_change_requests_internal_select ON client_change_requests
  FOR SELECT TO public
  USING (
    public.auth_user_role() IN ('delivery_manager', 'bsg_leadership')
    AND org_id = public.auth_user_org_id()
    OR public.auth_user_role() = 'super_admin'
  );

CREATE POLICY client_change_requests_manager_all ON client_change_requests
  FOR ALL TO public
  USING (
    (
      public.auth_user_role() = 'delivery_manager'
      AND org_id = public.auth_user_org_id()
    )
    OR public.auth_user_role() = 'super_admin'
  )
  WITH CHECK (
    (
      public.auth_user_role() = 'delivery_manager'
      AND org_id = public.auth_user_org_id()
    )
    OR public.auth_user_role() = 'super_admin'
  );

CREATE POLICY client_deliverables_client_select ON client_deliverables
  FOR SELECT TO public
  USING (
    public.auth_user_role() = 'client'
    AND org_id = public.auth_user_org_id()
    AND client_visible = TRUE
    AND deleted_at IS NULL
    AND EXISTS (
      SELECT 1
      FROM project_assignments pa
      WHERE pa.project_id = client_deliverables.project_id
        AND pa.user_id = public.current_user_id()
        AND pa.is_active = TRUE
        AND pa.deleted_at IS NULL
    )
  );

CREATE POLICY client_deliverables_internal_select ON client_deliverables
  FOR SELECT TO public
  USING (
    public.auth_user_role() IN ('delivery_manager', 'bsg_leadership')
    AND org_id = public.auth_user_org_id()
    OR public.auth_user_role() = 'super_admin'
  );

CREATE POLICY client_deliverables_manager_all ON client_deliverables
  FOR ALL TO public
  USING (
    (
      public.auth_user_role() = 'delivery_manager'
      AND org_id = public.auth_user_org_id()
    )
    OR public.auth_user_role() = 'super_admin'
  )
  WITH CHECK (
    (
      public.auth_user_role() = 'delivery_manager'
      AND org_id = public.auth_user_org_id()
    )
    OR public.auth_user_role() = 'super_admin'
  );

CREATE POLICY client_meetings_client_select ON client_meetings
  FOR SELECT TO public
  USING (
    public.auth_user_role() = 'client'
    AND org_id = public.auth_user_org_id()
    AND client_visible = TRUE
    AND deleted_at IS NULL
    AND EXISTS (
      SELECT 1
      FROM project_assignments pa
      WHERE pa.project_id = client_meetings.project_id
        AND pa.user_id = public.current_user_id()
        AND pa.is_active = TRUE
        AND pa.deleted_at IS NULL
    )
  );

CREATE POLICY client_meetings_internal_select ON client_meetings
  FOR SELECT TO public
  USING (
    public.auth_user_role() IN ('delivery_manager', 'bsg_leadership')
    AND org_id = public.auth_user_org_id()
    OR public.auth_user_role() = 'super_admin'
  );

CREATE POLICY client_meetings_manager_all ON client_meetings
  FOR ALL TO public
  USING (
    (
      public.auth_user_role() = 'delivery_manager'
      AND org_id = public.auth_user_org_id()
    )
    OR public.auth_user_role() = 'super_admin'
  )
  WITH CHECK (
    (
      public.auth_user_role() = 'delivery_manager'
      AND org_id = public.auth_user_org_id()
    )
    OR public.auth_user_role() = 'super_admin'
  );
