-- Quality error taxonomy reference table
CREATE TABLE IF NOT EXISTS quality_error_categories (
  id               UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  code             TEXT NOT NULL UNIQUE,
  name             TEXT NOT NULL,
  description      TEXT,
  severity_weight  NUMERIC(3,2),
  is_active        BOOLEAN NOT NULL DEFAULT TRUE,
  created_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at       TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TRIGGER quality_error_categories_updated_at
  BEFORE UPDATE ON quality_error_categories
  FOR EACH ROW EXECUTE FUNCTION set_updated_at();

-- Seed ERR-01 through ERR-07 + ERR-OTHER per spec §7.3
INSERT INTO quality_error_categories (code, name, description, severity_weight) VALUES
  ('ERR-01', 'Boundary precision',  'Inaccurate placement of annotation boundaries',                   0.70),
  ('ERR-02', 'Class confusion',     'Item annotated with the wrong class label',                       0.90),
  ('ERR-03', 'Missed object',       'Annotatable item not labeled',                                    0.80),
  ('ERR-04', 'Guideline ambiguity', 'Annotation inconsistent with SOP but SOP is unclear',             0.50),
  ('ERR-05', 'False positive',      'Non-annotatable item incorrectly labeled',                        0.70),
  ('ERR-06', 'Attribute error',     'Correct class but wrong attribute (e.g. severity, orientation)',  0.60),
  ('ERR-07', 'Tool error',          'Correct intent but annotation tool used incorrectly',             0.40),
  ('ERR-OTHER', 'Other',            'Errors not fitting above categories (must include free-text note)', 0.50)
ON CONFLICT (code) DO UPDATE SET
  name             = EXCLUDED.name,
  description      = EXCLUDED.description,
  severity_weight  = EXCLUDED.severity_weight;

-- RLS: all roles can read; only super_admin can write
ALTER TABLE quality_error_categories ENABLE ROW LEVEL SECURITY;
CREATE POLICY qec_read ON quality_error_categories FOR SELECT TO public USING (true);
CREATE POLICY qec_super_admin_write ON quality_error_categories FOR ALL TO public
  USING (current_setting('app.role', true) = 'super_admin')
  WITH CHECK (current_setting('app.role', true) = 'super_admin');
