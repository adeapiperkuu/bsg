# Governance Page Latency Baseline

Measurement-only baseline captured **2026-07-06** before any governance performance refactors. Use this document to compare each optimization phase against the same endpoints and log fields.

## What loads on first paint

Route: `/governance` → `GovernanceDashboard` (`frontend/src/features/governance/GovernanceDashboard.tsx`).

Load orchestration lives in `GovernanceDashboard.tsx` with defer/idle gates in `governance-load-strategy.ts`.

### Internal users (`delivery_manager`, `bsg_leadership`, `super_admin`)

| Order | React Query | HTTP endpoint | Blocks first paint? |
|------|-------------|---------------|---------------------|
| 1 | `governanceDependenciesQueryOptions` | `GET /api/v1/governance/dependencies?limit=50&offset=0` | Yes — primary table tab (default) |
| 2 | `governanceBootstrapQueryOptions` | `GET /api/v1/governance/bootstrap` | Partial — KPI strip + tab badge fallbacks |
| 3 | `governanceAnalyticsSummaryQueryOptions(30)` | `GET /api/v1/governance/analytics/summary?days=30` | Partial — executive analytics header (deferred 200 ms after mount) |
| 4 | `projectsQueryOptions` | `GET /api/v1/projects` | No on cold load — only when filters/dialogs/charters/agent need project names |

**Progressive after summary:** `governanceAnalyticsDetailQueryOptions(30)` → `GET /api/v1/governance/analytics/detail?days=30` loads when summary succeeds and the detail section is idle or in view (`requestIdleCallback` / `IntersectionObserver`).

**Not on first load:** register, actions, scope states, delivery portfolio, users, charters, agent chat, monolithic `GET /governance/analytics`.

### Client users (`client`)

| Order | React Query | HTTP endpoint | Blocks first paint? |
|------|-------------|---------------|---------------------|
| 1 | `governanceEscalationsQueryOptions` | `GET /api/v1/governance/escalations?limit=50&offset=0` | Yes — primary table tab (default) |
| 2 | `governanceBootstrapQueryOptions` | `GET /api/v1/governance/bootstrap` | Partial — KPI strip + tab badge fallbacks |
| 3 | `projectsQueryOptions` | `GET /api/v1/projects` | No on cold load — only when filters/dialogs need project names |

**Not on first load:** dependencies, actions, analytics (internal-only), register, agent/charters tools.

### Lazy-loaded on tab or interaction

| Trigger | Endpoint |
|---------|----------|
| Register tab | `GET /governance/register` |
| Actions tab | `GET /governance/actions` |
| Register tab + delivery context | `GET /delivery/portfolio` (delivery agent) |
| Project sheet open | Re-fetch lists with `project_id`; internal users also fetch `GET /governance/scope-states` |
| Charters sub-tab | `GET /governance/project-charters` |
| Create/edit dialog | `GET /users` |

## Backend timing instrumentation

All governance routes are wrapped by `instrument_governance_routes()` in `backend/app/agents/governance/routes/governance.py`.

Each request emits a log line:

```text
governance_endpoint_timing endpoint=GET /governance/analytics/summary role=delivery_manager org_id=<uuid> row_count=1 total_ms=1426.6 db_ms=1426.6 serialization_ms=0.1
```

Structured fields (also in `logging` `extra`):

- `endpoint` — HTTP method + path
- `role` — caller role (`delivery_manager`, `client`, …)
- `org_id` — organisation UUID (or `null` for cross-org super admin)
- `row_count` — rows returned (list endpoints) or `1`/`0` for data payloads
- `total_ms` — full handler time
- `db_ms` — time inside `governance_db_section` / `@governance_db_timed` service calls
- `serialization_ms` — `total_ms - db_ms` (Pydantic mapping, response build, cache hits)

DB-timed service entry points include list pages, register, analytics summary/detail, bootstrap KPI computation, and shared pagination helpers.

### How to capture logs locally

1. Start the API: `backend/run_dev_server.ps1`
2. Open `/governance` as an internal user and as a client user (hard refresh).
3. Grep backend stdout:

```bash
# PowerShell
Select-String -Pattern "governance_endpoint_timing" <backend-log-file>
```

Compare `total_ms` and `db_ms` per `endpoint` and `role`.

## Measured baseline (dev DB, 3-run average)

Captured via service-layer benchmark against the live Supabase dev database (delivery manager, org `0ac27787-896c-49e4-b90a-616c13a3694e`, cold cache):

| Endpoint | total_ms | db_ms | serialization_ms | Notes |
|----------|----------|-------|------------------|-------|
| `GET /governance/analytics` | **1427** | 1427 | 0.1 | Monolithic payload; **not used by current UI** (kept for backward compatibility) |
| `GET /governance/analytics/summary` | ~900–1100 | ~900–1100 | <1 | Internal first-paint analytics header (pre-optimization baseline) |
| `GET /governance/analytics/detail` | ~300–500 | ~300–500 | <1 | Progressive load after summary |
| `GET /governance/escalations` | 441 | 439 | 2.1 | Client-user primary table |
| `GET /governance/register` | 403 | 403 | 0.1 | Not on first paint; heavy per-project subqueries |
| `GET /governance/dependencies` | 375 | 374 | 1.6 | Internal first-paint table (pre-optimization baseline) |
| `GET /governance/bootstrap` | 343 | 342 | 0.1 | KPI strip + tab totals |

Client user escalations (representative client org): **~60–120 ms** after connection warm-up.

Internal first-paint critical path (parallel requests): dominated by **analytics summary** + **dependencies** + **bootstrap**. Analytics detail loads progressively and does not block the initial shell.

## What to optimize first

1. **`GET /governance/analytics/summary`** — Re-benchmarked **~377 ms** warm (down from **~800–1100 ms**). Further wins require regional DB proximity or accepting cache hits; see Analytics summary endpoint profiling.
2. **`GET /governance/dependencies`** — Re-benchmarked **~349 ms** warm with **1 DB round trip** (down from **~375 ms** / 2 executes). 60 s in-process cache for default list; see Dependencies endpoint profiling.
3. **`GET /governance/bootstrap`** — Parallel KPI fetch; short in-process KPI cache (not Redis).
4. **`GET /governance/register`** — Not first paint, but expensive when users switch tabs; same class of multi-subquery aggregation as analytics.
5. **`GET /governance/analytics/detail`** — Progressive only; optimize after summary path is stable.

Defer: agent chat, charter generation, export endpoints, monolithic `GET /governance/analytics` — not on dashboard first paint.

## Dependencies endpoint profiling

**Endpoint:** `GET /governance/dependencies?limit=50&offset=0`  
**Handler:** `list_governance_dependencies` → `list_governance_dependencies_page` (`governance_service.py`)

### Query shape (default internal request, after 2026-07-07 optimization)

1. **Single paginated query** — `_dependency_list_stmt` selects only list-table columns (`id`, `project_id`, `title`, `dependency_type`, `owner_id`, `due_date`, `status`) plus `projects.name` and `coalesce(users.full_name, users.email)` for display. Adds `count(*) OVER () AS _pagination_total`, then `ORDER BY due_date NULLS LAST, created_at DESC`, `LIMIT 50 OFFSET 0`. **One DB execute** on the request session.
2. **Count fallback** — separate lightweight `count(*)` query (no joins) only when the page is empty **and** `offset > 0` (rare).
3. **Serialization** — `map_dependency_list_row` builds `ProjectDependencyListRead` from row tuples (no ORM hydration, no lazy loads).
4. **Cache** — 60-second in-process TTL for unfiltered default requests (`limit`/`offset` only); invalidated on dependency create/update/resolve/delete.

Profiling log (when service `total_ms >= 200`):

```text
governance_dependencies_list_profile total_ms=351.4 db_executes=1 row_count=6 limit=50 offset=0 cached=false
```

Route-level timing (same request):

```text
governance_endpoint_timing endpoint=GET /governance/dependencies role=delivery_manager org_id=... row_count=6 total_ms=352.1 db_ms=350.4 serialization_ms=1.7
```

### Pagination strategy comparison (dev DB, org `0ac27787-896c-49e4-b90a-616c13a3694e`, 6 rows)

| Strategy | DB executes | Warm total_ms | Notes |
|----------|-------------|---------------|-------|
| Sequential count + rows (2 round trips, 1 session) | 2 | ~411 | Baseline before parallel |
| Parallel count + rows (2 round trips, 2 pool sessions) | 2 | ~352 | Prior optimization (2026-07-06) |
| **`count(*) OVER()` single query (chosen)** | **1** | **~349** | Same warm latency, half the round trips, no extra pool connections |
| In-process cache hit (60 s TTL) | 0 | **<5** | Repeat default list within TTL |

**Finding:** SQL CPU time is negligible (<1 ms). End-to-end latency is dominated by **one Supabase round trip per cold request (~350 ms)** on the dev network. Sub-250 ms on cold load is not achievable without regional DB proximity; the 60 s in-process cache covers React Query refetches and tab revisits.

### EXPLAIN ANALYZE summary (dev DB, default list)

| Query | Plan highlight | Execution time |
|-------|----------------|----------------|
| Paginated rows + `count(*) OVER()` | `Seq Scan` on `project_dependencies` (tiny table) → nested loop `projects_pkey` + `users_pkey` → window aggregate → `Sort` → `Limit` | **~0.2–0.5 ms** |
| Count fallback (offset > 0, empty page) | `Seq Scan` on `project_dependencies` + `Aggregate` | **~0.07 ms** |

No `count() OVER()` on a separate heavy join fan-out — the window runs on the same filtered row set as the page. Count query fallback has **no joins**.

### Optimizations applied

| Date | Change | Rationale | Effect |
|------|--------|-----------|--------|
| 2026-07-06 | Parallel count + rows in `_execute_paginated_rows` | Overlap network latency | Warm **~306–310 ms** (superseded) |
| 2026-07-06 | Indexes `project_dependencies_active_org_due_created_idx`, `project_dependencies_active_org_id_idx` | Match org filter + default sort / count | Planner ready at scale |
| **2026-07-07** | **`count(*) OVER()` on request session** | Reduce 2 round trips → 1 | Warm **~349 ms**, `db_executes=1` |
| **2026-07-07** | **60 s in-process cache** for default unfiltered list | Repeat fetches without DB | **<5 ms** within TTL |
| **2026-07-07** | **Profile log** `governance_dependencies_list_profile` | Observability when `total_ms >= 200` | Kept as lightweight debug |

Migration: `supabase/migrations/20260706143000_governance_dependencies_list_index.sql`  
**No new indexes added** — EXPLAIN on dev DB did not justify additional indexes at current table sizes.

### Before / after timing (dev DB, delivery manager, cache cleared each run)

| Metric | Phase 0 baseline | After parallel (2026-07-06) | After single-query (2026-07-07) |
|--------|------------------|-------------------------------|----------------------------------|
| `list_governance_dependencies_page` warm | **~375 ms** | **~306–352 ms** | **~349 ms** |
| DB executes (default page) | 2 (sequential) | 2 (parallel) | **1** |
| `serialization_ms` | ~1–2 ms | ~1–2 ms | ~1–2 ms |
| Cache hit (60 s TTL) | N/A | N/A | **<5 ms** |

**Note:** Warm cold-cache-cleared latency is network-bound at ~350 ms per round trip. Target <200–250 ms requires co-located DB/API or accepting cache hits for repeat requests.

## Analytics summary endpoint profiling

**Endpoint:** `GET /governance/analytics/summary?days=30`  
**Handler:** `governance_analytics_summary` → `get_governance_analytics_summary` (`analytics_service.py`)

### Query shape (internal user, after optimization)

1. **Project metrics (single round trip)** — `_summary_project_metrics_stmt` joins visible `projects` with four org-scoped aggregate subqueries (dependencies, escalations, overdue actions, pending scope revisions). Replaces separate project list + four `count(*)` queries.
2. **Delivery signals (single round trip)** — `GOVERNANCE_SIGNAL_BUNDLE_SQL` in `delivery_signals.py` unions throughput, quality, milestones, risks, and bottleneck aggregates in one SQL statement. Replaces five sequential delivery queries. Skips redundant org re-check when caller passes scoped `projects_by_id`.
3. **Serialization** — in-process scoring + `GovernanceAnalyticsSummaryRead` mapping (summary-only fields; no trend/chart payloads).
4. **Cache** — 3-minute in-process TTL per `(org, role, user, days)`; cache hits are sub-millisecond.

Profiling log (when `total_ms >= 300`):

```text
governance_analytics_summary_profile total_ms=387.5 project_count=19 ranking_count=8 query_timings={'project_metrics': 198.2, 'delivery_signals': 176.4}
```

Route-level timing (same request):

```text
governance_endpoint_timing endpoint=GET /governance/analytics/summary role=delivery_manager org_id=... row_count=1 total_ms=387.5 db_ms=386.1 serialization_ms=1.4
```

### EXPLAIN ANALYZE summary (dev DB, org `0ac27787-896c-49e4-b90a-616c13a3694e`, 19 projects)

| Query | Plan highlight | SQL execution time |
|-------|----------------|-------------------|
| Project metrics combined | Seq scan / hash aggregate on small governance tables; nested loop to `projects_pkey` | **<5 ms** |
| Delivery signal bundle | Window functions on `throughput_snapshots` / `quality_snapshots`; index scans on `milestones`, `risk_alerts`, `bottlenecks` | **<10 ms** |

**Finding:** SQL CPU is negligible. End-to-end latency is dominated by **two Supabase round trips** (project metrics + delivery bundle) at ~150–270 ms each on a warm pool. Parallel multi-session approaches were tried and **regressed** (connection-pool contention; 1.2–2.5 s).

### Optimizations applied (2026-07-06)

| Change | Rationale | Effect |
|--------|-----------|--------|
| `_summary_project_metrics_stmt` — one joined aggregate query | Cut 5 round trips → 1 for governance counts + project list | Major reduction from ~800 ms baseline |
| `GOVERNANCE_SIGNAL_BUNDLE_SQL` — single delivery input query | Cut 5 delivery round trips → 1 | Warm path **~377 ms** (down from **~640–870 ms**) |
| Skip `_filter_accessible_project_ids` when scoped `projects_by_id` provided | Avoid redundant round trip on summary/detail paths | ~50–100 ms saved when applicable |
| Profile log `governance_analytics_summary_profile` when `total_ms >= 300` | Temporary observability without hot-path overhead on fast/cache hits | Kept as lightweight debug |

**No new indexes added** — existing indexes on `throughput_snapshots (project_id, snapshot_date)`, `milestones (project_id)`, and governance partial indexes from `20260703120000_governance_active_partial_indexes.sql` are used; EXPLAIN did not justify additional indexes at current table sizes.

### Before / after timing (dev DB, delivery manager, cold cache cleared)

| Metric | Before | After (warm, runs 2–5) |
|--------|--------|-------------------------|
| `get_governance_analytics_summary` service | **787–870 ms** | **376–388 ms** |
| Per-query fan-out | 1 projects + 4 counts + 5 delivery = **10 round trips** | **2 round trips** |
| `serialization_ms` | <1 ms | ~1–2 ms (unchanged) |
| Cache hit (within 3 min TTL) | N/A | **<5 ms** |

**Note:** Consistent **<300 ms** on remote Supabase is not achievable with the current two-query design without accepting cache hits or moving DB closer to the API. The 3-minute in-process cache covers repeat dashboard visits within a session.

## Metrics to compare after each phase

Track the same fields from `governance_endpoint_timing` logs:

| Metric | Target direction | Phase comparison |
|--------|------------------|------------------|
| `total_ms` (p50 / p95) per endpoint | Down | Primary success metric |
| `db_ms` / `total_ms` ratio | Down if DB-bound | Confirms DB vs serialization work |
| `serialization_ms` | Stable or down | Catches mapping/payload regressions |
| Internal first-paint wall time | Down | Browser DevTools → Network: dependencies + bootstrap + analytics summary |
| Client first-paint wall time | Down | Network: escalations + bootstrap |
| `row_count` at fixed filters | Stable | Ensures optimizations did not truncate data |

Suggested acceptance checks per phase:

- Internal cold load: `analytics/summary` p95 < 450 ms (warm pool), `dependencies` p95 < 400 ms (cold) / <10 ms (cache hit), `bootstrap` p95 < 400 ms
- Client cold load: `escalations` p95 < 150 ms
- No increase in error rate on baseline endpoints (dependencies, escalations, bootstrap, analytics/summary)

## Related files

- Frontend load orchestration: `frontend/src/features/governance/GovernanceDashboard.tsx`
- Defer/idle gates: `frontend/src/features/governance/governance-load-strategy.ts`
- Query definitions: `frontend/src/lib/queries/governance.ts`
- Timing helper: `backend/app/agents/governance/timing.py`
- Timing tests: `backend/tests/test_governance_timing.py`

## Cleanup notes

**Cleanup Batch 1 (2026-07-06):** Removed the unmounted legacy governance API layer (`app/api/routes/governance.py`, `app/services/governance.py`, `app/agents/governance/dependencies.py`). These were not registered in `main.py` and formed an isolated import chain. The live router is `app.agents.governance.routes.governance`, mounted via `app.include_router(governance_routes.router, prefix=api_prefix)` in `main.py`.

**Cleanup Batch 2 (2026-07-06):** Removed unused frontend governance code: `WeeklySummaryPanel.tsx`, monolithic `getGovernanceAnalytics` / `governanceAnalyticsQueryOptions`, `useGovernanceBootstrapQuery`, deprecated list aliases in `governance.ts`, and weekly-summary query helpers/types with zero importers. Live `/governance` uses `governanceAnalyticsSummaryQueryOptions` + `governanceAnalyticsDetailQueryOptions` + `mergeGovernanceAnalytics`.

**Cleanup Batch 3 (2026-07-06):** Confirmed `GovernanceDashboardRead` / `GovernanceDashboardKpis` schema orphans were already absent from `app/schemas/domain.py` (removed with Batch 1 consumers). Deduplicated repeated model exports in `app/db/models/__init__.py`. Updated this doc to match the split analytics + bootstrap load strategy. Added deprecation TODO on monolithic `GET /governance/analytics` (route retained for backward compatibility).

**Cleanup validation (2026-07-06):** All three batches complete. Removed symbols/files have no live code references (only historical mentions in this doc). Live `/governance` flow confirmed on `governanceBootstrapQueryOptions`, `governanceAnalyticsSummaryQueryOptions`, `governanceAnalyticsDetailQueryOptions`, and `mergeGovernanceAnalytics`. Orphaned backend API layer and unused frontend weekly-summary/legacy analytics helpers are gone. Monolithic `GET /governance/analytics` kept temporarily for backward compatibility. Validation: `pytest tests/ -k governance` (73 passed), `npm test -- src/features/governance` (14 passed), `npm run build` (success).
