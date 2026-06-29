-- Project Governance Agent — Phase 1 demo seed data.
--
-- Attaches to 'Northwind Analytics' org (from supabase/seed.sql).
-- Idempotent: guarded with NOT EXISTS on stable titles/names.
--
-- Apply:
--   cd backend
--   .\.venv\Scripts\python.exe ..\supabase\apply_seed.py --file ..\supabase\seed_governance.sql

BEGIN;

-- ---------------------------------------------------------------------------
-- 1. Governance demo projects (3)
-- ---------------------------------------------------------------------------
INSERT INTO projects (org_id, name, description, vertical, status, start_date, target_end_date, daily_target_units)
SELECT o.id, v.name, v.description, v.vertical, 'active'::project_status, DATE '2026-01-10', DATE '2026-12-15', 900
FROM organisations o
JOIN (VALUES
  ('Helios Docs', 'Document intelligence program for Northwind.', 'document_ai'),
  ('Nimbus NLP', 'NLP model delivery and evaluation.', 'nlp'),
  ('Vertex Finance', 'Finance domain annotation engagement.', 'finance')
) AS v(name, description, vertical) ON TRUE
WHERE o.name = 'Northwind Analytics'
  AND o.deleted_at IS NULL
  AND NOT EXISTS (
    SELECT 1 FROM projects p
    WHERE p.org_id = o.id AND p.name = v.name AND p.deleted_at IS NULL
  );

-- ---------------------------------------------------------------------------
-- 2. Scope states (3)
-- ---------------------------------------------------------------------------
INSERT INTO project_scope_states (org_id, project_id, scope_status, version_label, notes)
SELECT p.org_id, p.id, v.scope_status::governance_scope_status, v.version_label, v.notes
FROM projects p
JOIN organisations o ON o.id = p.org_id
JOIN (VALUES
  ('Helios Docs', 'pending_revision', 'Pending v2', 'Schema v2 revision awaiting client approval.'),
  ('Nimbus NLP', 'locked', 'v1', 'Scope locked for Q2 delivery.'),
  ('Vertex Finance', 'approved', 'v1', 'Baseline scope approved.')
) AS v(project_name, scope_status, version_label, notes) ON p.name = v.project_name
WHERE o.name = 'Northwind Analytics'
  AND p.deleted_at IS NULL
  AND NOT EXISTS (
    SELECT 1 FROM project_scope_states s
    WHERE s.project_id = p.id AND s.deleted_at IS NULL
  );

-- ---------------------------------------------------------------------------
-- 3. Dependencies (5)
-- ---------------------------------------------------------------------------
INSERT INTO project_dependencies (
  org_id, project_id, title, description, dependency_type, due_date, status
)
SELECT p.org_id, p.id, v.title, v.description, v.dep_type::governance_dependency_type,
       v.due_date::date, v.status::governance_dependency_status
FROM projects p
JOIN organisations o ON o.id = p.org_id
JOIN (VALUES
  ('Helios Docs', 'Client schema v2 approval', 'Client must approve updated schema before indexing.', 'client_action', '2026-06-18', 'blocking'),
  ('Helios Docs', 'Legal review sign-off', 'Internal legal review of data handling addendum.', 'internal', '2026-06-28', 'open'),
  ('Nimbus NLP', 'GPU quota uplift', 'Cloud provider quota increase for training runs.', 'external', '2026-06-20', 'blocking'),
  ('Nimbus NLP', 'Annotation guideline refresh', 'Update guidelines for new toxicity labels.', 'internal', '2026-07-05', 'open'),
  ('Vertex Finance', 'Client UAT window', 'Client UAT calendar slot for finance workflows.', 'client_action', '2026-07-12', 'open')
) AS v(project_name, title, description, dep_type, due_date, status) ON p.name = v.project_name
WHERE o.name = 'Northwind Analytics'
  AND p.deleted_at IS NULL
  AND NOT EXISTS (
    SELECT 1 FROM project_dependencies d
    WHERE d.project_id = p.id AND d.title = v.title AND d.deleted_at IS NULL
  );

-- ---------------------------------------------------------------------------
-- 4. Governance actions (4)
-- ---------------------------------------------------------------------------
INSERT INTO governance_actions (
  org_id, project_id, title, description, due_date, status
)
SELECT p.org_id, p.id, v.title, v.description, v.due_date::date, v.status::governance_action_status
FROM projects p
JOIN organisations o ON o.id = p.org_id
JOIN (VALUES
  ('Helios Docs', 'Approve Helios schema v2', 'DM review of schema delta before client send.', '2026-06-24', 'open'),
  ('Helios Docs', 'Close W23 action items', 'Close four open items from last governance call.', '2026-06-26', 'in_progress'),
  ('Nimbus NLP', 'Review capacity proposal', 'Review annotator ramp plan for July.', '2026-06-25', 'open'),
  ('Vertex Finance', 'Sign-off calibration plan', 'QA lead sign-off on calibration approach.', '2026-06-27', 'open')
) AS v(project_name, title, description, due_date, status) ON p.name = v.project_name
WHERE o.name = 'Northwind Analytics'
  AND p.deleted_at IS NULL
  AND NOT EXISTS (
    SELECT 1 FROM governance_actions a
    WHERE a.project_id = p.id AND a.title = v.title AND a.deleted_at IS NULL
  );

-- ---------------------------------------------------------------------------
-- 5. Escalations (3)
-- ---------------------------------------------------------------------------
INSERT INTO governance_escalations (
  org_id, project_id, title, description, severity, status
)
SELECT p.org_id, p.id, v.title, v.description, v.severity::governance_escalation_severity,
       v.status::governance_escalation_status
FROM projects p
JOIN organisations o ON o.id = p.org_id
JOIN (VALUES
  ('Helios Docs', 'Schema approval delay', 'Client schema v2 approval is blocking milestone M3.', 'high', 'open'),
  ('Nimbus NLP', 'GPU quota escalation', 'External provider delay threatens training schedule.', 'critical', 'in_progress'),
  ('Vertex Finance', 'UAT scheduling risk', 'Client UAT window may slip into August.', 'medium', 'open')
) AS v(project_name, title, description, severity, status) ON p.name = v.project_name
WHERE o.name = 'Northwind Analytics'
  AND p.deleted_at IS NULL
  AND NOT EXISTS (
    SELECT 1 FROM governance_escalations e
    WHERE e.project_id = p.id AND e.title = v.title AND e.deleted_at IS NULL
  );

-- ---------------------------------------------------------------------------
-- 6. Draft weekly summary (1)
-- ---------------------------------------------------------------------------
INSERT INTO governance_weekly_summaries (org_id, summary_week, summary_text, status, generated_by_ai)
SELECT o.id, DATE '2026-06-16',
       'Three governance items pending; Helios schema is the critical-path blocker. Nimbus capacity proposal ready for review. Two escalations require client input on Friday''s call.',
       'draft'::governance_summary_status,
       FALSE
FROM organisations o
WHERE o.name = 'Northwind Analytics'
  AND o.deleted_at IS NULL
  AND NOT EXISTS (
    SELECT 1 FROM governance_weekly_summaries w
    WHERE w.org_id = o.id AND w.summary_week = DATE '2026-06-16'
  );

COMMIT;
