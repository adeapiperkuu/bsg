# Database Schema

> **Authoritative data model for autonomous AI coding agents.**
> Backend agents must generate SQLAlchemy models and Supabase CLI migrations directly from this document. Every table, column, type, constraint, and RLS note is binding. Items marked **** require human confirmation before the migration is committed. Do not add tables, columns, or relationships not listed here without flagging them first.
>
> **Schema syntax:** Raw PostgreSQL DDL. SQLAlchemy async models live in `backend/app/db/` and must mirror this document exactly. Supabase CLI migration files live in `supabase/migrations/`.

---

## 1. Entity Overview

The Operations Tower data model is built around **organisations** (clients, each fully isolated by RLS) and **delivery projects** that belong to those organisations. Every project has **milestones** with planned vs. actual dates and **daily throughput snapshots** that feed the Delivery Performance Agent. A parallel quality layer captures weekly **quality snapshots** per project/team pair, including gold-set accuracy, inter-annotator agreement, rework rate, and structured **error taxonomy entries** that feed the Quality Intelligence Agent. **Teams** and **annotators** represent the delivery workforce. The **Client Interaction Agent** generates AI-drafted **client communications** that must be reviewed and approved by a Delivery Manager before sending; a separate **agent query log** records every natural-language question and its evidence-backed answer for the full audit trail. **Risk alerts** capture threshold-crossing events with contributing causes. **Users** authenticate via Supabase Auth and carry a role claim; their access to all client-scoped tables is enforced by RLS policies that join on `org_id`. A **metric configuration** table lets Super Admin control which metrics are surfaced on client-facing dashboards without a code change.

**Tables:**

- `organisations` — a BSG client (tenant); the root of all tenant isolation
- `users` — platform users, linked to Supabase Auth `auth.users`; carries role and org membership
- `projects` — a delivery engagement (scoped to one organisation)
- `milestones` — planned delivery checkpoints within a project
- `throughput_snapshots` — one row per project per day: units completed, forecast, rolling metrics
- `teams` — a named delivery team (by site and domain) within a project
- `annotators` — individual workforce members assigned to teams 
- `quality_snapshots` — one row per project/team per ISO week: gold-set accuracy, IAA, rework rate
- `quality_error_entries` — individual error taxonomy line items within a quality snapshot
- `risk_alerts` — threshold-crossing delivery or quality risk events, per project
- `bottlenecks` — auto-detected workflow bottlenecks flagged by the Delivery Agent 
- `client_communications` — AI-drafted client status summaries awaiting or having received DM approval
- `communication_evidence_links` — maps a client communication to the source data rows it cites
- `agent_queries` — log of every natural-language query submitted to any agent
- `agent_query_evidence_links` — maps an agent query answer to its cited source rows
- `client_csat_scores` — rolling client satisfaction scores 
- `metric_configurations` — Super Admin–managed list of metrics shown on client-facing dashboards
- `delivery_confidence_scores` — computed confidence score per milestone at a point in time 
- `notifications` — alert delivery records (email/in-app) sent to users 

---

## 2. Entity-Relationship Summary

- One **organisation** has many **users**, many **projects**.
- One **project** belongs to one **organisation**.
- One **project** has many **milestones**, many **throughput_snapshots**, many **teams**, many **quality_snapshots**, many **risk_alerts**, many **bottlenecks**, many **client_communications**, many **delivery_confidence_scores**.
- One **milestone** belongs to one **project**; has many **delivery_confidence_scores**.
- One **throughput_snapshot** belongs to one **project** (one row per project per calendar day).
- One **team** belongs to one **project**; has many **annotators**, many **quality_snapshots**.
- One **annotator** belongs to one **team** (current assignment); belongs to one **organisation**. 
- One **quality_snapshot** belongs to one **project** and one **team** (the combination is unique per ISO week); has many **quality_error_entries**.
- One **quality_error_entry** belongs to one **quality_snapshot**.
- One **risk_alert** belongs to one **project**; optionally references one **milestone**.
- One **bottleneck** belongs to one **project**; optionally references one **team**. 
- One **client_communication** belongs to one **project**; has many **communication_evidence_links**; is approved by one **user** (Delivery Manager).
- One **communication_evidence_link** belongs to one **client_communication**; references one source row by table name + row id.
- One **agent_query** belongs to one **user** and one **project** (optionally); has many **agent_query_evidence_links**.
- One **agent_query_evidence_link** belongs to one **agent_query**; references one source row by table name + row id.
- One **client_csat_score** belongs to one **project** and one **user** (client submitter). 
- One **metric_configuration** belongs to no specific organisation (it is platform-wide); managed only by Super Admin.
- One **delivery_confidence_score** belongs to one **project** and one **milestone** (point-in-time snapshot). 
- One **notification** belongs to one **user** and optionally one **risk_alert** or one **client_communication**. 

---

## 3. Table Definitions

All tables use the standard field convention described in Section 5. RLS policy notes are included per table — agents must implement the named policy when writing migrations.

---

### `organisations`

```sql
CREATE TABLE organisations (
  id            UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
  name          TEXT        NOT NULL,
  slug          TEXT        NOT NULL,                  -- URL-safe identifier, e.g. "acme-lifesci"
  vertical      TEXT        NOT NULL,                  -- 'life_sciences' | 'finance' | 'logistics' | 'other'
  region        TEXT        NOT NULL,                  -- e.g. 'EU', 'US' — for data residency tracking
  is_active     BOOLEAN     NOT NULL DEFAULT TRUE,
  created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
  deleted_at    TIMESTAMPTZ                            -- soft delete

  CONSTRAINT organisations_slug_key UNIQUE (slug)
);

-- RLS: Super Admin can read/write all rows.
--      No other role reads this table directly; access is via joined queries.
ALTER TABLE organisations ENABLE ROW LEVEL SECURITY;
```

---

### `users`

```sql
CREATE TABLE users (
  id            UUID        PRIMARY KEY,               -- MUST equal auth.users.id (Supabase Auth)
  org_id        UUID        NOT NULL REFERENCES organisations (id) ON DELETE RESTRICT,
  email         TEXT        NOT NULL,
  full_name     TEXT,
  role          app_role    NOT NULL,                  -- enum: see Section 4
  is_active     BOOLEAN     NOT NULL DEFAULT TRUE,
  created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
  deleted_at    TIMESTAMPTZ                            -- soft delete

  CONSTRAINT users_email_key UNIQUE (email)
);

CREATE INDEX users_org_id_idx ON users (org_id);
CREATE INDEX users_role_idx ON users (role);

-- RLS:
--   'client'           → can only SELECT their own row (id = auth.uid())
--   'delivery_manager' → can SELECT all users within their own org_id
--   'bsg_leadership'   → can SELECT all users across all orgs (read-only)
--   'super_admin'      → full access
ALTER TABLE users ENABLE ROW LEVEL SECURITY;
```

---

### `projects`

```sql
CREATE TABLE projects (
  id                UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
  org_id            UUID        NOT NULL REFERENCES organisations (id) ON DELETE RESTRICT,
  name              TEXT        NOT NULL,
  description       TEXT,
  vertical          TEXT        NOT NULL,              -- mirrors organisations.vertical; stored for query convenience
  status            project_status NOT NULL DEFAULT 'active',  -- enum: see Section 4
  start_date        DATE        NOT NULL,
  target_end_date   DATE        NOT NULL,
  actual_end_date   DATE,
  daily_target_units INT,                              -- planned throughput per day (units)
  created_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
  deleted_at        TIMESTAMPTZ                        -- soft delete
);

CREATE INDEX projects_org_id_idx ON projects (org_id);
CREATE INDEX projects_status_idx ON projects (status);

-- RLS:
--   'client'           → SELECT only rows where org_id = their org_id
--   'delivery_manager' → SELECT/INSERT/UPDATE only rows where org_id = their org_id
--   'bsg_leadership'   → SELECT all rows (read-only)
--   'super_admin'      → full access
ALTER TABLE projects ENABLE ROW LEVEL SECURITY;
```

---

### `milestones`

```sql
CREATE TABLE milestones (
  id                UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
  project_id        UUID        NOT NULL REFERENCES projects (id) ON DELETE CASCADE,
  org_id            UUID        NOT NULL REFERENCES organisations (id) ON DELETE RESTRICT,  -- denormalized for RLS
  name              TEXT        NOT NULL,
  description       TEXT,
  planned_date      DATE        NOT NULL,
  actual_date       DATE,                              -- NULL until completed
  status            milestone_status NOT NULL DEFAULT 'pending',  -- enum: see Section 4
  created_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
  deleted_at        TIMESTAMPTZ
);

CREATE INDEX milestones_project_id_idx ON milestones (project_id);
CREATE INDEX milestones_org_id_idx ON milestones (org_id);
CREATE INDEX milestones_planned_date_idx ON milestones (planned_date);

-- RLS: mirror projects table policies, using org_id column.
ALTER TABLE milestones ENABLE ROW LEVEL SECURITY;
```

---

### `throughput_snapshots`

```sql
CREATE TABLE throughput_snapshots (
  id                  UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
  project_id          UUID        NOT NULL REFERENCES projects (id) ON DELETE CASCADE,
  org_id              UUID        NOT NULL REFERENCES organisations (id) ON DELETE RESTRICT,  -- denormalized for RLS
  snapshot_date       DATE        NOT NULL,
  units_completed     INT         NOT NULL CHECK (units_completed >= 0),
  units_forecast      INT                  CHECK (units_forecast >= 0),
  rolling_7day_units  INT                  CHECK (rolling_7day_units >= 0),  -- computed & stored by backend service
  created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at          TIMESTAMPTZ NOT NULL DEFAULT now()
  -- No soft delete: snapshots are immutable historical records.

  CONSTRAINT throughput_snapshots_project_date_key UNIQUE (project_id, snapshot_date)
);

CREATE INDEX throughput_snapshots_project_id_date_idx ON throughput_snapshots (project_id, snapshot_date DESC);
CREATE INDEX throughput_snapshots_org_id_idx ON throughput_snapshots (org_id);

-- RLS: 'client' → SELECT where org_id = their org_id (read-only).
--      'delivery_manager' → SELECT/INSERT/UPDATE where org_id = their org_id.
--      'bsg_leadership' → SELECT all (read-only).
--      'super_admin' → full access.
ALTER TABLE throughput_snapshots ENABLE ROW LEVEL SECURITY;
```

---

### `teams`

```sql
CREATE TABLE teams (
  id            UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
  project_id    UUID        NOT NULL REFERENCES projects (id) ON DELETE CASCADE,
  org_id        UUID        NOT NULL REFERENCES organisations (id) ON DELETE RESTRICT,  -- denormalized for RLS
  name          TEXT        NOT NULL,                  -- e.g. "Radiology CV", "Clinical NLP"
  site          delivery_site NOT NULL,                -- enum: 'india' | 'kosovo'
  domain        TEXT        NOT NULL,                  -- e.g. "radiology", "pathology", "clinical_nlp"
  is_active     BOOLEAN     NOT NULL DEFAULT TRUE,
  created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
  deleted_at    TIMESTAMPTZ
);

CREATE INDEX teams_project_id_idx ON teams (project_id);
CREATE INDEX teams_org_id_idx ON teams (org_id);

-- RLS: 'client' → SELECT where org_id = their org_id.
--      'delivery_manager' → SELECT/INSERT/UPDATE where org_id = their org_id.
--      'bsg_leadership' → SELECT all.
--      'super_admin' → full access.
ALTER TABLE teams ENABLE ROW LEVEL SECURITY;
```

---

### `annotators` 

```sql
-- : Source describes "72 experts deployed" and utilisation % by site,
--   implying individual workforce records. Confirm whether annotators are tracked
--   individually in this system or only aggregated at team level.

CREATE TABLE annotators (
  id              UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
  org_id          UUID        NOT NULL REFERENCES organisations (id) ON DELETE RESTRICT,  -- for RLS
  team_id         UUID        NOT NULL REFERENCES teams (id) ON DELETE RESTRICT,          -- current assignment
  full_name       TEXT        NOT NULL,
  site            delivery_site NOT NULL,              -- 'india' | 'kosovo'
  is_sme_certified BOOLEAN    NOT NULL DEFAULT FALSE,  -- domain reviewer certification
  is_active       BOOLEAN     NOT NULL DEFAULT TRUE,
  created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
  deleted_at      TIMESTAMPTZ
);

CREATE INDEX annotators_team_id_idx ON annotators (team_id);
CREATE INDEX annotators_org_id_idx ON annotators (org_id);

-- RLS: 'client' → no access (internal workforce data only).
--      'delivery_manager' → SELECT/INSERT/UPDATE where org_id = their org_id.
--      'bsg_leadership' → SELECT all.
--      'super_admin' → full access.
ALTER TABLE annotators ENABLE ROW LEVEL SECURITY;
```

---

### `quality_snapshots`

```sql
CREATE TABLE quality_snapshots (
  id                        UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
  project_id                UUID        NOT NULL REFERENCES projects (id) ON DELETE CASCADE,
  team_id                   UUID        NOT NULL REFERENCES teams (id) ON DELETE RESTRICT,
  org_id                    UUID        NOT NULL REFERENCES organisations (id) ON DELETE RESTRICT,  -- denormalized for RLS
  iso_week                  INT         NOT NULL CHECK (iso_week BETWEEN 1 AND 53),
  iso_year                  INT         NOT NULL CHECK (iso_year >= 2024),
  gold_set_accuracy_pct     NUMERIC(5,2)         CHECK (gold_set_accuracy_pct BETWEEN 0 AND 100),
  iaa_krippendorff_alpha    NUMERIC(4,3)         CHECK (iaa_krippendorff_alpha BETWEEN 0 AND 1),
  rework_rate_pct           NUMERIC(5,2)         CHECK (rework_rate_pct BETWEEN 0 AND 100),
  has_drift_alert           BOOLEAN     NOT NULL DEFAULT FALSE,
  drift_alert_detail        TEXT,                                -- narrative if has_drift_alert = TRUE
  created_at                TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at                TIMESTAMPTZ NOT NULL DEFAULT now()
  -- No soft delete: quality snapshots are immutable historical records.

  CONSTRAINT quality_snapshots_project_team_week_key
    UNIQUE (project_id, team_id, iso_year, iso_week)
);

CREATE INDEX quality_snapshots_project_id_idx ON quality_snapshots (project_id);
CREATE INDEX quality_snapshots_org_id_idx ON quality_snapshots (org_id);
CREATE INDEX quality_snapshots_week_idx ON quality_snapshots (iso_year, iso_week);

-- RLS: 'client' → SELECT where org_id = their org_id (read-only).
--      'delivery_manager' → SELECT/INSERT/UPDATE where org_id = their org_id.
--      'bsg_leadership' → SELECT all.
--      'super_admin' → full access.
ALTER TABLE quality_snapshots ENABLE ROW LEVEL SECURITY;
```

---

### `quality_error_entries`

```sql
CREATE TABLE quality_error_entries (
  id                    UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
  quality_snapshot_id   UUID        NOT NULL REFERENCES quality_snapshots (id) ON DELETE CASCADE,
  org_id                UUID        NOT NULL REFERENCES organisations (id) ON DELETE RESTRICT,  -- denormalized for RLS
  error_category        TEXT        NOT NULL,          -- e.g. 'boundary_precision', 'class_confusion', 'missed_small_objects'
  share_pct             NUMERIC(5,2) NOT NULL CHECK (share_pct BETWEEN 0 AND 100),
  recommended_action    TEXT,                          -- e.g. 'targeted reviewer calibration', 'SOP update'
  created_at            TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at            TIMESTAMPTZ NOT NULL DEFAULT now()
  -- No soft delete: taxonomy entries are immutable per snapshot.
);

CREATE INDEX quality_error_entries_snapshot_id_idx ON quality_error_entries (quality_snapshot_id);
CREATE INDEX quality_error_entries_org_id_idx ON quality_error_entries (org_id);

-- RLS: 'client' → SELECT where org_id = their org_id (read-only; error taxonomy surfaced in client view).
--      'delivery_manager' → SELECT/INSERT/UPDATE where org_id = their org_id.
--      'bsg_leadership' → SELECT all.
--      'super_admin' → full access.
ALTER TABLE quality_error_entries ENABLE ROW LEVEL SECURITY;
```

---

### `risk_alerts`

```sql
CREATE TABLE risk_alerts (
  id                    UUID            PRIMARY KEY DEFAULT gen_random_uuid(),
  project_id            UUID            NOT NULL REFERENCES projects (id) ON DELETE CASCADE,
  org_id                UUID            NOT NULL REFERENCES organisations (id) ON DELETE RESTRICT,  -- denormalized for RLS
  milestone_id          UUID            REFERENCES milestones (id) ON DELETE SET NULL,  -- optional
  alert_type            alert_type      NOT NULL,      -- enum: see Section 4
  risk_tier             risk_tier       NOT NULL,      -- enum: 'low' | 'medium' | 'high' | 'critical'
  title                 TEXT            NOT NULL,
  detail                TEXT            NOT NULL,      -- AI-generated narrative; must cite evidence
  slippage_probability  NUMERIC(4,3)    CHECK (slippage_probability BETWEEN 0 AND 1),
  contributing_causes   JSONB,                         -- e.g. {"absenteeism": 0.60, "rework": 0.25, "review_turnaround": 0.15}
  status                alert_status    NOT NULL DEFAULT 'open',  -- enum: see Section 4
  resolved_at           TIMESTAMPTZ,
  resolved_by           UUID            REFERENCES users (id) ON DELETE SET NULL,
  created_at            TIMESTAMPTZ     NOT NULL DEFAULT now(),
  updated_at            TIMESTAMPTZ     NOT NULL DEFAULT now(),
  deleted_at            TIMESTAMPTZ
);

CREATE INDEX risk_alerts_project_id_idx ON risk_alerts (project_id);
CREATE INDEX risk_alerts_org_id_idx ON risk_alerts (org_id);
CREATE INDEX risk_alerts_status_idx ON risk_alerts (status);
CREATE INDEX risk_alerts_risk_tier_idx ON risk_alerts (risk_tier);

-- RLS: 'client' → SELECT where org_id = their org_id (read-only; clients see their own escalations).
--      'delivery_manager' → SELECT/INSERT/UPDATE/soft-delete where org_id = their org_id.
--      'bsg_leadership' → SELECT all.
--      'super_admin' → full access.
ALTER TABLE risk_alerts ENABLE ROW LEVEL SECURITY;
```

---

### `bottlenecks` 

```sql
-- : Source (PDF p.7) shows "2 Bottlenecks flagged / auto-detected"
--   with named examples (e.g. "Retinal OCT tooling delay"). These are distinct
--   from risk_alerts: they are workflow-specific blockers, not risk probability scores.
--   Confirm whether bottlenecks are a standalone table or should be merged into risk_alerts.

CREATE TABLE bottlenecks (
  id            UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
  project_id    UUID        NOT NULL REFERENCES projects (id) ON DELETE CASCADE,
  org_id        UUID        NOT NULL REFERENCES organisations (id) ON DELETE RESTRICT,  -- denormalized for RLS
  team_id       UUID        REFERENCES teams (id) ON DELETE SET NULL,
  description   TEXT        NOT NULL,
  status        alert_status NOT NULL DEFAULT 'open',  -- reuse alert_status enum
  detected_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
  resolved_at   TIMESTAMPTZ,
  resolved_by   UUID        REFERENCES users (id) ON DELETE SET NULL,
  created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
  deleted_at    TIMESTAMPTZ
);

CREATE INDEX bottlenecks_project_id_idx ON bottlenecks (project_id);
CREATE INDEX bottlenecks_org_id_idx ON bottlenecks (org_id);

-- RLS: mirror risk_alerts policies.
ALTER TABLE bottlenecks ENABLE ROW LEVEL SECURITY;
```

---

### `client_communications`

```sql
CREATE TABLE client_communications (
  id                UUID                      PRIMARY KEY DEFAULT gen_random_uuid(),
  project_id        UUID                      NOT NULL REFERENCES projects (id) ON DELETE CASCADE,
  org_id            UUID                      NOT NULL REFERENCES organisations (id) ON DELETE RESTRICT,  -- denormalized for RLS
  comm_type         communication_type        NOT NULL,  -- enum: 'weekly_summary' | 'executive_summary' | 'ad_hoc'
  subject           TEXT                      NOT NULL,
  body_draft        TEXT                      NOT NULL,  -- AI-generated draft; never sent without approval
  body_approved     TEXT,                               -- final approved text (may differ from draft)
  status            communication_status      NOT NULL DEFAULT 'draft',  -- enum: see Section 4
  drafted_by_agent  TEXT                      NOT NULL DEFAULT 'client_interaction_agent',
  reviewed_by       UUID                      REFERENCES users (id) ON DELETE SET NULL,  -- must be delivery_manager role
  reviewed_at       TIMESTAMPTZ,
  approved_by       UUID                      REFERENCES users (id) ON DELETE SET NULL,
  approved_at       TIMESTAMPTZ,
  sent_at           TIMESTAMPTZ,
  created_at        TIMESTAMPTZ               NOT NULL DEFAULT now(),
  updated_at        TIMESTAMPTZ               NOT NULL DEFAULT now(),
  deleted_at        TIMESTAMPTZ
);

CREATE INDEX client_communications_project_id_idx ON client_communications (project_id);
CREATE INDEX client_communications_org_id_idx ON client_communications (org_id);
CREATE INDEX client_communications_status_idx ON client_communications (status);

-- RLS: 'client' → SELECT where org_id = their org_id AND status = 'sent' (only see approved+sent comms).
--      'delivery_manager' → SELECT/UPDATE where org_id = their org_id (can approve/send).
--      'bsg_leadership' → SELECT all.
--      'super_admin' → full access.
-- CRITICAL: INSERT is only permitted by the backend service account (service_role), not by
--   'delivery_manager' directly — DMs approve/reject, they do not create drafts.
ALTER TABLE client_communications ENABLE ROW LEVEL SECURITY;
```

---

### `communication_evidence_links`

```sql
CREATE TABLE communication_evidence_links (
  id                UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
  communication_id  UUID        NOT NULL REFERENCES client_communications (id) ON DELETE CASCADE,
  org_id            UUID        NOT NULL REFERENCES organisations (id) ON DELETE RESTRICT,  -- denormalized for RLS
  source_table      TEXT        NOT NULL,              -- e.g. 'throughput_snapshots', 'quality_snapshots'
  source_row_id     UUID        NOT NULL,              -- the specific row cited
  description       TEXT,                              -- human-readable label for the cited evidence
  created_at        TIMESTAMPTZ NOT NULL DEFAULT now()
  -- Immutable: evidence links are never updated.
);

CREATE INDEX comm_evidence_links_comm_id_idx ON communication_evidence_links (communication_id);
CREATE INDEX comm_evidence_links_org_id_idx ON communication_evidence_links (org_id);

-- RLS: mirror client_communications policies.
ALTER TABLE communication_evidence_links ENABLE ROW LEVEL SECURITY;
```

---

### `agent_queries`

```sql
CREATE TABLE agent_queries (
  id              UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id         UUID        NOT NULL REFERENCES users (id) ON DELETE RESTRICT,
  org_id          UUID        NOT NULL REFERENCES organisations (id) ON DELETE RESTRICT,  -- denormalized for RLS
  project_id      UUID        REFERENCES projects (id) ON DELETE SET NULL,               -- NULL = cross-project query
  agent_name      TEXT        NOT NULL,                -- e.g. 'delivery_performance_agent', 'client_interaction_agent'
  query_text      TEXT        NOT NULL,                -- the natural-language question
  answer_text     TEXT        NOT NULL,                -- the AI-generated answer
  model_used      TEXT        NOT NULL,                -- LLM model identifier string, e.g. 'claude-sonnet-4-6'
  latency_ms      INT,                                 -- response latency in milliseconds
  created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
  -- Immutable: queries are an append-only audit log.
);

CREATE INDEX agent_queries_user_id_idx ON agent_queries (user_id);
CREATE INDEX agent_queries_org_id_idx ON agent_queries (org_id);
CREATE INDEX agent_queries_project_id_idx ON agent_queries (project_id);
CREATE INDEX agent_queries_created_at_idx ON agent_queries (created_at DESC);

-- RLS: 'client' → SELECT where org_id = their org_id AND user_id = auth.uid().
--      'delivery_manager' → SELECT where org_id = their org_id.
--      'bsg_leadership' → SELECT all.
--      'super_admin' → full access.
ALTER TABLE agent_queries ENABLE ROW LEVEL SECURITY;
```

---

### `agent_query_evidence_links`

```sql
CREATE TABLE agent_query_evidence_links (
  id              UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
  query_id        UUID        NOT NULL REFERENCES agent_queries (id) ON DELETE CASCADE,
  org_id          UUID        NOT NULL REFERENCES organisations (id) ON DELETE RESTRICT,  -- denormalized for RLS
  source_table    TEXT        NOT NULL,                -- e.g. 'throughput_snapshots', 'quality_snapshots'
  source_row_id   UUID        NOT NULL,                -- the specific row cited
  description     TEXT,
  created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
  -- Immutable: evidence links are never updated.
);

CREATE INDEX agent_query_evidence_links_query_id_idx ON agent_query_evidence_links (query_id);
CREATE INDEX agent_query_evidence_links_org_id_idx ON agent_query_evidence_links (org_id);

-- RLS: mirror agent_queries policies.
ALTER TABLE agent_query_evidence_links ENABLE ROW LEVEL SECURITY;
```

---

### `delivery_confidence_scores` 

```sql
-- : Source explicitly shows "92% delivery confidence / this milestone"
--   (PDF p.11) and "schedule confidence" per project (PDF p.7, BSG BRD p.9).
--   Stored as a time-series to support trend charts; not just a live computed value.

CREATE TABLE delivery_confidence_scores (
  id              UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
  project_id      UUID        NOT NULL REFERENCES projects (id) ON DELETE CASCADE,
  org_id          UUID        NOT NULL REFERENCES organisations (id) ON DELETE RESTRICT,  -- denormalized for RLS
  milestone_id    UUID        NOT NULL REFERENCES milestones (id) ON DELETE CASCADE,
  score_pct       NUMERIC(5,2) NOT NULL CHECK (score_pct BETWEEN 0 AND 100),
  computed_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
  created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
  -- Immutable: scores are an append-only time-series.
);

CREATE INDEX delivery_confidence_scores_project_id_idx ON delivery_confidence_scores (project_id);
CREATE INDEX delivery_confidence_scores_milestone_id_idx ON delivery_confidence_scores (milestone_id);
CREATE INDEX delivery_confidence_scores_org_id_idx ON delivery_confidence_scores (org_id);

-- RLS: 'client' → SELECT where org_id = their org_id (read-only).
--      'delivery_manager' → SELECT where org_id = their org_id (read-only; backend inserts only).
--      'bsg_leadership' → SELECT all.
--      'super_admin' → full access.
ALTER TABLE delivery_confidence_scores ENABLE ROW LEVEL SECURITY;
```

---

### `client_csat_scores` 

```sql
-- : Source (PDF p.11) shows "4.7/5 Client CSAT / rolling".
--   Confirm whether CSAT is collected per project, per communication, or at a
--   different granularity. Confirm the scale (1–5 assumed here).

CREATE TABLE client_csat_scores (
  id              UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
  project_id      UUID        NOT NULL REFERENCES projects (id) ON DELETE CASCADE,
  org_id          UUID        NOT NULL REFERENCES organisations (id) ON DELETE RESTRICT,  -- denormalized for RLS
  submitted_by    UUID        NOT NULL REFERENCES users (id) ON DELETE RESTRICT,          -- must be 'client' role
  score           NUMERIC(3,1) NOT NULL CHECK (score BETWEEN 1 AND 5),
  comment         TEXT,
  submitted_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
  created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
  -- Immutable: CSAT submissions are append-only.
);

CREATE INDEX client_csat_scores_project_id_idx ON client_csat_scores (project_id);
CREATE INDEX client_csat_scores_org_id_idx ON client_csat_scores (org_id);

-- RLS: 'client' → INSERT where org_id = their org_id; SELECT only their own rows.
--      'delivery_manager' → SELECT where org_id = their org_id (read-only).
--      'bsg_leadership' → SELECT all.
--      'super_admin' → full access.
ALTER TABLE client_csat_scores ENABLE ROW LEVEL SECURITY;
```

---

### `metric_configurations`

```sql
-- This table is platform-wide (not org-scoped). Managed exclusively by super_admin.
-- Stores which metrics are shown on the client-facing dashboard — see PROJECT_SUMMARY §3 item 15.

CREATE TABLE metric_configurations (
  id              UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
  metric_key      TEXT        NOT NULL,                -- programmatic key, e.g. 'gold_set_accuracy', 'throughput_rolling_7d'
  display_label   TEXT        NOT NULL,                -- human-readable label shown in the client UI
  is_client_visible BOOLEAN   NOT NULL DEFAULT FALSE,  -- when TRUE, shown on client-facing dashboard
  display_order   INT         NOT NULL DEFAULT 0,      -- sort order on the dashboard
  description     TEXT,
  created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
  deleted_at      TIMESTAMPTZ

  CONSTRAINT metric_configurations_metric_key_key UNIQUE (metric_key)
);

-- RLS: Only super_admin may INSERT/UPDATE/DELETE.
--      'client', 'delivery_manager', 'bsg_leadership' → SELECT only (to render dashboard).
ALTER TABLE metric_configurations ENABLE ROW LEVEL SECURITY;
```

---

### `notifications` 

```sql
-- : Source (PROJECT_SUMMARY §3 item 3, TECH_STACK §6) specifies alert
--   delivery to PMs and Delivery Managers when thresholds are crossed.
--   Confirm whether notifications are stored (for in-app inbox) or fire-and-forget.

CREATE TABLE notifications (
  id                UUID                NOT NULL PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id           UUID                NOT NULL REFERENCES users (id) ON DELETE CASCADE,
  org_id            UUID                NOT NULL REFERENCES organisations (id) ON DELETE RESTRICT,  -- denormalized for RLS
  notification_type notification_type   NOT NULL,      -- enum: see Section 4
  title             TEXT                NOT NULL,
  body              TEXT                NOT NULL,
  source_table      TEXT,                              -- e.g. 'risk_alerts'
  source_row_id     UUID,                              -- the row that triggered this notification
  is_read           BOOLEAN             NOT NULL DEFAULT FALSE,
  sent_at           TIMESTAMPTZ,                       -- NULL until email/in-app delivery confirmed
  created_at        TIMESTAMPTZ         NOT NULL DEFAULT now(),
  updated_at        TIMESTAMPTZ         NOT NULL DEFAULT now()
);

CREATE INDEX notifications_user_id_idx ON notifications (user_id);
CREATE INDEX notifications_org_id_idx ON notifications (org_id);
CREATE INDEX notifications_is_read_idx ON notifications (user_id, is_read);

-- RLS: Each user sees only their own notifications (user_id = auth.uid()).
--      'super_admin' → full access.
ALTER TABLE notifications ENABLE ROW LEVEL SECURITY;
```

---

## 4. Enums / Constrained Value Sets

All enums are PostgreSQL `CREATE TYPE ... AS ENUM`. Agents must not extend these without updating this document first.

```sql
-- User roles — mirrors TECH_STACK.md §4 exactly
CREATE TYPE app_role AS ENUM (
  'client',
  'delivery_manager',
  'bsg_leadership',
  'super_admin'
);

-- Delivery site
CREATE TYPE delivery_site AS ENUM (
  'india',
  'kosovo'
);

-- Project lifecycle status
CREATE TYPE project_status AS ENUM (
  'active',        -- currently in delivery
  'ramping',       -- onboarding / setup phase
  'paused',        -- temporarily halted
  'completed',     -- delivery finished
  'cancelled'      -- terminated early
);

-- Milestone status
CREATE TYPE milestone_status AS ENUM (
  'pending',       -- not yet reached planned date
  'on_track',      -- within schedule confidence threshold
  'at_risk',       -- below schedule confidence threshold
  'completed',     -- actual_date is set
  'missed'         -- actual_date > planned_date, or not met at deadline
);

-- Delivery risk tier (Delivery Performance Agent BRD)
CREATE TYPE risk_tier AS ENUM (
  'low',
  'medium',
  'high',
  'critical'
);

-- Alert type — what domain triggered the alert
CREATE TYPE alert_type AS ENUM (
  'delivery_risk',         -- schedule/throughput breach
  'quality_drift',         -- quality metric below threshold
  'milestone_at_risk',     -- milestone predicted to slip
  'workforce_imbalance'    -- over/under-utilisation detected; 
);

-- Alert/bottleneck lifecycle
CREATE TYPE alert_status AS ENUM (
  'open',
  'acknowledged',
  'resolved',
  'dismissed'
);

-- Client communication lifecycle
CREATE TYPE communication_status AS ENUM (
  'draft',         -- AI-generated, not yet reviewed
  'in_review',     -- assigned to a Delivery Manager for review
  'approved',      -- DM approved but not yet sent
  'sent',          -- delivered to client
  'rejected'       -- DM rejected; draft should be revised
);

-- Communication type
CREATE TYPE communication_type AS ENUM (
  'weekly_summary',
  'executive_summary',
  'ad_hoc'
);

-- Notification type
CREATE TYPE notification_type AS ENUM (
  'risk_alert',              -- new high/critical risk alert
  'communication_pending',   -- DM has a communication to review
  'milestone_at_risk',       -- milestone confidence dropped below threshold
  'quality_drift_detected',  -- quality drift alert fired
  'system'                   -- platform/admin messages
);
```

---

## 5. Standard Fields Convention

Every table in this schema follows these conventions. Agents must not reinvent these per table.

| Convention | Rule |
|---|---|
| **Primary key** | `UUID`, generated with `gen_random_uuid()`, named `id`. Never use `SERIAL` or `BIGSERIAL`. |
| **Tenant isolation column** | Every client-data table carries `org_id UUID NOT NULL REFERENCES organisations(id)`. This is the column used in every RLS policy. Even when `org_id` is derivable by joining through `project_id`, it is denormalized onto the table directly so RLS policies are simple and index-friendly. |
| **Created timestamp** | `created_at TIMESTAMPTZ NOT NULL DEFAULT now()`. Never `TIMESTAMP` (always timezone-aware). |
| **Updated timestamp** | `updated_at TIMESTAMPTZ NOT NULL DEFAULT now()`. Must be kept current by a `BEFORE UPDATE` trigger or application-layer logic on every table that carries it. Append-only tables (throughput_snapshots, quality_snapshots, agent_queries, evidence link tables, delivery_confidence_scores, client_csat_scores) do **not** carry `updated_at`. |
| **Soft delete** | Mutable entity tables carry `deleted_at TIMESTAMPTZ` (NULL = live). Soft-deleted rows are never physically removed. Append-only/audit tables do **not** carry `deleted_at`. |
| **Boolean flags** | `NOT NULL DEFAULT FALSE` always. Never nullable booleans. |
| **Percentages** | `NUMERIC(5,2)` for 0–100 values (e.g., accuracy, rework rate). Always include a `CHECK` constraint. |
| **Ratios / probabilities** | `NUMERIC(4,3)` for 0–1 values (e.g., Krippendorff's α, slippage probability). Always include a `CHECK` constraint. |
| **Text** | Prefer `TEXT` over `VARCHAR(n)`. Add `CHECK (char_length(col) <= N)` only where a business length limit exists. |
| **Enum fields** | Always use a named PostgreSQL `CREATE TYPE ... AS ENUM`, never raw `TEXT` with unconstrained values. |
| **JSON** | Use `JSONB` (not `JSON`) for semi-structured fields (e.g., `contributing_causes`). |
| **Foreign key actions** | `ON DELETE CASCADE` for child rows that have no meaning without the parent (e.g., milestones without a project). `ON DELETE RESTRICT` for references that must not be silently deleted (e.g., `org_id` on any tenant-scoped table). `ON DELETE SET NULL` for optional references (e.g., `resolved_by`). |

---

## 6. Migration Strategy

| Decision | Rule |
|---|---|
| **Tool** | Supabase CLI (`supabase migration new <description>`). Migrations live in `supabase/migrations/`. If the team switches to Alembic, all rules below still apply; only the tooling changes. See TECH_STACK.md open question #16. |
| **File naming** | Supabase CLI default: `{unix_timestamp}_{snake_case_description}.sql`. Example: `20260619120000_create_organisations.sql`. Never rename a migration file after it has been applied to any environment. |
| **Ordering** | Enums must be created before the tables that reference them. Tables must be created before their foreign-key dependants. Suggested order: enums → organisations → users → projects → milestones → teams → annotators → throughput_snapshots → quality_snapshots → quality_error_entries → risk_alerts → bottlenecks → client_communications → communication_evidence_links → agent_queries → agent_query_evidence_links → delivery_confidence_scores → client_csat_scores → metric_configurations → notifications → RLS policies → indexes. |
| **RLS policies** | RLS policies must be written in the same migration file as the table they protect (or in a dedicated subsequent migration — never before the table exists). Every table in this schema has `ALTER TABLE ... ENABLE ROW LEVEL SECURITY` — this is not optional. |
| **Seed data** | `supabase/seed/` contains synthetic/anonymised data only. Never commit real client data to seed files. A `metric_configurations` seed is required (initial set of metrics), managed by Super Admin in production. |
| **Backward compatibility** | Never `DROP COLUMN`, `DROP TABLE`, or change an enum value in a migration without a prior deprecation migration. Prefer `ALTER TABLE ... ADD COLUMN` with a nullable default. |
| **Environment promotion** | Migrations run automatically in CI on merge to `main` (targeting `staging`). Production migrations require a manual approval step in the GitHub Actions workflow. |

---

## 7. Business Rules Not Enforceable by Schema Alone

The following rules must be enforced at the application layer (FastAPI service functions), not in the database schema. Backend agents must implement these as explicit checks before writing to the database.

1. **Client communication approval gate:** A `client_communications` row may only transition to `status = 'sent'` if `approved_by` is set AND the referenced user carries `role = 'delivery_manager'`. The schema cannot constrain the role of `approved_by`; the service layer must verify this before the update.

2. **Evidence-backed AI outputs:** Before inserting any row into `agent_queries`, the backend service must ensure at least one matching `agent_query_evidence_links` row will be inserted in the same transaction. An `agent_queries` row with zero evidence links violates the "Evidence-Backed AI" principle from the source material and must not be committed. Same rule applies to `client_communications`: `body_draft` rows must have at least one `communication_evidence_links` row.

3. **Delivery confidence threshold:** A `milestones` row should be set to `status = 'at_risk'` when the latest `delivery_confidence_scores.score_pct` for that milestone falls below 80% (the provisional draft threshold from PROJECT_SUMMARY §5). This threshold is a WIP value — the service must read it from `metric_configurations`, not hardcode it.

4. **Quality drift alert trigger:** A `quality_snapshots` row with `gold_set_accuracy_pct < 95` OR `iaa_krippendorff_alpha < 0.85` OR `rework_rate_pct > 5` should set `has_drift_alert = TRUE` and trigger insertion of a `risk_alerts` row of type `quality_drift`. These thresholds are WIP — see PROJECT_SUMMARY §5; read from `metric_configurations`.

5. **Tenant isolation enforcement:** Every FastAPI route that queries a client-data table must pass `org_id` as a filter. RLS provides the database-layer guarantee, but the service layer must also never construct a query that is intended to cross tenant boundaries. Routes must extract `org_id` from the JWT claim, not from the request body.

6. **Super Admin metric config changes:** Changes to `metric_configurations.is_client_visible` take effect immediately on next page load. The frontend must not cache this configuration client-side beyond a single session request.

7. **Soft-delete visibility:** All queries against tables with `deleted_at` must include `WHERE deleted_at IS NULL` unless the intent is explicitly to retrieve deleted records (audit/admin contexts only). This filter must be applied in the SQLAlchemy base query class, not repeated per route.

8. **CSAT submitter role check:** Inserts into `client_csat_scores` must verify `submitted_by` carries `role = 'client'`.  — confirm whether Delivery Managers can also submit CSAT on behalf of a client.

9. **Communication draft ownership:** Only the backend service account (`service_role`) may insert `client_communications` rows. Delivery Managers may only UPDATE the `status`, `body_approved`, `reviewed_by`, `reviewed_at`, `approved_by`, `approved_at`, `sent_at` columns.

---

## 8. Schema Diagram Description

The following table-and-relationship description is suitable for generating an ER diagram in Mermaid, dbdiagram.io, or any similar tool.

```
organisations       [1] ─── [N] users
organisations       [1] ─── [N] projects
projects            [1] ─── [N] milestones
projects            [1] ─── [N] throughput_snapshots
projects            [1] ─── [N] teams
projects            [1] ─── [N] quality_snapshots
projects            [1] ─── [N] risk_alerts
projects            [1] ─── [N] bottlenecks
projects            [1] ─── [N] client_communications
projects            [1] ─── [N] delivery_confidence_scores
projects            [1] ─── [N] client_csat_scores
milestones          [1] ─── [N] delivery_confidence_scores
teams               [1] ─── [N] annotators
teams               [1] ─── [N] quality_snapshots
quality_snapshots   [1] ─── [N] quality_error_entries
risk_alerts         [N] ─── [1] milestones              (optional FK)
risk_alerts         [N] ─── [1] users                   (resolved_by, optional)
bottlenecks         [N] ─── [1] teams                   (optional FK)
bottlenecks         [N] ─── [1] users                   (resolved_by, optional)
client_communications [1] ─── [N] communication_evidence_links
client_communications [N] ─── [1] users                 (approved_by, optional)
agent_queries       [N] ─── [1] users
agent_queries       [N] ─── [1] projects                (optional FK)
agent_queries       [1] ─── [N] agent_query_evidence_links
notifications       [N] ─── [1] users
metric_configurations  (no FK relationships — platform-wide table)

All client-data tables carry org_id FK → organisations (denormalized for RLS).
```

---

## 9. Open Questions

All items marked **** above are collected here. Each must be confirmed or overridden by a human before the relevant migration is committed to `staging` or `prod`.

| # | Table / Field | What needs deciding |
|---|---|---|
| 1 | `annotators` | Are individual annotators tracked in this system, or only teams in aggregate? The source names 72 deployed experts and site-level utilisation but does not specify individual records. |
| 2 | `annotators.team_id` | Is team assignment a single FK (current team) or a history table? Annotators may move between teams/projects over time. |
| 3 | `bottlenecks` | Should bottlenecks be a standalone table, or merged into `risk_alerts` with `alert_type = 'delivery_risk'`? The two overlap in semantics; the current design keeps them separate for query clarity. |
| 4 | `delivery_confidence_scores` | Confirmed as a stored time-series (not just a live computed value)? If the score is always derived at query time from `throughput_snapshots` + `milestones`, this table is unnecessary. |
| 5 | `client_csat_scores.score` | Confirm the scale: 1–5 (assumed here based on "4.7/5" in source) vs 1–10. Confirm granularity: per project, per communication, or per week? |
| 6 | `client_csat_scores` | Confirm whether Delivery Managers can submit CSAT on behalf of clients, or only client-role users. |
| 7 | `notifications` | Confirm whether notifications are stored in-database (for an in-app inbox) or fire-and-forget via email only. If fire-and-forget, this table can be removed. |
| 8 | `risk_alerts.contributing_causes` | `JSONB` is used for the contributor breakdown. Confirm this is acceptable or whether a separate `risk_alert_causes` child table is preferred for queryability. |
| 9 | `metric_configurations` | Is this truly platform-wide (one global config) or per-organisation (each client can have a different metric set)? Source says Super Admin configures it "system-wide" — assumed global here. |
| 10 | `quality_snapshots` granularity | Source shows data "by team and by week". Confirm whether a finer granularity (daily, per annotator) is needed for Phase 1, or weekly per team is sufficient for MVP. |
| 11 | `teams.domain` | Is `domain` a free-text field or a constrained enum? Source names: Radiology CV, Clinical NLP, Pathology, Genomics, General CV. A new client vertical (Finance, Logistics) would add different domain names. |
| 12 | `alert_type` enum: `workforce_imbalance` | Source describes workforce rebalancing recommendations (BSG BRD §f) but this is an Agent 3 (Phase 2) feature. Confirm whether `workforce_imbalance` alerts belong in the Phase 1 schema. |
| 13 | Workforce utilisation history | Source shows per-site utilisation % (India 89%, Kosovo 82%) and SME coverage tracking. Is this derived on the fly from `annotators` + project assignments, or stored as a separate time-series table (not modelled here)? |
| 14 | Project readiness assessments | Source (BRD §f) describes a scored readiness assessment for go-live. No table is modelled for this — it may be a Phase 2 concern (Client Interaction Agent). Confirm whether it belongs in Phase 1 schema. |
| 15 | `updated_at` trigger | Confirm whether `updated_at` is maintained by a PostgreSQL `BEFORE UPDATE` trigger (preferred for reliability) or by the application layer (SQLAlchemy `onupdate`). |
