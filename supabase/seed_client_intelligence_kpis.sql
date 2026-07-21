-- Client Intelligence KPI demo seed (additive only).
--
-- Does NOT modify existing rows. Inserts only the records required for:
--   - Reports Drafted vs Approved  (client_communications drafted_by_agent = client_interaction_agent)
--   - Avg Query Response           (agent_queries agent_name = client_interaction_agent + latency_ms)
--   - Avg CSAT                     (client_csat_scores on the 1–5 scale)
--
-- Idempotent: guarded with NOT EXISTS on stable subjects / month keys / query text.
--
-- Apply:
--   cd backend
--   .\.venv\Scripts\python.exe ..\supabase\apply_seed.py --file ..\supabase\seed_client_intelligence_kpis.sql

BEGIN;

-- ---------------------------------------------------------------------------
-- 1. CSAT scores (1–5) for every project that has none yet
-- ---------------------------------------------------------------------------
INSERT INTO client_csat_scores (
  project_id,
  org_id,
  submitted_by,
  score,
  reporting_period_month,
  comment,
  created_at
)
SELECT
  p.id,
  p.org_id,
  submitter.id,
  v.score,
  v.reporting_period_month,
  v.comment,
  v.reporting_period_month::timestamptz
FROM projects p
CROSS JOIN (
  VALUES
    (DATE '2026-05-01', 4.5::numeric, 'Seeded Client Intelligence CSAT response.'),
    (DATE '2026-06-01', 4.0::numeric, 'Seeded Client Intelligence CSAT response.'),
    (DATE '2026-07-01', 5.0::numeric, NULL)
) AS v(reporting_period_month, score, comment)
JOIN LATERAL (
  SELECT COALESCE(
    (
      SELECT u.id
      FROM users u
      WHERE u.org_id = p.org_id
        AND u.role::text = 'client'
      ORDER BY u.created_at NULLS LAST
      LIMIT 1
    ),
    (
      SELECT u.id
      FROM users u
      WHERE u.role::text IN ('delivery_manager', 'super_admin')
      ORDER BY u.created_at NULLS LAST
      LIMIT 1
    )
  ) AS id
) submitter ON submitter.id IS NOT NULL
WHERE p.deleted_at IS NULL
  AND NOT EXISTS (
  SELECT 1
  FROM client_csat_scores s
  WHERE s.project_id = p.id
    AND s.submitted_by = submitter.id
    AND s.reporting_period_month = v.reporting_period_month
);

-- ---------------------------------------------------------------------------
-- 2. Client Interaction Agent communications (reports KPI source)
--    Keep existing delivery-agent / ops-summary-agent rows untouched.
-- ---------------------------------------------------------------------------
INSERT INTO client_communications (
  project_id,
  org_id,
  comm_type,
  subject,
  body_draft,
  body_approved,
  status,
  drafted_by_agent,
  reviewed_by,
  reviewed_at,
  approved_by,
  approved_at,
  sent_at,
  created_at,
  updated_at
)
SELECT
  p.id,
  p.org_id,
  v.comm_type::communication_type,
  v.subject_prefix || ' — ' || p.name,
  'Evidence-backed Client Intelligence draft for ' || p.name || '.',
  CASE
    WHEN v.status IN ('approved', 'sent') THEN 'Approved Client Intelligence summary for ' || p.name || '.'
    ELSE NULL
  END,
  v.status::communication_status,
  'client_interaction_agent',
  reviewer.id,
  CASE WHEN v.status IN ('in_review', 'approved', 'sent') THEN now() - interval '2 days' ELSE NULL END,
  CASE WHEN v.status IN ('approved', 'sent') THEN reviewer.id ELSE NULL END,
  CASE WHEN v.status IN ('approved', 'sent') THEN now() - interval '1 day' ELSE NULL END,
  CASE WHEN v.status = 'sent' THEN now() - interval '12 hours' ELSE NULL END,
  now() - (v.age_days || ' days')::interval,
  now() - (v.age_days || ' days')::interval
FROM projects p
JOIN LATERAL (
  SELECT u.id
  FROM users u
  WHERE u.role::text IN ('delivery_manager', 'super_admin')
  ORDER BY u.created_at NULLS LAST
  LIMIT 1
) reviewer ON reviewer.id IS NOT NULL
CROSS JOIN (
  VALUES
    ('weekly_summary', 'CI Weekly Status', 'draft', 5),
    ('weekly_summary', 'CI Mid-month Quality Note', 'in_review', 4),
    ('executive_summary', 'CI Executive Summary', 'approved', 3),
    ('weekly_summary', 'CI Sent Weekly Update', 'sent', 2)
) AS v(comm_type, subject_prefix, status, age_days)
WHERE p.deleted_at IS NULL
  AND p.status IN ('active'::project_status, 'ramping'::project_status)
  AND NOT EXISTS (
    SELECT 1
    FROM client_communications c
    WHERE c.project_id = p.id
      AND c.drafted_by_agent = 'client_interaction_agent'
      AND c.subject = v.subject_prefix || ' — ' || p.name
  );

-- ---------------------------------------------------------------------------
-- 3. Client Interaction Agent queries (avg query response KPI source)
-- ---------------------------------------------------------------------------
INSERT INTO agent_queries (
  user_id,
  org_id,
  project_id,
  agent_name,
  query_text,
  answer_text,
  model_used,
  latency_ms,
  created_at
)
SELECT
  asker.id,
  p.org_id,
  p.id,
  'client_interaction_agent',
  v.query_text,
  'Seeded Client Intelligence answer grounded in governed project evidence for ' || p.name || '.',
  'claude-sonnet-4-6',
  v.latency_ms,
  now() - (v.age_hours || ' hours')::interval
FROM projects p
JOIN LATERAL (
  SELECT u.id
  FROM users u
  WHERE u.role::text IN ('delivery_manager', 'super_admin')
  ORDER BY u.created_at NULLS LAST
  LIMIT 1
) asker ON asker.id IS NOT NULL
CROSS JOIN (
  VALUES
    ('What is the current delivery confidence for this project?', 3200, 30),
    ('Summarize open risks and mitigations for this project.', 5100, 20),
    ('When is the next milestone forecast to complete?', 2800, 10)
) AS v(query_text, latency_ms, age_hours)
WHERE p.deleted_at IS NULL
  AND p.status IN ('active'::project_status, 'ramping'::project_status)
  AND NOT EXISTS (
    SELECT 1
    FROM agent_queries q
    WHERE q.project_id = p.id
      AND q.agent_name = 'client_interaction_agent'
      AND q.query_text = v.query_text
  );

COMMIT;
