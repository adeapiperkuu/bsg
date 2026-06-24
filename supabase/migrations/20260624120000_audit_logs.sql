CREATE TABLE audit_logs (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  org_id UUID NOT NULL REFERENCES organisations(id) ON DELETE RESTRICT,
  project_id UUID REFERENCES projects(id) ON DELETE SET NULL,
  event_type TEXT NOT NULL,
  payload JSONB NOT NULL DEFAULT '{}'::jsonb,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX audit_logs_org_id_idx ON audit_logs (org_id);
CREATE INDEX audit_logs_project_id_idx ON audit_logs (project_id);
CREATE INDEX audit_logs_event_type_idx ON audit_logs (event_type);
CREATE INDEX audit_logs_created_at_idx ON audit_logs (created_at);

ALTER TABLE audit_logs ENABLE ROW LEVEL SECURITY;
