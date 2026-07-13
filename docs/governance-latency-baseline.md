# Governance Page Latency Baseline

**Phase 0 re-baseline — measurement only (2026-07-10).**  
No production behavior, SQL, cache eligibility, API contracts, or frontend load-order changes in this phase.

Use this document to compare later optimization phases against the **same request shapes the production frontend actually sends**.

## Environment

| Field | Value |
|-------|-------|
| Date | 2026-07-10 |
| Environment | Local API + remote Supabase **dev** database |
| API region | Developer workstation (not co-located with DB) |
| Database | Supabase Postgres via `DATABASE_URL` pooler (`*.supabase.co` / `pooler.supabase.com`) |
| API ↔ DB co-located? | **No** — remote RTT dominates warm single-query latency (~150–350 ms per round trip) |
| Connection pool | Supabase pooler: **NullPool** (transaction mode port 6543 preferred; session mode 5432 capped at 4 concurrent sessions). See `backend/app/db/session.py` |
| Org under test | `0ac27787-896c-49e4-b90a-616c13a3694e` |
| Benchmark script | `backend/scripts/benchmark_governance_latency_baseline.py` |

Re-run:

```bash
cd backend
python scripts/benchmark_governance_latency_baseline.py
```

## Frontend request shapes (production)

Constants:

| Constant | Value | Source |
|----------|-------|--------|
| `TABLE_PAGE_SIZE` | `6` | `GovernanceDashboard.tsx` |
| `GOVERNANCE_DEFAULT_TABLE_PARAMS` | `{ limit: 6, offset: 0 }` | `governance-prefetch.ts` |
| `GOVERNANCE_DEFAULT_ANALYTICS_DAYS` | `30` | `governance-prefetch.ts` |
| `GOVERNANCE_ANALYTICS_DEFER_MS` | `200` | `governance-load-strategy.ts` |
| `GOVERNANCE_ANALYTICS_DETAIL_IDLE_MS` | `400` | `governance-load-strategy.ts` |

Exact first-page / progressive parameters:

| Request | Method / path | Parameters |
|---------|---------------|------------|
| Bootstrap | `GET /governance/bootstrap` | (none) |
| Dependencies first page | `GET /governance/dependencies` | `limit=6&offset=0` (+ optional filters when set) |
| Escalations first page | `GET /governance/escalations` | `limit=6&offset=0` |
| Register first page | `GET /governance/register` | `limit=6&offset=0` (Register tab only) |
| Actions first page | `GET /governance/actions` | `limit=6&offset=0` (Actions tab only) |
| Analytics summary | `GET /governance/analytics/summary` | `days=30` |
| Analytics detail | `GET /governance/analytics/detail` | `days=30` |

**Important:** Older docs and some backend caches assumed `limit=50`. The live dashboard first page is **`limit=6`**.

## Current loading sequence

Route: `/governance` → lazy `GovernanceDashboard`.

### Internal users (`delivery_manager`, `bsg_leadership`, `super_admin`)

| Order | React Query | HTTP | Blocks first paint? |
|------|-------------|------|---------------------|
| 1 | `governanceBootstrapQueryOptions` | `GET /governance/bootstrap` | Partial — KPI strip |
| 1 | `governanceDependenciesQueryOptions({limit:6,offset:0})` | `GET /governance/dependencies?limit=6&offset=0` | Yes — default Dependencies tab |
| 2 (after 200 ms) | `governanceAnalyticsSummaryQueryOptions(30)` | `GET /governance/analytics/summary?days=30` | Partial — executive header |
| 3 (idle / in-view) | `governanceAnalyticsDetailQueryOptions(30)` | `GET /governance/analytics/detail?days=30` | No — progressive |

Nav prefetch (`prefetchGovernanceRouteData`) warms bootstrap, dependencies `limit=6`, and analytics summary `days=30` **concurrently** (no detail). See Phase 2.

**Not on first load:** register, actions, scope states, delivery portfolio, users, charters, agent chat, monolithic `GET /governance/analytics`.

### Client users (`client`)

| Order | React Query | HTTP | Blocks first paint? |
|------|-------------|------|---------------------|
| 1 | `governanceBootstrapQueryOptions` | `GET /governance/bootstrap` | Partial — KPI strip |
| 1 | `governanceEscalationsQueryOptions({limit:6,offset:0})` | `GET /governance/escalations?limit=6&offset=0` | Yes — default Escalations tab |

**Skipped for clients:** dependencies, actions, analytics summary/detail, register (unless they switch tabs where allowed).

### Lazy-loaded on tab or interaction

| Trigger | Endpoint |
|---------|----------|
| Register tab | `GET /governance/register?limit=6&offset=0` |
| Actions tab | `GET /governance/actions?limit=6&offset=0` |
| Register + delivery context | `GET /delivery/portfolio` |
| Project sheet | Re-fetch lists with `project_id`; internal also `GET /governance/scope-states?limit=1` |
| Charters sub-tab | `GET /governance/project-charters` |
| Create/edit dialog | `GET /users` |

## Backend timing instrumentation

All governance routes are wrapped by `instrument_governance_routes()` (`backend/app/agents/governance/timing.py`).

Log line (fields present when recorded):

```text
governance_endpoint_timing endpoint=GET /governance/dependencies role=delivery_manager org_id=<uuid> row_count=6 total_ms=358.3 db_ms=356.0 serialization_ms=2.3 execute_count=1 cache_hit=false limit=6 offset=0
```

| Field | Always? | Notes |
|-------|---------|-------|
| `total_ms` | Yes | Full handler time |
| `db_ms` | Yes | Time inside `governance_db_section` / `@governance_db_timed` |
| `serialization_ms` | Yes | `total_ms - db_ms` |
| `row_count` | Yes | List length or `1`/`0` for data payloads |
| `limit` / `offset` | When query params present | Captured from handler kwargs |
| `execute_count` | When service records it | Bootstrap, dependencies, escalations, register, analytics summary |
| `cache_hit` | When service records it | Same endpoints; analytics detail now records hit/miss and execute count |

**Do not log:** access tokens, PII, raw user IDs beyond role/org already present, sensitive filter values, full cache keys.

### Instrumentation gaps (Phase 0)

| Gap | Status |
|-----|--------|
| Analytics **detail** exact `execute_count` | Not recorded — path fans out across many helpers; only `cache_hit` is reliable |
| Dependencies / register **production** `limit=6` cache | **Not eligible** under current rules (deps require `limit=50`; register requires `limit ∈ {25,50}`) — documented, not changed |
| Escalations list cache | None today |
| Route-level fields without service `record_meta` | `execute_count` / `cache_hit` omitted (limit/offset still logged) |

## Cache eligibility vs frontend shapes (unchanged in Phase 0)

| Endpoint | Frontend first-page shape | Currently cacheable? | TTL |
|----------|---------------------------|----------------------|-----|
| Bootstrap | no params | Yes (per org/role/user) | 3 min |
| Dependencies | `limit=6` | **No** (eligibility still `limit=50`) | 60 s (legacy shape only) |
| Escalations | `limit=6` | **No** | — |
| Register | `limit=6` | **No** (eligibility `{25,50}`) | 60 s (legacy shapes only) |
| Analytics summary | `days=30` | Yes | 3 min |
| Analytics detail | `days=30` | Yes | 3 min |

> **Phase 1 update:** dependencies and register `limit=6` are now cache-eligible. See [Phase 1](#phase-1--first-page-cache-eligibility-limit6). Phase 0 numbers above are preserved for comparison.

## Measured baseline (dev DB)

Captured **2026-07-10** via `benchmark_governance_latency_baseline.py` against the live Supabase dev database (session pooler port 5432, NullPool, concurrency cap 4).  
API on developer workstation — **not** co-located with DB. First cold sample dropped from warm-pool averages where noted. Remote RTT on this run was higher than the earlier ~350 ms historical samples (~800–1100 ms per round trip).

### Internal path

| Endpoint | Shape | Cold cache / warm pool | Immediate repeat | Cache hit | DB executes (miss) | Rows |
|----------|-------|------------------------|------------------|-----------|--------------------|------|
| `GET /governance/bootstrap` | — | avg **860** ms (p95 **904**, n=4) | **~0.1** ms (cache) | **~0.1** ms | **1** | 1 |
| `GET /governance/dependencies` | **`limit=6`** | avg **846** ms (p95 **877**, n=4) | avg **843** ms (still miss) | **N/A** (ineligible) | **1** | 6 |
| `GET /governance/analytics/summary` | `days=30` | avg **1112** ms (p95 **1145**, n=4) | **~0.1** ms (cache) | **~0.1** ms | **2** | 8 ranking |
| `GET /governance/analytics/detail` | `days=30` | avg **3818** ms (p95 **3997**, n=4) | **~0.1** ms (cache) | **~0.1** ms | many (exact count not instrumented) | — |
| `GET /governance/register` | **`limit=6`** | avg **1451** ms (p95 **1542**, n=4; **4** executes incl. day rollover) | avg **846** ms (**1** execute; still miss) | **N/A** (ineligible) | **4** cold / **1** warm day | 6 |

### Client path

Synthetic client user in the same org (no project assignments in this run → escalations empty page after assignments lookup).

| Endpoint | Shape | Cold cache / warm pool | Immediate repeat | Cache hit | DB executes (miss) | Rows |
|----------|-------|------------------------|------------------|-----------|--------------------|------|
| `GET /governance/bootstrap` | — | avg **841** ms (p95 **863**, n=4; first cold **1879** ms) | **~0.1** ms (cache) | **~0.1** ms | **1** | 1 |
| `GET /governance/escalations` | **`limit=6`** | avg **633** ms (p95 **655**, n=4) | avg **662** ms (no list cache) | **N/A** | **1** (no assigned projects) | 0 |

Re-run with a real assigned client identity before treating client escalations as production-representative.

Do **not** assume client and internal paths share SQL or cache behavior.

### Cold vs warm vs cache

| Mode | Meaning |
|------|---------|
| A / B | In-process caches cleared; first request(s) after warm `SELECT 1` |
| C | Immediate repeated request without clearing caches (cache hit if eligible; still a miss if shape ineligible) |
| D | Warm DB / pool — all scripted runs after an initial `SELECT 1` |
| E | In-process cache hit where eligibility applies |

### Main latency contributors (current system)

1. **Remote Supabase RTT** — SQL CPU is typically <10 ms; this run saw ~800–1100 ms per round trip from a non-colocated API (historical samples were ~150–350 ms under better network conditions).
2. **Analytics summary** — 2 round trips (~1112 ms cold) on the deferred internal path.
3. **Bootstrap + dependencies** — 1 round trip each on internal first paint; dependencies `limit=6` never hits the 60 s cache today (~846 ms every request).
4. **Analytics detail** — ~3.8 s cold progressive fan-out; cacheable after first load.
5. **Register** — cold day-rollover can cost **4** executes (~1450 ms); warm-day page is **1** execute but still uncached at `limit=6`.
6. **Client escalations** — no list cache; assignment-scoped SQL differs from internal.
## Current success targets (unchanged goals for later phases)

Track the same fields from `governance_endpoint_timing` / the baseline script:

| Metric | Target direction |
|--------|------------------|
| `total_ms` (p50 / p95) per endpoint | Down |
| `db_ms` / `total_ms` | Down if DB-bound |
| `serialization_ms` | Stable or down |
| Internal first-paint wall time | Down (bootstrap + dependencies `limit=6` + deferred summary) |
| Client first-paint wall time | Down (bootstrap + escalations `limit=6`) |
| `row_count` at fixed filters | Stable |
| `execute_count` | Down or stable; never silently increase |

Suggested acceptance checks (later phases):

- Internal cold: `analytics/summary` p95 < 450 ms (warm pool), `dependencies?limit=6` p95 < 400 ms (cold) / <10 ms once cache eligibility matches frontend, `bootstrap` p95 < 400 ms
- Client cold: `escalations?limit=6` p95 < 150 ms (when data/org allow)
- No increase in error rate on baseline endpoints

## How to capture logs locally

1. Start the API: `backend/run_dev_server.ps1`
2. Open `/governance` as an internal user and as a client user (hard refresh).
3. Grep backend stdout for `governance_endpoint_timing`.

## Related files

- Frontend load orchestration: `frontend/src/features/governance/GovernanceDashboard.tsx`
- Prefetch: `frontend/src/features/governance/governance-prefetch.ts`
- Defer/idle gates: `frontend/src/features/governance/governance-load-strategy.ts`
- Query definitions: `frontend/src/lib/queries/governance.ts`
- Timing helper: `backend/app/agents/governance/timing.py`
- Baseline script: `backend/scripts/benchmark_governance_latency_baseline.py`
- Timing tests: `backend/tests/test_governance_timing.py`

## Phase 0 confirmation

- Baseline parameters match production frontend traffic (`limit=6`, analytics `days=30`).
- Cold / warm / cache-hit measurements are separated in the benchmark script and this doc.
- DB execute counts are visible for bootstrap, dependencies, escalations, register, and analytics summary.
- Internal and client paths are documented separately.
- **No optimization** was introduced: no Redis, no SQL changes, no cache-eligibility changes, no API contract changes, no frontend load-order changes.

## Phase 1 — First-page cache eligibility (`limit=6`)

**Date:** 2026-07-10 (same environment as Phase 0).  
**Goal:** Make repeated unfiltered first-page requests hit the existing in-process cache instead of paying another remote RTT.

### Eligibility before → after

| Endpoint | Before | After |
|----------|--------|-------|
| Dependencies | `limit=50` only | **`limit ∈ {6, 50}`**, offset=0, unfiltered |
| Register | `limit ∈ {25, 50}` | **`limit ∈ {6, 25, 50}`**, offset=0, unfiltered |
| Actions | none | **Deferred to Phase 5** (no existing list cache) |
| Escalations | none | **Deferred to Phase 5** (client assignment-scoped; needs permission-aware cache) |

Constant: `GOVERNANCE_FIRST_PAINT_LIMIT = 6` in `backend/app/agents/governance/constants.py` (must stay aligned with frontend `TABLE_PAGE_SIZE`).

### Cache key dimensions

| Cache | Key | Isolation |
|-------|-----|-----------|
| Dependencies | `(org_id\|None, role, user_id, limit, offset)` | Per-user; clients never populate (empty early return). Internal rows are org-scoped. |
| Register | `(org_id\|None, role, user_id, limit, offset)` | Per-user; clients use assignment-scoped `scoped_project_query`. |

Safe log fields: `cache_scope=user_access`, `cache_shape=first_paint_unfiltered|legacy_first_page|uncached_*`, `cache_eligible`, `cache_hit`, `filtered`, `execute_count`, `limit`, `offset`.

### Invalidation (after successful commit)

`invalidate_governance_read_caches_after_commit()` clears **both** dependencies and register list caches after:

- dependency create / update / resolve / soft-delete
- escalation create / update / soft-delete
- action create / update / soft-delete
- scope-state update
- delivery risk → escalation promote

Day-rollover summary refresh (`ensure_org_time_sensitive_summary_counts`) is unchanged; register list cache is no longer cleared inside `refresh_project_governance_summary` (moved to post-commit to avoid stale re-population races).

### Before / after measurements (2026-07-10)

Remote RTT remains ~800–1100 ms on miss.

| Endpoint | Metric | Phase 0 | Phase 1 |
|----------|--------|---------|---------|
| Dependencies `limit=6` | miss avg | ~846 ms / **1** exec | ~833 ms / **1** exec |
| Dependencies `limit=6` | cache hit | **N/A** (ineligible) | **~0.6 ms / 0 exec** |
| Register `limit=6` | cold (day rollover) | ~1451 ms / **4** exec | ~1436 ms / **4** exec |
| Register `limit=6` | cache hit | **N/A** (ineligible) | **~0.1 ms / 0 exec** |

### Deferred from Phase 1

- Actions first-page cache (no prior infrastructure)
- Escalations first-page cache (assignment-scoped; synthetic Phase 0 client had 0 rows)
- Analytics SQL / execute-count instrumentation for detail
- Day-rollover 4-execute register path
- Frontend prefetch order

### Phase 1 confirmation

- No Redis, no API contract changes, no analytics SQL changes, no frontend load-order changes.
- Legacy `limit=50` (deps) and `limit ∈ {25,50}` (register) remain cacheable.
- Governance tests: **113 passed**.

## Phase 2 — Concurrent Governance route prefetch

**Date:** 2026-07-10.  
**Goal:** On Governance sidebar hover, start eligible first-paint queries together inside the Governance bundle, while keeping cross-agent single-flight in `nav-prefetch.ts`.

### Previous call chain

```
Shell onMouseEnter
  → scheduleNavPrefetch(/governance) [450 ms linger]
  → runPrefetch (abort other agent; one flight)
  → prefetchGovernanceNav
  → await bootstrap
  → await dependencies limit=6
  → await analytics summary days=30
```

Internal hover was a **sequential waterfall** of up to ~3 remote RTTs (~2.4–3.3 s in the Phase 0/1 environment).

### New call chain

```
Shell onMouseEnter
  → scheduleNavPrefetch(/governance) [450 ms linger; unchanged]
  → runPrefetch (cross-agent single-flight unchanged)
  → prefetchGovernanceNav
  → Promise.allSettled([
        bootstrap,
        dependencies limit=6   // internal
        OR escalations limit=6 // client
        analytics summary days=30 // internal only
     ])
```

Module chunk prefetch (`import("./GovernanceDashboard")`) still starts immediately alongside the data bundle.

### Internal-user prefetch tasks

1. `governanceBootstrapQueryOptions`
2. `governanceDependenciesQueryOptions({ limit: 6, offset: 0 })`
3. `governanceAnalyticsSummaryQueryOptions(30)`

Not prefetched: analytics detail, register, actions, portfolio, projects, users, charters, chat.

### Client-user prefetch tasks

1. `governanceBootstrapQueryOptions`
2. `governanceEscalationsQueryOptions({ limit: 6, offset: 0 })`

Not prefetched: dependencies, analytics summary/detail.

Role is resolved from the optional argument or `useAuthStore.getState().user?.role`.

### Cross-agent single-flight preserved

`nav-prefetch.ts` still enforces:

- 450 ms hover linger
- one active agent path at a time (switching aborts the previous controller)
- same-route in-flight reuse (`path === activePath`)
- 2.5 s same-route cooldown after successful completion

Only queries **inside** the Governance bundle are parallelized.

### Query-key reuse

Prefetch calls the same factories as `GovernanceDashboard`:

- `GOVERNANCE_DEFAULT_TABLE_PARAMS` / `GOVERNANCE_DEFAULT_ANALYTICS_DAYS`
- Dashboard `TABLE_PAGE_SIZE` and default analytics days now import those constants

Mounted 200 ms summary defer remains for click-without-hover. Hover bypasses that defer by warming the summary query early; mount reuses cache/in-flight data.

### Failure behavior

- Tasks run under `Promise.allSettled`
- Abort still throws `AbortError` for nav-prefetch
- Partial failures do not fail the bundle
- All-task failure rethrows so nav-prefetch can log and skip cooldown
- Navigation is never blocked (prefetch is fire-and-forget from Shell)

### Expected timing (remote RTT ~800–1100 ms)

| Scenario | Before Phase 2 | After Phase 2 |
|----------|----------------|---------------|
| Internal hover cold | ~sum of 3 RTTs (waterfall) | ~max(bootstrap, deps, summary) overlapping envelope |
| Client hover cold | ~sum of 2 RTTs | ~max(bootstrap, escalations) |
| Hover then click (fresh) | may refetch if keys differed | reuses React Query cache / in-flight |
| Click without hover | summary after 200 ms defer | **unchanged** |

Duplicate request count on hover→click with matching keys: **0** while queries remain fresh/in-flight (React Query dedupe).

### Tests

- Concurrency: deferred bootstrap does not block deps/summary (or escalations) from starting
- Client branch excludes deps/summary
- Failure / abort paths
- Nav single-flight, cooldown, in-flight reuse

### Browser Network validation

Automated unit tests prove concurrent `prefetchQuery` starts (deferred-promise pattern). Live DevTools Network overlap should be confirmed manually:

| Scenario | Expected |
|----------|----------|
| Internal hover 500–1000 ms | bootstrap, deps `limit=6`, summary `days=30` overlap; no detail |
| Hover then click in-flight | no duplicate bootstrap/deps/summary |
| Hover until complete then click | shell from React Query cache; no immediate refetch while fresh |
| Click without hover | summary still waits ~200 ms defer |
| Client hover | bootstrap + escalations only |
| Repeated hover | single-flight / cooldown suppress uncontrolled duplicates |

### Phase 2 confirmation

- No Redis, no backend cache/SQL changes, no API contract changes
- Analytics detail not prefetched
- Cross-agent single-flight intact

## Phase 3 — Analytics summary single-execute

**Date:** 2026-07-10.  
**Goal:** Reduce `GET /governance/analytics/summary` from **2 sequential DB executes** to **1** on cache miss, without changing the public response or business rules.

### Previous summary query flow

```
get_governance_analytics_summary
  → cache lookup (org_id|None, role, user_id, days)
  → execute #1: _summary_project_metrics_stmt
       (visible projects + dep/esc/overdue/scope aggs)
  → execute #2: GOVERNANCE_SIGNAL_BUNDLE_SQL
       (throughput/quality/milestone/risk/bottleneck UNION)
  → Python score → top 8 ranking → cache store
```

Phase 0 cold miss: ~1112 ms, **execute_count=2**.

### New unified query flow

```
get_governance_analytics_summary
  → cache lookup (unchanged key)
  → execute #1: _summary_unified_sql
       WITH visible_projects
            summary_dep_agg / summary_esc_agg / summary_overdue_agg / summary_scope_agg
            signal_bundle + signals_agg (internal only; jsonb_agg per project)
       SELECT one row per visible project + scalar metrics + delivery_signals JSON
  → Python parse signals → same scoring / ranking / charts
  → cache store
```

Clients / non-internal: same single statement **without** signal CTEs (signals were already skipped before the second execute).

### Execute counts

| Path | Before | After |
|------|--------|-------|
| Cache miss | 2 | **1** |
| Cache hit | 0 | **0** |

No multi-session fan-out; no `asyncio.gather` for summary DB work.

### EXPLAIN ANALYZE (representative org, days irrelevant to SQL)

Against remote Supabase for the unified statement (`include_signals=true`):

- Planning Time: ~1.9 ms
- Execution Time: ~5.2 ms
- Plan: CTE `visible_projects` (Seq Scan on small `projects` set) + independent aggregate Hash Left Joins + signal UNION/`row_number` Append + `jsonb_agg`
- SQL time remains << remote RTT; no new index added

### Benchmark (2026-07-10, same remote environment)

| Metric | Phase 0 (2 executes) | Phase 3 (1 execute) |
|--------|----------------------|---------------------|
| Cache miss avg | ~1112 ms | ~1300–1490 ms (session variance; first cold ~2.0 s) |
| Cache miss execute_count | 2 | **1** |
| Cache hit | ~0.1 ms / 0 executes | ~0.2 ms / 0 executes |

Interpretation: removing one remote round trip is the structural win. Absolute miss latency remains dominated by a single remote RTT (~800–1100 ms+). This session’s miss samples were not faster than Phase 0’s recorded average (network variance); the acceptance criterion is **one execute** and a one-RTT envelope rather than a hard sub-450 ms p95 on this non-colocated setup.

### Response contract

`GovernanceAnalyticsSummaryRead` fields unchanged. Contract tests assert full serialized field sets for summary and health rows.

### Visible-project scoping

Unified SQL mirrors `scoped_project_query`:

- soft-deleted projects excluded
- super_admin: all non-deleted
- DM / leadership: org-scoped
- client: org + active assignment

Org filters on aggregate CTEs match `_apply_org_filter`.

### Delivery-signal selection

Same UNION semantics as `GOVERNANCE_SIGNAL_BUNDLE_SQL` (shared via `governance_signal_bundle_select_sql`):

- throughput: `row_number()` by `snapshot_date DESC`, keep ≤7
- quality: latest by `created_at DESC`
- milestones / open risks: matching rows
- bottlenecks: `count(*)` per project, expanded in Python

Signals are JSON-aggregated **after** independent CTEs so one-to-many signal rows cannot inflate governance counts.

### Cache

- Key still `(org_id|None, role, user_id, days)`; TTL 3 minutes
- **Write invalidation:** still TTL-only (not cleared by `invalidate_governance_read_caches_after_commit`, which covers deps + register only)
- Follow-up: optional analytics cache invalidation on governance writes

### 200 ms frontend defer recommendation

**Keep 200 ms** for now.

Even with one execute, remote RTT remains ~800–1100 ms, so summary is still expensive relative to first-paint table data. Prefetch already warms summary on hover; the mount defer still protects cold click-without-hover. Revisit only after measured miss latency is consistently well below one full RTT envelope in production-like conditions.

### Remaining work

- Analytics **detail** still multi-query / progressive (out of scope)
- Register day-rollover (deferred)
- Analytics write invalidation (follow-up)

### Phase 3 confirmation

- No Redis, no API schema change, no frontend defer/prefetch change
- No analytics-detail refactor
- Legacy two-query helper retained as `_fetch_summary_metric_bundle_two_query` for equivalence tests only

## Phase 4 - Analytics detail two-execute miss path

**Date:** 2026-07-13.  
**Goal:** Reduce `GET /governance/analytics/detail?days=30` from many sequential
service-level database executes to no more than two executes on cache miss, while keeping the
detail payload progressive and off first paint.

### Previous detail query flow

Before Phase 4, a representative internal cache miss used **19 service-level executes** inside
`get_governance_analytics_detail`:

```
1  _fetch_visible_projects
2  _fetch_dependency_counts_by_project
3  _fetch_escalation_counts_by_project
4  _fetch_overdue_action_counts_by_project
5  _fetch_pending_scope_counts_by_project
6  fetch_governance_delivery_signals / GOVERNANCE_SIGNAL_BUNDLE_SQL
7  _fetch_blocking_dependencies
8  _fetch_critical_escalations
9  _fetch_trend_dependencies
10 _fetch_trend_escalations
11 _fetch_trend_actions
12 _fetch_trend_scopes
13 _fetch_enum_counter(project_dependencies.dependency_type)
14 _fetch_enum_counter(governance_escalations.severity)
15 _fetch_action_status_counter
16 _fetch_overdue_actions
17 _fetch_recent_activity dependencies branch
18 _fetch_recent_activity actions branch
19 _fetch_recent_activity escalations branch
```

The `_fetch_project_evidence` helper did not add two extra executes in the live detail path because
blocking dependencies and critical escalations were already passed in. It would still execute twice
if called independently without those rows.

### New detail architecture

`get_governance_analytics_detail` now uses exactly two bundled statements on cache miss:

1. `_fetch_detail_project_bundle` reuses the Phase 3 visible-project aggregate SQL without delivery
   signal CTEs. It returns visible projects plus per-project dependency, escalation, overdue-action,
   and pending-scope counts.
2. `_fetch_detail_second_bundle` returns all rows needed for detail-only sections:
   trend source rows, chart counters, blocking-dependency evidence rows, critical-escalation evidence
   rows, overdue actions, recent activity, and delivery-signal input rows.

Python response construction still uses the existing scoring, insight, recommendation, trend, chart,
and evidence builders. No production dual path was kept.

### Visible-project scoping

Both statements use a shared `visible_projects` CTE equivalent to `scoped_project_query`:

- soft-deleted projects excluded
- super_admin: all non-deleted projects
- delivery manager / leadership: org-scoped projects
- client: org-scoped projects with active, non-deleted assignment

All bundled governance source CTEs join through `visible_projects`, preventing hidden broad org scans
and preserving user/access isolation.

### Trend and activity design

Trend sources are bundled as CTEs and returned as typed JSON payloads:

- dependencies: open rows plus rows created or resolved within the selected window
- escalations: open/in-progress rows plus rows raised or resolved within the selected window
- actions: non-completed rows plus rows created or completed within the selected window
- scope states: pending-revision rows plus rows updated within the selected window

The existing `_build_trends` function still zero-fills `days=7/30/90/365` buckets and preserves the
current date-bucket rules.

Recent activity is now a `UNION ALL` over dependency, action, and escalation branches. Each branch
keeps its previous top-8 local limit. Python then applies the same global top-8 ordering by timestamp,
with a deterministic source-order tie-breaker matching the old append order: dependency, action,
escalation.

### Row-multiplication and N+1 prevention

The bundled SQL never joins raw dependencies, actions, escalations, scope states, and signals together
in one unaggregated row set. It uses independent CTEs and `UNION ALL` payload sections, so one-to-many
tables cannot inflate counts. Project names and display labels are returned in the same bundled rows;
there are no per-row project/owner enrichment queries.

### Execute counts

| Path | Before | After |
|------|--------|-------|
| Cache miss | 19 service executes in the representative internal path | **2** |
| Cache hit | 0 | **0** |

Timing metadata now records `execute_count`, `cache_hit`, `activity_row_count`,
`trend_bucket_count`, and `project_row_count` for detail requests.

### Cache

- Cache key remains `(org_id|None, role, user_id, days)`
- TTL remains 3 minutes
- Cache hit performs zero service-level executes and records `execute_count=0`
- Write invalidation remains TTL-only; analytics invalidation is still a follow-up phase

### Response contract and tests

Response schema remains `GovernanceAnalyticsDetailRead` with unchanged fields:
`generated_at`, `date_range_days`, `insights`, `recommendations`, `trends`, `charts`,
`recent_activity`, and `export_sections`.

Added/updated tests cover:

- detail endpoint contract
- complete empty detail serialized shape
- miss/hit execute-boundary regression through the two bundle helpers
- summary/detail split behavior
- governance cache, RBAC, tenant isolation, and timing regressions

Validation run:

```
python -m pytest tests -k governance
# 130 passed, 511 deselected
```

### EXPLAIN ANALYZE

Captured against remote Supabase on 2026-07-13.

`detail_project_bundle`:

- Planning Time: **0.901 ms**
- Execution Time: **0.340 ms**
- Plan shape: visible projects Seq Scan on the small project set, independent HashAggregate CTEs for
  dependency/escalation/action/scope counts, Hash Left Joins back to visible projects, final Sort by
  project name

`detail_source_bundle`:

- Planning Time: **2.165 ms**
- Execution Time: **5.190 ms**
- Plan shape: Append over JSON payload branches, visible-project CTE, independent source CTE scans,
  recent-activity Sorts over small CTE sets, signal UNION branches for throughput/quality/milestones/
  risks/bottlenecks
- Largest row source in this sample was delivery signal history (`throughput_snapshots`, 2235 rows);
  SQL execution time is still far smaller than remote RTT

No new indexes were added. The observed SQL cost does not justify index work for Phase 4.

### Benchmark

The benchmark script now reports analytics-detail cache misses as **2 executes** and cache hits as
**0 executes**. Run from `backend/`:

```
python scripts/benchmark_governance_latency_baseline.py
```

Phase 4 remote run, internal user, `days=30`, warm pool, cleared cache:

| Metric | Value |
|--------|-------|
| min | **1045.1 ms** |
| avg | **1071.6 ms** |
| median | **1067.8 ms** |
| p90 | **1095.0 ms** |
| p95 | **1100.4 ms** |
| max | **1105.7 ms** |
| execute count | **2** |
| cache hits | 0/4 |
| row count | 5 insight/recommendation rows |

Immediate repeat/cache-hit:

| Metric | Value |
|--------|-------|
| immediate repeat avg | **0.1 ms** |
| explicit cache-hit avg | **0.2 ms** |
| execute count | **0** |
| cache hits | 5/5 |

Baseline remains Phase 0: detail cache miss approximately **3818 ms**, cache hit approximately
**0.1 ms**, and execute count recorded only as "many" at the time. The current code-level inventory
identifies the representative internal miss path as 19 executes before Phase 4.

### Date-window and business-rule notes

Current behavior is preserved rather than corrected:

- detail trends use the selected `days` window for source inclusion and bucket count
- chart distributions and current project-health totals remain current/all-time over visible rows,
  not date-window filtered
- recent activity uses a fixed top-8 global result assembled from top-8 per source type, not the
  selected `days` window
- `_build_trends` still anchors bucket dates with `date.today()` internally

Follow-up: decide whether totals, charts, and recent activity should use the same date-window
semantics as trends.

### Progressive-load confirmation

No frontend files changed in Phase 4. Governance detail remains loaded by the existing idle/in-view
detail strategy, is not part of first paint, and is not included in hover prefetch.

### Remaining work

- Run live EXPLAIN/benchmark against remote Supabase and paste measured planning/execution/RTT numbers
- Add optional analytics cache invalidation after governance writes
- Revisit register day-rollover optimization separately
- Consider business-rule cleanup for inconsistent `days` semantics

## Historical profiling notes

Earlier sections (dependencies paginate-then-join, bootstrap KPI merge, analytics summary bundling, register summary table) remain useful engineering history. Those measurements often used `limit=50` / register `limit=25`. Prefer the Phase 0 tables above for dashboard first-page comparisons going forward; use the Phase 1 table for cache-hit comparisons.
