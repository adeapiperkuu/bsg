-- Client → Project (programs) → Scope (projects) hierarchy.
-- UI labels: programs = "Project", projects = "Scope".
-- Client reports remain attached to projects (scopes).

CREATE TABLE IF NOT EXISTS programs (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  org_id UUID NOT NULL REFERENCES organisations (id) ON DELETE RESTRICT,
  name TEXT NOT NULL,
  description TEXT,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  deleted_at TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS programs_org_id_idx ON programs (org_id);
CREATE UNIQUE INDEX IF NOT EXISTS programs_org_name_active_uidx
  ON programs (org_id, lower(name))
  WHERE deleted_at IS NULL;

CREATE TRIGGER programs_updated_at
BEFORE UPDATE ON programs
FOR EACH ROW EXECUTE FUNCTION set_updated_at();

ALTER TABLE programs ENABLE ROW LEVEL SECURITY;

CREATE POLICY programs_client_select ON programs FOR SELECT TO public
  USING (
    public.auth_user_role() = 'client'
    AND org_id = public.auth_user_org_id()
    AND deleted_at IS NULL
  );

CREATE POLICY programs_dm_all ON programs FOR ALL TO public
  USING (public.auth_user_role() = 'delivery_manager' AND org_id = public.auth_user_org_id())
  WITH CHECK (public.auth_user_role() = 'delivery_manager' AND org_id = public.auth_user_org_id());

CREATE POLICY programs_leadership_select ON programs FOR SELECT TO public
  USING (public.auth_user_role() = 'bsg_leadership' AND deleted_at IS NULL);

CREATE POLICY programs_super_admin_all ON programs FOR ALL TO public
  USING (public.auth_user_role() = 'super_admin')
  WITH CHECK (public.auth_user_role() = 'super_admin');

ALTER TABLE projects
  ADD COLUMN IF NOT EXISTS program_id UUID REFERENCES programs (id) ON DELETE SET NULL;

CREATE INDEX IF NOT EXISTS projects_program_id_idx ON projects (program_id);

-- Backfill: group existing scopes into projects by stripping trailing numbers
-- and the organisation's first word (e.g. "Northwind Annotation Sprint 13" → "Annotation Sprint").
WITH named AS (
  SELECT
    p.id AS project_id,
    p.org_id,
    NULLIF(
      trim(
        regexp_replace(
          regexp_replace(
            p.name,
            '^\s*' || split_part(o.name, ' ', 1) || '\s+',
            '',
            'i'
          ),
          '\s+[0-9]+$',
          ''
        )
      ),
      ''
    ) AS program_name
  FROM projects p
  JOIN organisations o ON o.id = p.org_id
  WHERE p.deleted_at IS NULL
    AND p.program_id IS NULL
),
resolved AS (
  SELECT
    project_id,
    org_id,
    COALESCE(program_name, 'General') AS program_name
  FROM named
)
INSERT INTO programs (org_id, name, description)
SELECT DISTINCT r.org_id, r.program_name, 'Auto-grouped from existing scopes'
FROM resolved r
WHERE NOT EXISTS (
  SELECT 1
  FROM programs existing
  WHERE existing.org_id = r.org_id
    AND lower(existing.name) = lower(r.program_name)
    AND existing.deleted_at IS NULL
);

WITH named AS (
  SELECT
    p.id AS project_id,
    p.org_id,
    NULLIF(
      trim(
        regexp_replace(
          regexp_replace(
            p.name,
            '^\s*' || split_part(o.name, ' ', 1) || '\s+',
            '',
            'i'
          ),
          '\s+[0-9]+$',
          ''
        )
      ),
      ''
    ) AS program_name
  FROM projects p
  JOIN organisations o ON o.id = p.org_id
  WHERE p.deleted_at IS NULL
    AND p.program_id IS NULL
),
resolved AS (
  SELECT
    project_id,
    org_id,
    COALESCE(program_name, 'General') AS program_name
  FROM named
)
UPDATE projects p
SET program_id = ap.id
FROM resolved r
JOIN programs ap
  ON ap.org_id = r.org_id
 AND lower(ap.name) = lower(r.program_name)
 AND ap.deleted_at IS NULL
WHERE p.id = r.project_id
  AND p.program_id IS NULL;
