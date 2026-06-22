CREATE EXTENSION IF NOT EXISTS pgcrypto;

CREATE TYPE app_role AS ENUM ('client', 'delivery_manager', 'bsg_leadership', 'super_admin');
CREATE TYPE delivery_site AS ENUM ('india', 'kosovo');
CREATE TYPE project_status AS ENUM ('active', 'ramping', 'paused', 'completed', 'cancelled');
CREATE TYPE milestone_status AS ENUM ('pending', 'on_track', 'at_risk', 'completed', 'missed');
CREATE TYPE risk_tier AS ENUM ('low', 'medium', 'high', 'critical');
CREATE TYPE alert_type AS ENUM ('delivery_risk', 'quality_drift', 'milestone_at_risk', 'workforce_imbalance');
CREATE TYPE alert_status AS ENUM ('open', 'acknowledged', 'resolved', 'dismissed');
CREATE TYPE communication_status AS ENUM ('draft', 'in_review', 'approved', 'sent', 'rejected');
CREATE TYPE communication_type AS ENUM ('weekly_summary', 'executive_summary', 'ad_hoc');
CREATE TYPE notification_type AS ENUM (
  'risk_alert',
  'communication_pending',
  'milestone_at_risk',
  'quality_drift_detected',
  'system'
);

CREATE OR REPLACE FUNCTION set_updated_at()
RETURNS TRIGGER AS $$
BEGIN
  NEW.updated_at = now();
  RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TABLE organisations (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  name TEXT NOT NULL,
  slug TEXT NOT NULL UNIQUE,
  vertical TEXT NOT NULL,
  region TEXT NOT NULL,
  is_active BOOLEAN NOT NULL DEFAULT TRUE,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  deleted_at TIMESTAMPTZ
);

CREATE TABLE users (
  id UUID PRIMARY KEY,
  org_id UUID NOT NULL REFERENCES organisations (id) ON DELETE RESTRICT,
  email TEXT NOT NULL UNIQUE,
  full_name TEXT,
  role app_role NOT NULL,
  is_active BOOLEAN NOT NULL DEFAULT TRUE,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  deleted_at TIMESTAMPTZ
);

CREATE TABLE projects (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  org_id UUID NOT NULL REFERENCES organisations (id) ON DELETE RESTRICT,
  name TEXT NOT NULL,
  description TEXT,
  vertical TEXT NOT NULL,
  status project_status NOT NULL DEFAULT 'active',
  start_date DATE NOT NULL,
  target_end_date DATE NOT NULL,
  actual_end_date DATE,
  daily_target_units INT,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  deleted_at TIMESTAMPTZ
);

CREATE TABLE milestones (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  project_id UUID NOT NULL REFERENCES projects (id) ON DELETE CASCADE,
  org_id UUID NOT NULL REFERENCES organisations (id) ON DELETE RESTRICT,
  name TEXT NOT NULL,
  description TEXT,
  planned_date DATE NOT NULL,
  actual_date DATE,
  status milestone_status NOT NULL DEFAULT 'pending',
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  deleted_at TIMESTAMPTZ
);

CREATE TABLE throughput_snapshots (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  project_id UUID NOT NULL REFERENCES projects (id) ON DELETE CASCADE,
  org_id UUID NOT NULL REFERENCES organisations (id) ON DELETE RESTRICT,
  snapshot_date DATE NOT NULL,
  units_completed INT NOT NULL CHECK (units_completed >= 0),
  units_forecast INT CHECK (units_forecast >= 0),
  rolling_7day_units INT CHECK (rolling_7day_units >= 0),
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  CONSTRAINT throughput_snapshots_project_date_key UNIQUE (project_id, snapshot_date)
);

CREATE TABLE teams (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  project_id UUID NOT NULL REFERENCES projects (id) ON DELETE CASCADE,
  org_id UUID NOT NULL REFERENCES organisations (id) ON DELETE RESTRICT,
  name TEXT NOT NULL,
  site delivery_site NOT NULL,
  domain TEXT NOT NULL,
  is_active BOOLEAN NOT NULL DEFAULT TRUE,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  deleted_at TIMESTAMPTZ
);

CREATE TABLE annotators (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  org_id UUID NOT NULL REFERENCES organisations (id) ON DELETE RESTRICT,
  team_id UUID NOT NULL REFERENCES teams (id) ON DELETE RESTRICT,
  full_name TEXT NOT NULL,
  site delivery_site NOT NULL,
  is_sme_certified BOOLEAN NOT NULL DEFAULT FALSE,
  is_active BOOLEAN NOT NULL DEFAULT TRUE,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  deleted_at TIMESTAMPTZ
);

CREATE TABLE quality_snapshots (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  project_id UUID NOT NULL REFERENCES projects (id) ON DELETE CASCADE,
  team_id UUID NOT NULL REFERENCES teams (id) ON DELETE RESTRICT,
  org_id UUID NOT NULL REFERENCES organisations (id) ON DELETE RESTRICT,
  iso_week INT NOT NULL CHECK (iso_week BETWEEN 1 AND 53),
  iso_year INT NOT NULL CHECK (iso_year >= 2024),
  gold_set_accuracy_pct NUMERIC(5,2) CHECK (gold_set_accuracy_pct BETWEEN 0 AND 100),
  iaa_krippendorff_alpha NUMERIC(4,3) CHECK (iaa_krippendorff_alpha BETWEEN 0 AND 1),
  rework_rate_pct NUMERIC(5,2) CHECK (rework_rate_pct BETWEEN 0 AND 100),
  has_drift_alert BOOLEAN NOT NULL DEFAULT FALSE,
  drift_alert_detail TEXT,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  CONSTRAINT quality_snapshots_project_team_week_key UNIQUE (project_id, team_id, iso_year, iso_week)
);

CREATE TABLE quality_error_entries (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  quality_snapshot_id UUID NOT NULL REFERENCES quality_snapshots (id) ON DELETE CASCADE,
  org_id UUID NOT NULL REFERENCES organisations (id) ON DELETE RESTRICT,
  error_category TEXT NOT NULL,
  share_pct NUMERIC(5,2) NOT NULL CHECK (share_pct BETWEEN 0 AND 100),
  recommended_action TEXT,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE risk_alerts (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  project_id UUID NOT NULL REFERENCES projects (id) ON DELETE CASCADE,
  org_id UUID NOT NULL REFERENCES organisations (id) ON DELETE RESTRICT,
  milestone_id UUID REFERENCES milestones (id) ON DELETE SET NULL,
  alert_type alert_type NOT NULL,
  risk_tier risk_tier NOT NULL,
  title TEXT NOT NULL,
  detail TEXT NOT NULL,
  slippage_probability NUMERIC(4,3) CHECK (slippage_probability BETWEEN 0 AND 1),
  contributing_causes JSONB,
  status alert_status NOT NULL DEFAULT 'open',
  resolved_at TIMESTAMPTZ,
  resolved_by UUID REFERENCES users (id) ON DELETE SET NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  deleted_at TIMESTAMPTZ
);

CREATE TABLE bottlenecks (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  project_id UUID NOT NULL REFERENCES projects (id) ON DELETE CASCADE,
  org_id UUID NOT NULL REFERENCES organisations (id) ON DELETE RESTRICT,
  team_id UUID REFERENCES teams (id) ON DELETE SET NULL,
  title TEXT NOT NULL,
  detail TEXT NOT NULL,
  status alert_status NOT NULL DEFAULT 'open',
  resolved_at TIMESTAMPTZ,
  resolved_by UUID REFERENCES users (id) ON DELETE SET NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  deleted_at TIMESTAMPTZ
);

CREATE TABLE client_communications (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  project_id UUID NOT NULL REFERENCES projects (id) ON DELETE CASCADE,
  org_id UUID NOT NULL REFERENCES organisations (id) ON DELETE RESTRICT,
  comm_type communication_type NOT NULL,
  subject TEXT NOT NULL,
  body_draft TEXT NOT NULL,
  body_approved TEXT,
  status communication_status NOT NULL DEFAULT 'draft',
  drafted_by_agent TEXT NOT NULL,
  reviewed_by UUID REFERENCES users (id) ON DELETE SET NULL,
  reviewed_at TIMESTAMPTZ,
  approved_by UUID REFERENCES users (id) ON DELETE SET NULL,
  approved_at TIMESTAMPTZ,
  sent_at TIMESTAMPTZ,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE communication_evidence_links (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  communication_id UUID NOT NULL REFERENCES client_communications (id) ON DELETE CASCADE,
  source_table TEXT NOT NULL,
  source_row_id UUID NOT NULL,
  description TEXT NOT NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE agent_queries (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id UUID NOT NULL REFERENCES users (id) ON DELETE RESTRICT,
  org_id UUID NOT NULL REFERENCES organisations (id) ON DELETE RESTRICT,
  project_id UUID REFERENCES projects (id) ON DELETE SET NULL,
  agent_name TEXT NOT NULL,
  query_text TEXT NOT NULL,
  answer_text TEXT NOT NULL,
  model_used TEXT,
  latency_ms INT,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE agent_query_evidence_links (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  agent_query_id UUID NOT NULL REFERENCES agent_queries (id) ON DELETE CASCADE,
  source_table TEXT NOT NULL,
  source_row_id UUID NOT NULL,
  description TEXT NOT NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE client_csat_scores (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  project_id UUID NOT NULL REFERENCES projects (id) ON DELETE CASCADE,
  org_id UUID NOT NULL REFERENCES organisations (id) ON DELETE RESTRICT,
  submitted_by UUID NOT NULL REFERENCES users (id) ON DELETE RESTRICT,
  score NUMERIC(2,1) NOT NULL CHECK (score BETWEEN 1 AND 5),
  reporting_period_month DATE NOT NULL,
  comment TEXT,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  CONSTRAINT client_csat_scores_project_user_month_key UNIQUE (project_id, submitted_by, reporting_period_month)
);

CREATE TABLE metric_configurations (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  metric_key TEXT NOT NULL UNIQUE,
  display_label TEXT NOT NULL,
  is_client_visible BOOLEAN NOT NULL DEFAULT FALSE,
  display_order INT NOT NULL DEFAULT 0,
  description TEXT,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  deleted_at TIMESTAMPTZ
);

CREATE TABLE delivery_confidence_scores (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  project_id UUID NOT NULL REFERENCES projects (id) ON DELETE CASCADE,
  milestone_id UUID NOT NULL REFERENCES milestones (id) ON DELETE CASCADE,
  org_id UUID NOT NULL REFERENCES organisations (id) ON DELETE RESTRICT,
  score_pct NUMERIC(5,2) NOT NULL CHECK (score_pct BETWEEN 0 AND 100),
  forecast_completion_date DATE,
  status milestone_status NOT NULL,
  model_version TEXT,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE notifications (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id UUID NOT NULL REFERENCES users (id) ON DELETE CASCADE,
  org_id UUID NOT NULL REFERENCES organisations (id) ON DELETE RESTRICT,
  notification_type notification_type NOT NULL,
  title TEXT NOT NULL,
  body TEXT NOT NULL,
  source_table TEXT,
  source_row_id UUID,
  is_read BOOLEAN NOT NULL DEFAULT FALSE,
  sent_at TIMESTAMPTZ,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX users_org_id_idx ON users (org_id);
CREATE INDEX users_role_idx ON users (role);
CREATE INDEX projects_org_id_idx ON projects (org_id);
CREATE INDEX milestones_project_id_idx ON milestones (project_id);
CREATE INDEX throughput_snapshots_project_id_date_idx ON throughput_snapshots (project_id, snapshot_date DESC);
CREATE INDEX teams_project_id_idx ON teams (project_id);
CREATE INDEX quality_snapshots_project_id_idx ON quality_snapshots (project_id);
CREATE INDEX risk_alerts_project_id_idx ON risk_alerts (project_id);
CREATE INDEX client_communications_project_id_idx ON client_communications (project_id);
CREATE INDEX agent_queries_org_id_idx ON agent_queries (org_id);
CREATE INDEX notifications_user_id_idx ON notifications (user_id);

CREATE TRIGGER organisations_updated_at BEFORE UPDATE ON organisations FOR EACH ROW EXECUTE FUNCTION set_updated_at();
CREATE TRIGGER users_updated_at BEFORE UPDATE ON users FOR EACH ROW EXECUTE FUNCTION set_updated_at();
CREATE TRIGGER projects_updated_at BEFORE UPDATE ON projects FOR EACH ROW EXECUTE FUNCTION set_updated_at();
CREATE TRIGGER milestones_updated_at BEFORE UPDATE ON milestones FOR EACH ROW EXECUTE FUNCTION set_updated_at();
CREATE TRIGGER throughput_snapshots_updated_at BEFORE UPDATE ON throughput_snapshots FOR EACH ROW EXECUTE FUNCTION set_updated_at();
CREATE TRIGGER teams_updated_at BEFORE UPDATE ON teams FOR EACH ROW EXECUTE FUNCTION set_updated_at();
CREATE TRIGGER annotators_updated_at BEFORE UPDATE ON annotators FOR EACH ROW EXECUTE FUNCTION set_updated_at();
CREATE TRIGGER quality_snapshots_updated_at BEFORE UPDATE ON quality_snapshots FOR EACH ROW EXECUTE FUNCTION set_updated_at();
CREATE TRIGGER quality_error_entries_updated_at BEFORE UPDATE ON quality_error_entries FOR EACH ROW EXECUTE FUNCTION set_updated_at();
CREATE TRIGGER risk_alerts_updated_at BEFORE UPDATE ON risk_alerts FOR EACH ROW EXECUTE FUNCTION set_updated_at();
CREATE TRIGGER bottlenecks_updated_at BEFORE UPDATE ON bottlenecks FOR EACH ROW EXECUTE FUNCTION set_updated_at();
CREATE TRIGGER client_communications_updated_at BEFORE UPDATE ON client_communications FOR EACH ROW EXECUTE FUNCTION set_updated_at();
CREATE TRIGGER metric_configurations_updated_at BEFORE UPDATE ON metric_configurations FOR EACH ROW EXECUTE FUNCTION set_updated_at();
CREATE TRIGGER notifications_updated_at BEFORE UPDATE ON notifications FOR EACH ROW EXECUTE FUNCTION set_updated_at();

ALTER TABLE organisations ENABLE ROW LEVEL SECURITY;
ALTER TABLE users ENABLE ROW LEVEL SECURITY;
ALTER TABLE projects ENABLE ROW LEVEL SECURITY;
ALTER TABLE milestones ENABLE ROW LEVEL SECURITY;
ALTER TABLE throughput_snapshots ENABLE ROW LEVEL SECURITY;
ALTER TABLE teams ENABLE ROW LEVEL SECURITY;
ALTER TABLE annotators ENABLE ROW LEVEL SECURITY;
ALTER TABLE quality_snapshots ENABLE ROW LEVEL SECURITY;
ALTER TABLE quality_error_entries ENABLE ROW LEVEL SECURITY;
ALTER TABLE risk_alerts ENABLE ROW LEVEL SECURITY;
ALTER TABLE bottlenecks ENABLE ROW LEVEL SECURITY;
ALTER TABLE client_communications ENABLE ROW LEVEL SECURITY;
ALTER TABLE communication_evidence_links ENABLE ROW LEVEL SECURITY;
ALTER TABLE agent_queries ENABLE ROW LEVEL SECURITY;
ALTER TABLE agent_query_evidence_links ENABLE ROW LEVEL SECURITY;
ALTER TABLE client_csat_scores ENABLE ROW LEVEL SECURITY;
ALTER TABLE metric_configurations ENABLE ROW LEVEL SECURITY;
ALTER TABLE delivery_confidence_scores ENABLE ROW LEVEL SECURITY;
ALTER TABLE notifications ENABLE ROW LEVEL SECURITY;
