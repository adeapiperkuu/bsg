# Governance background jobs

Phase F moves Governance AI generation and large analytics exports from synchronous HTTP handling
to a durable PostgreSQL queue. Requests authorize and validate, create or reuse a job, commit it,
and return `202 Accepted`. A worker later creates the draft, suggestion, or export.

## Architecture

```text
Governance control
  -> authorization + deterministic idempotency key
  -> governance_jobs row + requested event
  -> 202 with job ID

Scheduler or standalone worker
  -> FOR UPDATE SKIP LOCKED claim and short commit
  -> evidence read and commit
  -> external AI / export work without an open DB transaction
  -> validate and commit product record
  -> mark job succeeded and store result reference

React Query
  -> discover latest active job after refresh
  -> poll GET /governance/jobs/{id} every 3 seconds
  -> stop on succeeded, failed, or cancelled
  -> invalidate the relevant product query after success
```

This reuses the repository's knowledge-ingestion pattern: PostgreSQL is the durable queue,
APScheduler polls it, workers open their own sessions, and transient failures use bounded backoff.
No Redis, Docker, Azure service, or FastAPI `BackgroundTasks` dependency was added.

## Supported job types

| Job type | Product result | Review-first guarantee |
|---|---|---|
| `ai_recommendation_generate` | Recommendation rows | User reviews before conversion |
| `weekly_summary_generate` | Draft weekly summary | Explicit approval remains required |
| `project_charter_generate` | Draft charter version | Explicit approval and publication remain required |
| `governance_analytics_export` | Protected CSV or PDF | Download only after success |

Approvals, conversions, feedback, dismissals, snoozing, ordinary CRUD, and charter/summary document
downloads remain synchronous.

## Lifecycle and progress

Statuses are `queued`, `running`, `retry_scheduled`, `succeeded`, `failed`,
`cancellation_requested`, and `cancelled`. Meaningful stages include `collecting_evidence`,
`building_context`, `generating`, `validating`, `persisting`, and terminal stages. Product services
may combine validation and persistence internally; job success is written only after the product
transaction commits.

Immutable `governance_job_events` rows record requested, started, retry scheduled, succeeded,
failed, cancellation requested, cancelled, and stale recovery events.

## Deduplication

The canonical payload is hashed with job type, organization, project, and—only for user-specific
exports—requester. Recommendation keys include prompt and strategy versions; escalation scans
include active configuration; summaries include week start; charters include source strategy;
exports include normalized filters and format.

Creation takes a transaction-scoped PostgreSQL advisory lock. A partial unique index on active
`idempotency_key` values is the concurrency safety net. Repeated clicks and retries return the
existing active job with `deduplicated=true`.

## Claiming, heartbeat, and recovery

Workers claim one ready row with `FOR UPDATE SKIP LOCKED`, increment `attempt_count`, assign a
worker ID, and commit before product work. Each execution gets independent short-lived sessions.
Heartbeat updates default to every 30 seconds.

Jobs older than `GOVERNANCE_JOB_STALE_SECONDS` are recovered. Jobs with attempts remaining move to
`retry_scheduled`; exhausted jobs fail with `WORKER_INTERRUPTED`. Stale cancellation requests
become cancelled.

## Retries and cancellation

Automatic retry uses bounded exponential delays of 5, 10, and up to 300 seconds. Timeouts, rate
limits, temporary network/database/storage failures, and worker interruption are transient.
Invalid input, authorization, missing targets, unsupported formats, and invalid schemas are
terminal. Persisted errors contain stable codes and safe messages, never prompts, tokens, stack
traces, secrets, or connection strings.

Queued and retry-scheduled jobs cancel immediately. Running jobs become
`cancellation_requested` and stop only at a safe checkpoint. If a product already committed, the
job succeeds because cancellation must not hide or undo it.

## API

Start responses use `202`:

```json
{
  "data": {
    "job_id": "uuid",
    "job_type": "weekly_summary_generate",
    "status": "queued",
    "deduplicated": false
  }
}
```

```text
GET  /api/v1/governance/jobs
GET  /api/v1/governance/jobs/{job_id}
POST /api/v1/governance/jobs/{job_id}/retry
POST /api/v1/governance/jobs/{job_id}/cancel
GET  /api/v1/governance/jobs/{job_id}/download
POST /api/v1/governance/analytics/exports
```

Legacy analytics CSV/PDF paths also return a 202 job. Reads expose progress, attempts, timestamps,
safe errors, retry/cancel flags, and result references; internal storage paths are removed.

## Authorization

Only delivery managers, BSG leadership, and super administrators can use job APIs. Start routes
retain project, organization, scope, and role checks. Lookup requires organization visibility and
`requested_by` ownership, so knowing another job UUID grants no access. Clients cannot start,
discover, inspect, cancel, retry, or download jobs.

## Migration and local commands

Apply the Phase F migration:

```powershell
cd backend
.\.venv\Scripts\python.exe scripts\apply_migrations.py 20260715100000_governance_background_jobs_phase_f.sql
```

The API scheduler polls automatically. A dedicated worker can also run:

```powershell
cd backend
.\.venv\Scripts\python.exe scripts\run_governance_worker.py
```

Process one batch and exit:

```powershell
.\.venv\Scripts\python.exe scripts\run_governance_worker.py --once
```

Multiple workers are safe because claiming uses `SKIP LOCKED`.

## Environment

```text
GOVERNANCE_JOB_POLL_INTERVAL_SECONDS=5
GOVERNANCE_JOB_POLL_BATCH_SIZE=3
GOVERNANCE_JOB_STALE_SECONDS=180
GOVERNANCE_JOB_HEARTBEAT_SECONDS=30
GOVERNANCE_JOB_WORKER_ID=
GOVERNANCE_JOB_EXPORT_DIR=./data/governance-exports
```

## Monitoring and troubleshooting

Structured logs emit queue depth, oldest queued age, job type, queue wait, processing time, status,
attempt count, and safe failure code.

- `SCHEMA_NOT_READY` or “migration unavailable”: apply the Phase F migration.
- Jobs remain queued: run the standalone worker once and inspect logs.
- Repeated stale recovery: keep heartbeat below the stale threshold and inspect worker/database
  availability.
- Missing completed export: the worker and API must share `GOVERNANCE_JOB_EXPORT_DIR`.
- Existing job returned: active-job deduplication is working.

## Current limitation

Export files use protected local storage. This suits the current single-host runtime, but scaled or
ephemeral deployments need shared object storage and retention cleanup. Job state and Governance
product rows remain durable in PostgreSQL.
