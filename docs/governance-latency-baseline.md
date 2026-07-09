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
| `GET /governance/bootstrap` | 343 | 342 | 0.1 | KPI strip + tab totals (pre-optimization; see Bootstrap endpoint profiling) |

Client user escalations (representative client org): **~60–120 ms** after connection warm-up.

Internal first-paint critical path (parallel requests): dominated by **analytics summary** + **dependencies** + **bootstrap**. Analytics detail loads progressively and does not block the initial shell.

## What to optimize first

1. **`GET /governance/analytics/summary`** — Re-benchmarked **~377 ms** warm (down from **~800–1100 ms**). Further wins require regional DB proximity or accepting cache hits; see Analytics summary endpoint profiling.
2. **`GET /governance/dependencies`** — Re-benchmarked **~349 ms** warm with **1 DB round trip** (down from **~375 ms** / 2 executes). 60 s in-process cache for default list; see Dependencies endpoint profiling.
3. **`GET /governance/bootstrap`** — Re-benchmarked **~357 ms** warm with **1 DB execute** (down from **~473 ms** / 3 executes). 3-min in-process cache; see Bootstrap endpoint profiling.
4. **`GET /governance/register`** — Not first paint, but expensive when users switch tabs; same class of multi-subquery aggregation as analytics.
5. **`GET /governance/analytics/detail`** — Progressive only; optimize after summary path is stable.

Defer: agent chat, charter generation, export endpoints, monolithic `GET /governance/analytics` — not on dashboard first paint.

## Dependencies endpoint profiling

**Endpoint:** `GET /governance/dependencies?limit=50&offset=0`  
**Handler:** `list_governance_dependencies` → `list_governance_dependencies_page` (`governance_service.py`)

### Query shape (default internal request, after 2026-07-07 paginate-then-join)

1. **Single paginated query** — `_dependency_enriched_page_stmt`:
   - Inner `dep_page_ids` subquery: `SELECT id FROM project_dependencies WHERE org_id = ? AND deleted_at IS NULL ORDER BY due_date NULLS LAST, created_at DESC LIMIT 50 OFFSET 0`
   - Scalar count subquery: `SELECT count(*) FROM project_dependencies WHERE …` (no joins)
   - Outer query joins **only the page rows** to `projects` (name) and `users` (owner display name)
   - Selects only list-table columns; no `description` or other heavy fields
2. **Count fallback** — separate lightweight `count(*)` only when the page is empty **and** `offset > 0`.
3. **Serialization** — `map_dependency_list_row` from row tuples (no ORM hydration).
4. **Cache** — 60-second in-process TTL for unfiltered default requests; invalidated on dependency CRUD.

Profiling log (when service `total_ms >= 200`):

```text
governance_dependencies_list_profile total_ms=358.3 db_executes=1 row_count=6 limit=50 offset=0 cached=false
```

### EXPLAIN ANALYZE — before vs after (dev DB, org `0ac27787-896c-49e4-b90a-616c13a3694e`, 6 active rows)

**Before (`count(*) OVER()` + join all rows):**

| Node | Observation |
|------|-------------|
| `Seq Scan` | On `project_dependencies` (planner choice at n=6; index used at scale with `enable_seqscan=off`) |
| `Nested Loop` | Join **all** org rows to `projects_pkey` + `users_pkey` before `Limit` |
| `WindowAgg` | `count(*) OVER()` scans full joined set |
| `Sort` | `due_date`, `created_at DESC` — eliminated at scale when index `project_dependencies_active_org_due_created_idx` is chosen |
| **Execution time** | **~0.15 ms** |

**After (paginate ids, then join page):**

| Node | Observation |
|------|-------------|
| `InitPlan` + `Aggregate` | Scalar `count(*)` — at scale uses `Index Only Scan` on `project_dependencies_active_org_id_idx` |
| `Subquery Scan on dep_page_ids` + `Limit` | Paginates ids first — at scale uses `project_dependencies_active_org_due_created_idx` |
| `Hash Join` | Joins only page rows (≤50) to full dependency row |
| `Nested Loop` | `projects_pkey` + `users_pkey` on **page rows only** (not entire org) |
| `Sort` | Small final re-sort of page rows |
| **Execution time** | **~1.0 ms** at n=6 (extra hash join overhead); **wins at scale** by avoiding per-row joins on full org set |

**Indexes evaluated (not added):**

| Proposed | Verdict |
|----------|---------|
| `(org_id, deleted_at, created_at DESC)` | **Rejected** — `deleted_at` redundant with partial index `WHERE deleted_at IS NULL`; `created_at` alone does not match `ORDER BY due_date, created_at DESC` |
| `(org_id, project_id, deleted_at, created_at DESC)` | **Rejected** — `project_id` filter uses existing `project_dependencies_project_id_idx`; sort key is `due_date` first |
| `(org_id, status, deleted_at, created_at DESC)` | **Rejected** — existing `project_dependencies_active_org_status_due_project_idx` covers status-filtered open/blocking queries; general sort still needs `due_date` before `created_at` |

**Existing indexes used at scale** (`enable_seqscan=off` simulation):

- `project_dependencies_active_org_due_created_idx` — default list `ORDER BY due_date NULLS LAST, created_at DESC`
- `project_dependencies_active_org_id_idx` — scalar count (`Index Only Scan`)

Migration: `supabase/migrations/20260706143000_governance_dependencies_list_index.sql` (already applied). **No new indexes added.**

### Before / after timing (dev DB, delivery manager, cache cleared each run)

| Metric | Before window-count | After paginate-then-join |
|--------|---------------------|--------------------------|
| `list_governance_dependencies_page` warm | **355–419 ms** | **349–368 ms** |
| DB executes (default page) | **1** | **1** |
| `serialization_ms` | ~1–2 ms | ~1–2 ms |
| Cache hit (60 s TTL) | **<5 ms** | **<5 ms** |

**Finding:** SQL CPU is negligible on dev DB (<1 ms). End-to-end latency is dominated by **one Supabase round trip (~350 ms)**. The paginate-then-join change prevents join fan-out from growing with org dependency volume; cold latency is network-bound.

## Bootstrap endpoint profiling

**Endpoint:** `GET /governance/bootstrap`  
**Handler:** `governance_bootstrap` → `get_governance_bootstrap` (`dashboard_service.py`)

### Query shape (after 2026-07-07 optimization)

**Internal users** (`delivery_manager`, `bsg_leadership`, `super_admin`) — **one DB execute** combining:

1. **Action KPIs** — conditional `count(*) FILTER (...)` on `governance_actions` (open, overdue, SLA on-time/total for 90-day window).
2. **Inventory KPIs** — scalar subqueries on `project_dependencies` (blocking) and `project_scope_states` (pending revision).
3. **Escalation KPIs** — conditional `count(*) FILTER (...)` on `governance_escalations` (open + high/critical).

**Client users** — **one DB execute**: escalation aggregates scoped via `project_id IN (SELECT … FROM project_assignments WHERE user_id = ?)`.

No list payloads, no joins for enrichment, no weekly summaries or charters. Response is KPI counts only (`GovernanceBootstrapRead.kpis`); legacy list fields remain empty defaults.

Profiling log (when KPI compute `total_ms >= 150`):

```text
governance_bootstrap_profile total_ms=357.2 db_executes=1 role=delivery_manager org_id=...
```

### DB execute count comparison

| Role | Before | After |
|------|--------|-------|
| Internal (DM/leadership) | **3** sequential executes | **1** |
| Client | **2** (assignments + escalations) | **1** |
| Cache hit (3 min TTL) | 0 | **0** (<5 ms) |

### EXPLAIN ANALYZE summary (dev DB)

| Component | Plan highlight | SQL execution time |
|-----------|----------------|-------------------|
| Combined KPI select | Independent scalar subqueries / aggregate subqueries; no row fan-out | **<2 ms** |

**Finding:** SQL CPU is negligible. Warm latency is dominated by **one Supabase round trip (~357 ms)**. Prior path used three sequential round trips (~473 ms warm).

### Before / after timing (dev DB, delivery manager, cache cleared each run)

| Metric | Before (docs baseline) | Before (re-benchmark) | After |
|--------|------------------------|----------------------|-------|
| `get_governance_bootstrap` warm | ~343 ms | **~473 ms** | **~357 ms** |
| DB executes (internal) | 3 | 3 | **1** |
| `serialization_ms` | ~0.1 ms | ~0.1 ms | ~0.1 ms |
| Cache hit (3 min TTL) | <5 ms | <5 ms | <5 ms |

**Note:** Target 150–200 ms on cold load is not achievable on remote Supabase with a single round trip at ~357 ms. The existing 3-minute in-process cache covers repeat dashboard visits.

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

## Register endpoint profiling

**Endpoint:** `GET /governance/register?limit=25&offset=0`  
**Handler:** `list_governance_register` → `list_governance_register_page` (`register_service.py`)

### Summary table (`project_governance_summary`)

Precomputed per-project counts for register badges. Migrations:

- `supabase/migrations/20260704120000_project_governance_summary.sql` — table + backfill
- `supabase/migrations/20260707100000_project_governance_summary_org_updated_idx.sql` — `(org_id, updated_at)` for stale-row lookup

| Column | Register UI field |
|--------|-------------------|
| `open_dependencies_count` | `open_dependencies` |
| `blocked_dependencies_count` | `blocking_dependencies` |
| `blocking_overdue_dependencies_count` | health (red) |
| `open_actions_count` | `open_actions` |
| `overdue_actions_count` | health (amber) |
| `open_escalations_count` | `open_escalations` |
| `critical_escalations_count` | health (red) |
| `pending_scope_changes_count` | (not exposed; scope from `project_scope_states`) |

Write paths call `refresh_project_governance_summary` on dependency/action/escalation/scope CRUD (and delivery-integration escalations). Paginated register rows still come from `projects` + `project_scope_states`; counts are read from the summary table (no live `GROUP BY` on governance source tables).

### Query shape (internal user, after optimization)

1. **Date rollover (0–1 round trips)** — `ensure_org_time_sensitive_summary_counts`: in-process “refreshed today” cache; otherwise `EXISTS` stale rows, then one combined overdue-actions + blocking-overdue-deps aggregate when the UTC day rolled over. Skipped when `org_id` is null (super admin).
2. **Register page (1 round trip)** — `projects` ⋈ scoped visible projects ⋈ `project_scope_states` ⋈ `project_governance_summary` with `count(*) OVER()` pagination. Client scoping uses embedded `scoped_project_query` assignment filter (no extra assignments query).

Profiling log (when `total_ms >= 200`):

```text
governance_register_list_profile total_ms=414.0 db_executes=2 row_count=19 limit=25 offset=0 cached=false
```

### Before / after timing (dev DB, delivery manager org `0ac27787-896c-49e4-b90a-616c13a3694e`, cache cleared)

| Metric | Before | After (cold, runs 2–5) | After (cache hit) |
|--------|--------|------------------------|-------------------|
| `list_governance_register_page` | **~403 ms** | **407–419 ms** | **<1 ms** |
| DB executes (internal DM) | **2–4** (stale-day refresh + page; client +1 assignments) | **2** | **0** |
| Live aggregation on read | None (summary table already wired) | None | None |
| `serialization_ms` | ~0.1 ms | ~0.1 ms | ~0 ms |

**Finding:** End-to-end latency remains dominated by **two Supabase round trips** (~200 ms each). The summary table prevents register cost from growing with dependency/action/escalation row volume; counts are O(1) per project at read time. A 60-second in-process cache covers repeat Register tab visits within a session.

### Optimizations applied (2026-07-07)

| Change | Rationale | Effect |
|--------|-----------|--------|
| `project_governance_summary` table + write-path refresh | Precompute counts; avoid read-time `GROUP BY` as data grows | Stable per-page read cost |
| In-process org day cache + `EXISTS` stale check | Skip 1–3 rollover queries on repeat reads same UTC day | Fewer round trips on tab revisits |
| Combined overdue + blocking-overdue aggregate on rollover | 2 queries → 1 on day boundary | Faster midnight rollover |
| Single-query `compute_project_governance_counts` on write | 4 executes → 1 per mutation refresh | Faster write-path summary updates |
| Remove redundant `_client_project_ids` on register read | `scoped_project_query` already embeds assignment filter | −1 round trip for clients |
| `count(*) OVER()` pagination | Already shared with dependencies | 1 execute for page + total |
| 60 s register list cache + invalidation on summary refresh | Repeat tab loads | **<1 ms** cache hits |
| Index `(org_id, updated_at)` | Stale-summary lookup | Supports `EXPLAIN` index scan at scale |

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
