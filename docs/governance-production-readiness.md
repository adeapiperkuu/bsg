# Project Governance Production Readiness

Phase 8 hardens the Project Governance Agent for production use without changing the visible workflows.

## Access Control

- Read access remains limited to delivery managers, BSG leadership, super admins, and clients where existing project visibility allows it.
- Write access remains limited to delivery managers and super admins.
- Governance monitoring is restricted to BSG leadership and super admins.
- Super admins retain cross-organisation visibility where the governance services already support it.

## Audit Trail

Governance mutations now write append-only `audit_logs` events using the `governance.*` event namespace. Covered events include dependency, escalation, action, scope state, weekly summary, project charter, analytics export, and delivery-risk promotion changes.

Each event records the actor, source table, source row, previous values, new values, and metadata where available.

## Notifications

High-priority governance notifications are created for leadership-relevant changes:

- Blocking dependencies.
- Critical escalations.
- Scope states waiting for revision or approval.

Notifications reuse the existing notifications table and `SYSTEM` notification type so the feature does not require a schema-breaking enum change.

## AI Safety

The governance chatbot and generated artifacts continue to rely on approved governance evidence. Monitoring tracks empty or low-evidence answers so operators can detect evidence gaps and prompt quality issues.

Phase 6 adds grounded AI recommendations (`docs/governance-ai-recommendations.md`). Generation is user-triggered, validated, and persisted separately from analytics reads. Rule-based recommendations remain the fallback when AI is disabled or fails grounding.

## Monitoring

`GET /governance/monitoring?window_hours=24` returns operational counters for:

- Governance audit event volume.
- Governance chatbot query volume.
- Average and p95 chatbot latency.
- Empty or insufficient-evidence answers.
- Dashboard and charter exports.
- Most common recent governance event types.

## Exports

Analytics export endpoints are available for CSV and PDF:

- `GET /governance/analytics/export.csv`
- `GET /governance/analytics/export.pdf`

Exports are audited through the same governance audit trail.

## Performance

Phase 8 adds partial indexes for active governance records and monitoring paths:

- Dependencies by organisation, project, status, and due date.
- Escalations by organisation, project, status, severity, and raised date.
- Actions by organisation, project, status, due date, and completion date.
- Scope states by organisation, project, and status.
- Project charters by organisation, project, status, and created date.
- Governance chatbot queries by organisation, agent, and created date.
- Governance audit logs by organisation and created date.

Phase B completes process-local first-page cache coverage for the default Governance actions and
escalations dashboard reads:

- Only unfiltered `limit=6`, `offset=0` requests are cached for 60 seconds.
- Keys include effective organization, role, and user identity; client entries therefore never
  cross assignment scopes.
- Client assignment and publish-gate predicates remain in the database query on misses.
- Phase B cache hits execute zero SQL statements; measured p50 was 0.1 ms for actions, 0.2 ms for
  internal escalations, and 0.1 ms for client escalations.
- Mutations clear affected-organization entries only after commit, including super-admin aggregate
  variants.
- The caches are process-local. Multi-worker deployments do not share entries, hit ratios, or
  invalidation messages, and no Redis/shared-cache support is claimed.

Phase D removes UTC day-rollover maintenance from the register GET request:

- Normal register cache misses execute one paginated read; warm hits execute zero SQL statements.
- APScheduler triggers a catch-up refresh hourly at minute 5 in UTC. Freshness predicates make the
  update effective once per summary row per UTC day.
- A PostgreSQL transaction advisory lock prevents multiple application workers from performing the
  same refresh concurrently.
- Refresh commits before organization-scoped register cache invalidation. Failures roll back,
  preserve the previous committed summaries, log the error, and retry at the next trigger.
- Another worker's process-local register page may remain warm for at most its remaining 60-second
  TTL after a refresh commit; no cross-worker invalidation bus is present.
- `GOVERNANCE_REGISTER_DAILY_REFRESH_ENABLED` controls the job and defaults to enabled.
- Manual operation: run
  `.\.venv\Scripts\python.exe scripts\refresh_governance_register_summaries.py` from `backend`.
- The business-day definition is UTC because the platform currently has no organization-timezone
  setting.

Phase E removes the project-sheet initial request fan-out:

- `GET /governance/project-sheet/{project_id}` returns one explicit, bounded read model.
- Successful reads use one SQL statement; a denied/missing read uses one additional existence check
  solely to preserve 403 versus 404 behavior.
- Dependency, action, escalation, and delivery-risk sections are limited to six items and include
  `total` / `has_more`; full individual APIs remain available after **View all**.
- Authorization is performed in the statement's authorized-project CTE. Organization isolation,
  active client assignment, `client_visible` escalation publication, internal scope notes, and
  delivery-risk permissions remain section-specific.
- Project charters/history, AI recommendations, audits, exports, and long
  activity feeds remain deferred and are not included in the sheet response.
- The frontend opens the sheet with one React Query request and a coordinated loading/error state.
  Successful mutations invalidate only the affected project's composite key.
- Measured internal development results against remote Supabase were 5 HTTP / 6 executes /
  5948.8 ms p50 before versus 1 HTTP / 1 execute / 1137.8 ms p50 after.
- The measured bounded payload was 2,450 bytes uncompressed and 938 bytes gzipped, with 0.11 ms
  average serialization time.
- No endpoint cache was added. Correct one-execute behavior is measured directly rather than hidden
  behind a warm cache.
- Browser automation was unavailable; the request harness verifies one composite request and no
  initial section fan-out but does not claim real-browser latency.

## Remaining Opportunities

- Capture an authenticated internal and client browser Network waterfall in a production-like
  environment; the configured benchmark dataset currently has no active client assignment.
- Add a small real-browser performance budget for project-sheet response size and coordinated
  loading once browser automation is available in CI.
- Alert when the scheduled register refresh reports failures or zero refreshed rows after UTC
  rollover, and track the age of the oldest summary row.
- Add organization-local rollover only if an explicit organization-timezone setting is introduced;
  do not infer it from user or server time.
- Add shared cache/invalidation infrastructure only if multi-worker hit-rate data justifies its
  operational complexity.
- Add synthetic cache-hit, cache-miss, and execute-count monitoring for the default Governance list
  shapes.
- If project assignments become mutable through an application API, connect its successful commit
  to Governance read-cache invalidation; external direct database edits currently age out through
  the 60-second TTL.
- Add first-class notification priority/archive columns if the notification schema evolves.
- Expand Slack/email adapters beyond critical governance notifications (digest digests, client channels).
- Add server-side Excel exports if executive users require workbook formatting.
- Add synthetic monitoring for `/governance`, `/governance/bootstrap`, and chatbot latency.
- Connect Team Health Score once Workforce owns ingest (no tables yet).

## Recent additions

- Quality BR-06 auto-escalation into `governance_escalations` (scheduled; feature-flagged).
- Client-safe escalation summaries (`client_summary` / `client_visible` publish gate).
- Optional Slack webhook + Resend email for critical governance notifications
  (`GOVERNANCE_OUTBOUND_NOTIFICATIONS_ENABLED`, `SLACK_WEBHOOK_URL`, `EMAIL_*`).
- Critical-path dependency highlighting on Dependency Tracker (blocking + overdue).

## Related

- Phase 11 executive insights dashboard (scores, rates, heatmap, filtered exports): `docs/governance-insights-dashboard.md`

## Phase F: durable background jobs

Phase F removes AI/provider waits and large analytics rendering from request handlers.
Recommendation generation/regeneration, escalation scans, weekly-summary drafts, charter drafts,
and analytics CSV/PDF exports now return `202` jobs. PostgreSQL advisory locking plus an active-job
partial unique index suppress duplicates; `FOR UPDATE SKIP LOCKED` prevents double claims.

Production controls now present:

- requester- and tenant-scoped job APIs;
- bounded transient retries with safe errors;
- queued cancellation and running safe-checkpoint cancellation;
- persisted heartbeat, attempts, timings, result references, and immutable lifecycle events;
- stale-worker recovery;
- scheduler polling plus a dedicated worker command;
- frontend polling, refresh discovery, terminal stop, and targeted result invalidation;
- no automatic approval, conversion, escalation, or publication.

Apply `20260715100000_governance_background_jobs_phase_f.sql` before enabling workers. Before
horizontal scaling, replace local export storage with shared object storage and add retention
cleanup. Full operations are documented in `docs/governance-background-jobs.md`.
