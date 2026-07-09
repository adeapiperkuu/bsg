-- Persist calibration briefs per project/week (generated during quality scan, read on dashboard)

CREATE TABLE calibration_briefs (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  project_id UUID NOT NULL REFERENCES projects (id) ON DELETE CASCADE,
  org_id UUID NOT NULL REFERENCES organisations (id) ON DELETE RESTRICT,
  iso_year INT NOT NULL CHECK (iso_year >= 2024),
  iso_week INT NOT NULL CHECK (iso_week BETWEEN 1 AND 53),
  candidates JSONB NOT NULL DEFAULT '[]',
  brief_text TEXT,
  signal_sent_at TIMESTAMPTZ,
  generated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  CONSTRAINT calibration_briefs_unique_week UNIQUE (project_id, iso_year, iso_week)
);

CREATE INDEX calibration_briefs_project_idx ON calibration_briefs (project_id);
