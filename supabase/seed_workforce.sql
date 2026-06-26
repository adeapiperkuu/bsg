-- Workforce & Capability Agent demo seed data.
--
-- Purpose: populate the Workforce dashboards (utilization, skills, requirements,
-- certifications, training, capability gaps) with realistic data for the
-- Northwind demo organisation so the full workflow can be exercised end-to-end.
--
-- Design notes:
--   * Idempotent: every statement is guarded with NOT EXISTS, so re-running
--     the file never creates duplicates.
--   * Name-scoped: all rows are resolved by stable org / project / team /
--     annotator / skill names instead of hard-coded random UUIDs.
--   * Tenant-scoped: everything is attached to the 'Northwind Analytics' org and
--     a canonical 'Northwind Content Shield' project, compatible with existing RLS.
--   * Requires the 'Northwind Analytics' organisation to already exist (created by
--     supabase/seed.sql). If it is missing, every statement safely no-ops.
--
-- How to apply:
--   * Via the helper (recommended):
--       cd backend
--       .\.venv\Scripts\python.exe ..\supabase\apply_seed.py --file ..\supabase\seed_workforce.sql
--   * Or paste the contents into the Supabase SQL Editor and run.
--
-- Capability gaps are intentionally NOT inserted here. Seed the underlying
-- requirements / skills / training / utilization data with this file, then open
-- the Workforce page for the 'Northwind Content Shield' project and click
-- "Detect gaps" to let the detection engine generate them (avoids duplicates).

BEGIN;

-- ---------------------------------------------------------------------------
-- 1. Canonical demo project (Northwind Content Shield)
-- ---------------------------------------------------------------------------
INSERT INTO projects (org_id, name, description, vertical, status, start_date, target_end_date, daily_target_units)
SELECT o.id,
       'Northwind Content Shield',
       'Content moderation and trust-and-safety delivery engagement for Northwind Analytics.',
       'content_moderation',
       'active',
       DATE '2026-01-05',
       DATE '2026-12-31',
       1200
FROM organisations o
WHERE o.name = 'Northwind Analytics'
  AND o.deleted_at IS NULL
  AND NOT EXISTS (
    SELECT 1 FROM projects p
    WHERE p.org_id = o.id AND p.name = 'Northwind Content Shield' AND p.deleted_at IS NULL
  );

-- ---------------------------------------------------------------------------
-- 2. Teams (overloaded / normal / underutilized scenarios)
-- ---------------------------------------------------------------------------
INSERT INTO teams (project_id, org_id, name, site, domain, is_active)
SELECT p.id, p.org_id, v.team_name, v.site::delivery_site, 'content_review', TRUE
FROM projects p
JOIN organisations o ON o.id = p.org_id
JOIN (VALUES
    ('Content Shield - Vision QA Pod', 'india'),
    ('Content Shield - Content Review Pod', 'kosovo'),
    ('Content Shield - Safety Review Pod', 'india')
  ) AS v(team_name, site) ON TRUE
WHERE o.name = 'Northwind Analytics'
  AND p.name = 'Northwind Content Shield'
  AND p.deleted_at IS NULL
  AND NOT EXISTS (
    SELECT 1 FROM teams t
    WHERE t.project_id = p.id AND t.name = v.team_name AND t.deleted_at IS NULL
  );

-- ---------------------------------------------------------------------------
-- 3. Annotators (synthetic, role-gated demo workforce)
-- ---------------------------------------------------------------------------
INSERT INTO annotators (org_id, team_id, full_name, site, is_sme_certified, is_active)
SELECT t.org_id, t.id, v.full_name, t.site, v.is_sme, TRUE
FROM teams t
JOIN projects p ON p.id = t.project_id
JOIN organisations o ON o.id = p.org_id
JOIN (VALUES
    ('Content Shield - Vision QA Pod', 'Aria Vision', TRUE),
    ('Content Shield - Vision QA Pod', 'Cole Pixel', FALSE),
    ('Content Shield - Vision QA Pod', 'Devi Frame', FALSE),
    ('Content Shield - Vision QA Pod', 'Mateo Lens', FALSE),
    ('Content Shield - Content Review Pod', 'Bela Cizmja', TRUE),
    ('Content Shield - Content Review Pod', 'Ilir Reka', FALSE),
    ('Content Shield - Content Review Pod', 'Sara Berg', FALSE),
    ('Content Shield - Content Review Pod', 'Noa Quist', FALSE),
    ('Content Shield - Safety Review Pod', 'Petra Cohen', TRUE),
    ('Content Shield - Safety Review Pod', 'Owen Shaw', FALSE),
    ('Content Shield - Safety Review Pod', 'Lena Voss', FALSE),
    ('Content Shield - Safety Review Pod', 'Rhea Mond', FALSE)
  ) AS v(team_name, full_name, is_sme) ON v.team_name = t.name
WHERE o.name = 'Northwind Analytics'
  AND p.name = 'Northwind Content Shield'
  AND t.deleted_at IS NULL
  AND NOT EXISTS (
    SELECT 1 FROM annotators a
    WHERE a.team_id = t.id AND a.full_name = v.full_name AND a.deleted_at IS NULL
  );

-- ---------------------------------------------------------------------------
-- 4. Skills (org-scoped catalog)
-- ---------------------------------------------------------------------------
INSERT INTO skills (org_id, name, category, domain, description, is_critical)
SELECT o.id, v.name, v.category, v.domain, v.descr, v.is_critical
FROM organisations o
JOIN (VALUES
    ('Computer Vision QA', 'Quality', 'computer_vision', 'Quality assurance for computer-vision annotation output.', TRUE),
    ('Content Review', 'Operations', 'content_review', 'General content moderation and review.', FALSE),
    ('Medical Review', 'Life Sciences', 'medical', 'Clinical and medical content review.', TRUE),
    ('Safety Policy Review', 'Trust and Safety', 'content_review', 'Safety policy enforcement and escalation review.', TRUE),
    ('SME Calibration', 'Quality', 'quality', 'Subject-matter-expert calibration and adjudication.', FALSE)
  ) AS v(name, category, domain, descr, is_critical) ON TRUE
WHERE o.name = 'Northwind Analytics'
  AND o.deleted_at IS NULL
  AND NOT EXISTS (
    SELECT 1 FROM skills s
    WHERE s.org_id = o.id AND s.name = v.name AND s.deleted_at IS NULL
  );

-- ---------------------------------------------------------------------------
-- 5. Project skill requirements (includes a critical Safety Policy shortage)
-- ---------------------------------------------------------------------------
INSERT INTO project_skill_requirements (org_id, project_id, skill_id, required_proficiency_level, required_headcount, required_sme_count, priority)
SELECT p.org_id, p.id, s.id, v.level, v.headcount, v.sme_count, v.priority
FROM projects p
JOIN organisations o ON o.id = p.org_id
JOIN skills s ON s.org_id = p.org_id AND s.deleted_at IS NULL
JOIN (VALUES
    ('Computer Vision QA', 'advanced', 3, 1, 'high'),
    ('Content Review', 'intermediate', 4, 1, 'medium'),
    ('Safety Policy Review', 'advanced', 3, 2, 'critical'),
    ('SME Calibration', 'expert', 2, 1, 'high'),
    ('Medical Review', 'advanced', 2, 1, 'high')
  ) AS v(skill_name, level, headcount, sme_count, priority) ON v.skill_name = s.name
WHERE o.name = 'Northwind Analytics'
  AND p.name = 'Northwind Content Shield'
  AND p.deleted_at IS NULL
  AND NOT EXISTS (
    SELECT 1 FROM project_skill_requirements r
    WHERE r.project_id = p.id AND r.skill_id = s.id AND r.deleted_at IS NULL
  );

-- ---------------------------------------------------------------------------
-- 6. Annotator skills (mix of proficiency levels; some requirements under-covered)
-- ---------------------------------------------------------------------------
INSERT INTO annotator_skills (org_id, annotator_id, skill_id, proficiency_level)
SELECT a.org_id, a.id, s.id, v.level
FROM annotators a
JOIN teams t ON t.id = a.team_id
JOIN projects p ON p.id = t.project_id
JOIN organisations o ON o.id = p.org_id
JOIN skills s ON s.org_id = a.org_id AND s.deleted_at IS NULL
JOIN (VALUES
    ('Aria Vision', 'Computer Vision QA', 'expert'),
    ('Aria Vision', 'Content Review', 'advanced'),
    ('Cole Pixel', 'Computer Vision QA', 'advanced'),
    ('Devi Frame', 'Computer Vision QA', 'advanced'),
    ('Mateo Lens', 'Content Review', 'intermediate'),
    ('Bela Cizmja', 'SME Calibration', 'expert'),
    ('Bela Cizmja', 'Content Review', 'advanced'),
    ('Ilir Reka', 'Content Review', 'intermediate'),
    ('Sara Berg', 'Content Review', 'advanced'),
    ('Noa Quist', 'Content Review', 'beginner'),
    ('Petra Cohen', 'Safety Policy Review', 'advanced'),
    ('Owen Shaw', 'Safety Policy Review', 'intermediate'),
    ('Lena Voss', 'Content Review', 'intermediate'),
    ('Rhea Mond', 'Content Review', 'beginner')
  ) AS v(full_name, skill_name, level) ON v.full_name = a.full_name AND v.skill_name = s.name
WHERE o.name = 'Northwind Analytics'
  AND p.name = 'Northwind Content Shield'
  AND a.deleted_at IS NULL
  AND NOT EXISTS (
    SELECT 1 FROM annotator_skills x
    WHERE x.annotator_id = a.id AND x.skill_id = s.id AND x.deleted_at IS NULL
  );

-- ---------------------------------------------------------------------------
-- 7. Certification definitions
-- ---------------------------------------------------------------------------
INSERT INTO certifications (org_id, name, issuing_body, description, validity_months, is_required_for_sme)
SELECT o.id, v.name, v.body, v.descr, v.months, v.sme
FROM organisations o
JOIN (VALUES
    ('Content Safety Level 2', 'BSG Academy', 'Baseline content safety review certification.', 12, FALSE),
    ('SME Calibration Certificate', 'BSG Academy', 'Subject-matter-expert calibration certification.', 24, TRUE),
    ('Vision QA Specialist', 'BSG Academy', 'Computer-vision quality assurance specialist certification.', 12, FALSE)
  ) AS v(name, body, descr, months, sme) ON TRUE
WHERE o.name = 'Northwind Analytics'
  AND o.deleted_at IS NULL
  AND NOT EXISTS (
    SELECT 1 FROM certifications c
    WHERE c.org_id = o.id AND c.name = v.name AND c.deleted_at IS NULL
  );

-- ---------------------------------------------------------------------------
-- 8. Employee certifications (active / expired / pending_review)
-- ---------------------------------------------------------------------------
INSERT INTO employee_certifications (org_id, annotator_id, certification_id, issued_at, expires_at, status)
SELECT a.org_id, a.id, c.id, v.issued, v.expires, v.status
FROM annotators a
JOIN teams t ON t.id = a.team_id
JOIN projects p ON p.id = t.project_id
JOIN organisations o ON o.id = p.org_id
JOIN certifications c ON c.org_id = a.org_id AND c.deleted_at IS NULL
JOIN (VALUES
    ('Aria Vision', 'Vision QA Specialist', DATE '2026-02-01', DATE '2027-02-01', 'active'),
    ('Bela Cizmja', 'SME Calibration Certificate', DATE '2025-06-01', DATE '2027-06-01', 'active'),
    ('Petra Cohen', 'Content Safety Level 2', DATE '2024-01-01', DATE '2025-01-01', 'expired'),
    ('Owen Shaw', 'Content Safety Level 2', NULL::date, NULL::date, 'pending_review')
  ) AS v(full_name, cert_name, issued, expires, status) ON v.full_name = a.full_name AND v.cert_name = c.name
WHERE o.name = 'Northwind Analytics'
  AND p.name = 'Northwind Content Shield'
  AND a.deleted_at IS NULL
  AND NOT EXISTS (
    SELECT 1 FROM employee_certifications e
    WHERE e.annotator_id = a.id AND e.certification_id = c.id AND e.deleted_at IS NULL
  );

-- ---------------------------------------------------------------------------
-- 9. Training programs (linked to skills)
-- ---------------------------------------------------------------------------
INSERT INTO training_programs (org_id, skill_id, name, description, required_for_skill_level, is_mandatory)
SELECT o.id, s.id, v.name, v.descr, v.level, v.mandatory
FROM organisations o
JOIN (VALUES
    ('Content Safety Foundations', 'Content Review', 'Foundational content safety review training.', 'intermediate', TRUE),
    ('Advanced Vision QA', 'Computer Vision QA', 'Advanced computer-vision QA techniques.', 'advanced', FALSE),
    ('Safety Policy Deep Dive', 'Safety Policy Review', 'In-depth safety policy enforcement training.', 'advanced', TRUE),
    ('SME Calibration Workshop', 'SME Calibration', 'Calibration workshop for subject-matter experts.', 'expert', FALSE)
  ) AS v(name, skill_name, descr, level, mandatory) ON TRUE
LEFT JOIN skills s ON s.org_id = o.id AND s.name = v.skill_name AND s.deleted_at IS NULL
WHERE o.name = 'Northwind Analytics'
  AND o.deleted_at IS NULL
  AND NOT EXISTS (
    SELECT 1 FROM training_programs tp
    WHERE tp.org_id = o.id AND tp.name = v.name AND tp.deleted_at IS NULL
  );

-- ---------------------------------------------------------------------------
-- 10. Training records (completed / in_progress / failed / expired)
-- ---------------------------------------------------------------------------
INSERT INTO training_records (org_id, annotator_id, training_program_id, status, started_at, completed_at, score_pct)
SELECT a.org_id, a.id, tp.id, v.status, v.started, v.completed, v.score
FROM annotators a
JOIN teams t ON t.id = a.team_id
JOIN projects p ON p.id = t.project_id
JOIN organisations o ON o.id = p.org_id
JOIN training_programs tp ON tp.org_id = a.org_id AND tp.deleted_at IS NULL
JOIN (VALUES
    ('Aria Vision', 'Advanced Vision QA', 'completed', TIMESTAMPTZ '2026-02-10 09:00:00+00', TIMESTAMPTZ '2026-03-01 17:00:00+00', 95.00),
    ('Cole Pixel', 'Advanced Vision QA', 'in_progress', TIMESTAMPTZ '2026-05-01 09:00:00+00', NULL::timestamptz, NULL::numeric),
    ('Owen Shaw', 'Safety Policy Deep Dive', 'failed', TIMESTAMPTZ '2026-04-01 09:00:00+00', TIMESTAMPTZ '2026-04-15 17:00:00+00', 48.00),
    ('Mateo Lens', 'Content Safety Foundations', 'expired', TIMESTAMPTZ '2025-01-10 09:00:00+00', TIMESTAMPTZ '2025-02-01 17:00:00+00', 80.00),
    ('Noa Quist', 'Content Safety Foundations', 'in_progress', TIMESTAMPTZ '2026-06-01 09:00:00+00', NULL::timestamptz, NULL::numeric),
    ('Ilir Reka', 'Content Safety Foundations', 'completed', TIMESTAMPTZ '2026-03-01 09:00:00+00', TIMESTAMPTZ '2026-03-20 17:00:00+00', 88.00)
  ) AS v(full_name, program_name, status, started, completed, score) ON v.full_name = a.full_name AND v.program_name = tp.name
WHERE o.name = 'Northwind Analytics'
  AND p.name = 'Northwind Content Shield'
  AND a.deleted_at IS NULL
  AND NOT EXISTS (
    SELECT 1 FROM training_records r
    WHERE r.annotator_id = a.id AND r.training_program_id = tp.id AND r.deleted_at IS NULL
  );

-- ---------------------------------------------------------------------------
-- 11. Utilization snapshots (team-level; overloaded > 85%, normal, under < 60%,
--      plus one overtime value > 100% to verify the overtime chart)
-- ---------------------------------------------------------------------------
INSERT INTO utilization_snapshots (org_id, project_id, team_id, annotator_id, snapshot_date, allocated_hours, available_hours, utilization_pct, notes)
SELECT t.org_id, p.id, t.id, NULL, v.snap_date, v.allocated, v.available, v.util, v.notes
FROM teams t
JOIN projects p ON p.id = t.project_id
JOIN organisations o ON o.id = p.org_id
JOIN (VALUES
    ('Content Shield - Vision QA Pod', DATE '2026-06-15', 92.00, 100.00, 92.00, 'Sustained high load ahead of policy launch.'),
    ('Content Shield - Vision QA Pod', DATE '2026-06-22', 108.00, 100.00, 108.00, 'Overtime to clear the review backlog.'),
    ('Content Shield - Content Review Pod', DATE '2026-06-22', 72.00, 100.00, 72.00, 'Healthy steady-state utilization.'),
    ('Content Shield - Safety Review Pod', DATE '2026-06-22', 48.00, 100.00, 48.00, 'Underutilized; capacity available for reallocation.')
  ) AS v(team_name, snap_date, allocated, available, util, notes) ON v.team_name = t.name
WHERE o.name = 'Northwind Analytics'
  AND p.name = 'Northwind Content Shield'
  AND t.deleted_at IS NULL
  AND NOT EXISTS (
    SELECT 1 FROM utilization_snapshots u
    WHERE u.team_id = t.id AND u.snapshot_date = v.snap_date AND u.annotator_id IS NULL AND u.deleted_at IS NULL
  );

-- ---------------------------------------------------------------------------
-- 12. Compatibility demo data for the existing generated project most often
--     used in local QA: Northwind Content Shield 4.
--
-- The generated baseline seed already contains this project, its teams, and
-- annotators. This block attaches the same workforce demo signals to that
-- existing project so the default UI selection shows populated dashboards.
-- ---------------------------------------------------------------------------
INSERT INTO project_skill_requirements (org_id, project_id, skill_id, required_proficiency_level, required_headcount, required_sme_count, priority)
SELECT p.org_id, p.id, s.id, v.level, v.headcount, v.sme_count, v.priority
FROM projects p
JOIN organisations o ON o.id = p.org_id
JOIN skills s ON s.org_id = p.org_id AND s.deleted_at IS NULL
JOIN (VALUES
    ('Computer Vision QA', 'advanced', 6, 2, 'high'),
    ('Content Review', 'intermediate', 8, 2, 'medium'),
    ('Safety Policy Review', 'advanced', 4, 2, 'critical'),
    ('SME Calibration', 'expert', 3, 2, 'high'),
    ('Medical Review', 'advanced', 3, 1, 'high')
  ) AS v(skill_name, level, headcount, sme_count, priority) ON v.skill_name = s.name
WHERE o.name = 'Northwind Analytics'
  AND p.name = 'Northwind Content Shield 4'
  AND p.deleted_at IS NULL
  AND NOT EXISTS (
    SELECT 1 FROM project_skill_requirements r
    WHERE r.project_id = p.id AND r.skill_id = s.id AND r.deleted_at IS NULL
  );

WITH ranked_annotators AS (
  SELECT
    a.id,
    a.org_id,
    t.name AS team_name,
    ROW_NUMBER() OVER (PARTITION BY t.id ORDER BY a.full_name, a.id) AS rn
  FROM annotators a
  JOIN teams t ON t.id = a.team_id
  JOIN projects p ON p.id = t.project_id
  JOIN organisations o ON o.id = p.org_id
  WHERE o.name = 'Northwind Analytics'
    AND p.name = 'Northwind Content Shield 4'
    AND a.deleted_at IS NULL
)
INSERT INTO annotator_skills (org_id, annotator_id, skill_id, proficiency_level)
SELECT ra.org_id, ra.id, s.id, v.level
FROM ranked_annotators ra
JOIN skills s ON s.org_id = ra.org_id AND s.deleted_at IS NULL
JOIN (VALUES
    ('Northwind Content Shield 4 Team 1', 1, 'Computer Vision QA', 'expert'),
    ('Northwind Content Shield 4 Team 1', 2, 'Computer Vision QA', 'advanced'),
    ('Northwind Content Shield 4 Team 1', 3, 'Computer Vision QA', 'advanced'),
    ('Northwind Content Shield 4 Team 1', 4, 'SME Calibration', 'advanced'),
    ('Northwind Content Shield 4 Team 2', 1, 'Content Review', 'expert'),
    ('Northwind Content Shield 4 Team 2', 2, 'Content Review', 'advanced'),
    ('Northwind Content Shield 4 Team 2', 3, 'Content Review', 'intermediate'),
    ('Northwind Content Shield 4 Team 2', 4, 'Safety Policy Review', 'intermediate'),
    ('Northwind Content Shield 4 Team 2', 5, 'Content Review', 'beginner'),
    ('Northwind Content Shield 4 Team 3', 1, 'Computer Vision QA', 'advanced'),
    ('Northwind Content Shield 4 Team 3', 2, 'Safety Policy Review', 'advanced'),
    ('Northwind Content Shield 4 Team 3', 3, 'Medical Review', 'intermediate'),
    ('Northwind Content Shield 4 Team 3', 4, 'SME Calibration', 'expert'),
    ('Northwind Content Shield 4 Team 3', 5, 'Content Review', 'beginner')
  ) AS v(team_name, rn, skill_name, level)
    ON v.team_name = ra.team_name AND v.rn = ra.rn AND v.skill_name = s.name
WHERE NOT EXISTS (
  SELECT 1 FROM annotator_skills x
  WHERE x.annotator_id = ra.id AND x.skill_id = s.id AND x.deleted_at IS NULL
);

WITH ranked_annotators AS (
  SELECT
    a.id,
    a.org_id,
    t.name AS team_name,
    ROW_NUMBER() OVER (PARTITION BY t.id ORDER BY a.full_name, a.id) AS rn
  FROM annotators a
  JOIN teams t ON t.id = a.team_id
  JOIN projects p ON p.id = t.project_id
  JOIN organisations o ON o.id = p.org_id
  WHERE o.name = 'Northwind Analytics'
    AND p.name = 'Northwind Content Shield 4'
    AND a.deleted_at IS NULL
)
INSERT INTO employee_certifications (org_id, annotator_id, certification_id, issued_at, expires_at, status)
SELECT ra.org_id, ra.id, c.id, v.issued, v.expires, v.status
FROM ranked_annotators ra
JOIN certifications c ON c.org_id = ra.org_id AND c.deleted_at IS NULL
JOIN (VALUES
    ('Northwind Content Shield 4 Team 1', 1, 'Vision QA Specialist', DATE '2026-02-01', DATE '2027-02-01', 'active'),
    ('Northwind Content Shield 4 Team 2', 1, 'SME Calibration Certificate', DATE '2025-06-01', DATE '2027-06-01', 'active'),
    ('Northwind Content Shield 4 Team 3', 2, 'Content Safety Level 2', DATE '2024-01-01', DATE '2025-01-01', 'expired'),
    ('Northwind Content Shield 4 Team 3', 3, 'Content Safety Level 2', NULL::date, NULL::date, 'pending_review')
  ) AS v(team_name, rn, cert_name, issued, expires, status)
    ON v.team_name = ra.team_name AND v.rn = ra.rn AND v.cert_name = c.name
WHERE NOT EXISTS (
  SELECT 1 FROM employee_certifications e
  WHERE e.annotator_id = ra.id AND e.certification_id = c.id AND e.deleted_at IS NULL
);

WITH ranked_annotators AS (
  SELECT
    a.id,
    a.org_id,
    t.name AS team_name,
    ROW_NUMBER() OVER (PARTITION BY t.id ORDER BY a.full_name, a.id) AS rn
  FROM annotators a
  JOIN teams t ON t.id = a.team_id
  JOIN projects p ON p.id = t.project_id
  JOIN organisations o ON o.id = p.org_id
  WHERE o.name = 'Northwind Analytics'
    AND p.name = 'Northwind Content Shield 4'
    AND a.deleted_at IS NULL
)
INSERT INTO training_records (org_id, annotator_id, training_program_id, status, started_at, completed_at, score_pct)
SELECT ra.org_id, ra.id, tp.id, v.status, v.started, v.completed, v.score
FROM ranked_annotators ra
JOIN training_programs tp ON tp.org_id = ra.org_id AND tp.deleted_at IS NULL
JOIN (VALUES
    ('Northwind Content Shield 4 Team 1', 1, 'Advanced Vision QA', 'completed', TIMESTAMPTZ '2026-02-10 09:00:00+00', TIMESTAMPTZ '2026-03-01 17:00:00+00', 95.00),
    ('Northwind Content Shield 4 Team 1', 2, 'Advanced Vision QA', 'in_progress', TIMESTAMPTZ '2026-05-01 09:00:00+00', NULL::timestamptz, NULL::numeric),
    ('Northwind Content Shield 4 Team 2', 3, 'Content Safety Foundations', 'completed', TIMESTAMPTZ '2026-03-01 09:00:00+00', TIMESTAMPTZ '2026-03-20 17:00:00+00', 88.00),
    ('Northwind Content Shield 4 Team 2', 5, 'Content Safety Foundations', 'expired', TIMESTAMPTZ '2025-01-10 09:00:00+00', TIMESTAMPTZ '2025-02-01 17:00:00+00', 80.00),
    ('Northwind Content Shield 4 Team 3', 2, 'Safety Policy Deep Dive', 'failed', TIMESTAMPTZ '2026-04-01 09:00:00+00', TIMESTAMPTZ '2026-04-15 17:00:00+00', 48.00),
    ('Northwind Content Shield 4 Team 3', 4, 'SME Calibration Workshop', 'in_progress', TIMESTAMPTZ '2026-06-01 09:00:00+00', NULL::timestamptz, NULL::numeric)
  ) AS v(team_name, rn, program_name, status, started, completed, score)
    ON v.team_name = ra.team_name AND v.rn = ra.rn AND v.program_name = tp.name
WHERE NOT EXISTS (
  SELECT 1 FROM training_records r
  WHERE r.annotator_id = ra.id AND r.training_program_id = tp.id AND r.deleted_at IS NULL
);

INSERT INTO utilization_snapshots (org_id, project_id, team_id, annotator_id, snapshot_date, allocated_hours, available_hours, utilization_pct, notes)
SELECT t.org_id, p.id, t.id, NULL, v.snap_date, v.allocated, v.available, v.util, v.notes
FROM teams t
JOIN projects p ON p.id = t.project_id
JOIN organisations o ON o.id = p.org_id
JOIN (VALUES
    ('Northwind Content Shield 4 Team 1', DATE '2026-06-08', 78.00, 100.00, 78.00, 'Ramping load ahead of policy launch.'),
    ('Northwind Content Shield 4 Team 1', DATE '2026-06-15', 92.00, 100.00, 92.00, 'Sustained high load before launch.'),
    ('Northwind Content Shield 4 Team 1', DATE '2026-06-22', 108.00, 100.00, 108.00, 'Overtime to clear project backlog.'),
    ('Northwind Content Shield 4 Team 2', DATE '2026-06-08', 71.00, 100.00, 71.00, 'Healthy steady-state utilization.'),
    ('Northwind Content Shield 4 Team 2', DATE '2026-06-15', 74.00, 100.00, 74.00, 'Healthy steady-state utilization.'),
    ('Northwind Content Shield 4 Team 2', DATE '2026-06-22', 72.00, 100.00, 72.00, 'Healthy steady-state utilization.'),
    ('Northwind Content Shield 4 Team 3', DATE '2026-06-08', 52.00, 100.00, 52.00, 'Underutilized; capacity available for reallocation.'),
    ('Northwind Content Shield 4 Team 3', DATE '2026-06-15', 47.00, 100.00, 47.00, 'Underutilized; capacity available for reallocation.'),
    ('Northwind Content Shield 4 Team 3', DATE '2026-06-22', 48.00, 100.00, 48.00, 'Underutilized; capacity available for reallocation.')
  ) AS v(team_name, snap_date, allocated, available, util, notes) ON v.team_name = t.name
WHERE o.name = 'Northwind Analytics'
  AND p.name = 'Northwind Content Shield 4'
  AND t.deleted_at IS NULL
  AND NOT EXISTS (
    SELECT 1 FROM utilization_snapshots u
    WHERE u.team_id = t.id AND u.snapshot_date = v.snap_date AND u.annotator_id IS NULL AND u.deleted_at IS NULL
  );

COMMIT;
