-- Phase F: durable Governance background jobs.

CREATE TABLE IF NOT EXISTS governance_jobs (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  org_id UUID NOT NULL REFERENCES organisations (id) ON DELETE RESTRICT,
  project_id UUID REFERENCES projects (id) ON DELETE CASCADE,
  job_type TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'queued'
    CHECK (status IN (
      'queued', 'running', 'retry_scheduled', 'succeeded', 'failed',
      'cancellation_requested', 'cancelled'
    )),
  requested_by UUID NOT NULL REFERENCES users (id) ON DELETE RESTRICT,
  requested_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  started_at TIMESTAMPTZ,
  completed_at TIMESTAMPTZ,
  progress_stage TEXT NOT NULL DEFAULT 'queued',
  progress_percent INTEGER NOT NULL DEFAULT 0 CHECK (progress_percent BETWEEN 0 AND 100),
  attempt_count INTEGER NOT NULL DEFAULT 0 CHECK (attempt_count >= 0),
  max_attempts INTEGER NOT NULL DEFAULT 3 CHECK (max_attempts BETWEEN 1 AND 10),
  next_attempt_at TIMESTAMPTZ,
  idempotency_key TEXT NOT NULL,
  request_payload JSONB NOT NULL DEFAULT '{}'::jsonb,
  result_record_type TEXT,
  result_record_id UUID,
  result_data JSONB,
  error_code TEXT,
  error_message TEXT,
  heartbeat_at TIMESTAMPTZ,
  worker_id TEXT,
  cancel_requested_at TIMESTAMPTZ,
  queue_wait_ms BIGINT,
  processing_ms BIGINT,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE UNIQUE INDEX IF NOT EXISTS governance_jobs_active_idempotency_uidx
  ON governance_jobs (idempotency_key)
  WHERE status IN ('queued', 'running', 'retry_scheduled', 'cancellation_requested');

CREATE INDEX IF NOT EXISTS governance_jobs_queue_idx
  ON governance_jobs (status, next_attempt_at, requested_at);
CREATE INDEX IF NOT EXISTS governance_jobs_org_requested_idx
  ON governance_jobs (org_id, requested_at DESC);
CREATE INDEX IF NOT EXISTS governance_jobs_project_requested_idx
  ON governance_jobs (project_id, requested_at DESC)
  WHERE project_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS governance_jobs_requester_requested_idx
  ON governance_jobs (requested_by, requested_at DESC);

CREATE TABLE IF NOT EXISTS governance_job_events (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  org_id UUID NOT NULL REFERENCES organisations (id) ON DELETE RESTRICT,
  project_id UUID REFERENCES projects (id) ON DELETE CASCADE,
  job_id UUID NOT NULL REFERENCES governance_jobs (id) ON DELETE CASCADE,
  event_type TEXT NOT NULL,
  actor_user_id UUID REFERENCES users (id) ON DELETE SET NULL,
  event_metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS governance_job_events_job_created_idx
  ON governance_job_events (job_id, created_at);
CREATE INDEX IF NOT EXISTS governance_job_events_org_created_idx
  ON governance_job_events (org_id, created_at);

ALTER TABLE governance_jobs ENABLE ROW LEVEL SECURITY;
ALTER TABLE governance_job_events ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS governance_jobs_org_select ON governance_jobs;
CREATE POLICY governance_jobs_org_select
  ON governance_jobs FOR SELECT TO public
  USING (
    public.auth_user_role() = 'super_admin'
    OR (
      org_id = public.auth_user_org_id()
      AND public.auth_user_role() IN ('delivery_manager', 'bsg_leadership')
      AND requested_by = public.current_user_id()
    )
  );

DROP POLICY IF EXISTS governance_jobs_internal_write ON governance_jobs;
CREATE POLICY governance_jobs_internal_write
  ON governance_jobs FOR ALL TO public
  USING (
    public.auth_user_role() = 'super_admin'
    OR (
      org_id = public.auth_user_org_id()
      AND requested_by = public.current_user_id()
      AND public.auth_user_role() IN ('delivery_manager', 'bsg_leadership')
    )
  )
  WITH CHECK (
    public.auth_user_role() = 'super_admin'
    OR (
      org_id = public.auth_user_org_id()
      AND requested_by = public.current_user_id()
      AND public.auth_user_role() IN ('delivery_manager', 'bsg_leadership')
    )
  );

DROP POLICY IF EXISTS governance_job_events_org_select ON governance_job_events;
CREATE POLICY governance_job_events_org_select
  ON governance_job_events FOR SELECT TO public
  USING (
    public.auth_user_role() = 'super_admin'
    OR EXISTS (
      SELECT 1
      FROM governance_jobs job
      WHERE job.id = governance_job_events.job_id
        AND job.org_id = public.auth_user_org_id()
        AND job.requested_by = public.current_user_id()
        AND public.auth_user_role() IN ('delivery_manager', 'bsg_leadership')
    )
  );

DROP POLICY IF EXISTS governance_job_events_internal_write ON governance_job_events;
CREATE POLICY governance_job_events_internal_write
  ON governance_job_events FOR INSERT TO public
  WITH CHECK (
    public.auth_user_role() = 'super_admin'
    OR EXISTS (
      SELECT 1
      FROM governance_jobs job
      WHERE job.id = governance_job_events.job_id
        AND job.org_id = public.auth_user_org_id()
        AND job.requested_by = public.current_user_id()
        AND public.auth_user_role() IN ('delivery_manager', 'bsg_leadership')
    )
  );
