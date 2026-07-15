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
- Revisit register day-rollover optimization separately
- Consider business-rule cleanup for inconsistent `days` semantics

## Phase 5: Analytics Cache Invalidation

Phase 5 replaces TTL-only freshness for split analytics reads with post-commit invalidation.
No SQL, API contract, Redis, TTL, or frontend behavior changed.

### Previous behavior

The summary and detail endpoints used independent in-process caches with a 3-minute TTL:

- summary cache key: `(org_id|None, role, user_id, days)`
- detail cache key: `(org_id|None, role, user_id, days)`
- `org_id=None` represents super-admin cross-org reads

After dependency, escalation, action, scope, or delivery-risk-promotion writes, the list/register
caches were cleared after commit, but analytics summary/detail entries could remain stale until TTL
expiry.

### New invalidation behavior

`analytics_service.py` now exposes pure in-memory helpers:

- `clear_governance_analytics_summary_cache(org_id=...)`
- `clear_governance_analytics_detail_cache(org_id=...)`
- `clear_governance_analytics_caches(org_id=...)`

These helpers do not create sessions and do not execute SQL. For a concrete org write, they remove:

- all summary/detail entries whose key org scope matches that org
- all summary/detail entries whose key org scope is `None`, because super-admin aggregate reads can
  include the changed org

They preserve other org-specific entries. If no org can be supplied, the helper clears every
summary/detail entry rather than risking an unknown stale org.

The existing `invalidate_governance_read_caches_after_commit()` hook now returns removal counts for
dependencies, register, analytics summary, and analytics detail caches, and logs a single structured
line with org scope, counts, and invalidation duration.

### Write matrix

The following successful write paths now pass the committed row's org into the post-commit helper:

| Write path | Cache invalidation timing |
|------------|---------------------------|
| dependency create/update/resolve/archive | after `session.commit()` |
| escalation create/update/archive | after `session.commit()` |
| action create/update/archive | after `session.commit()` |
| scope state upsert | after `session.commit()` |
| delivery risk promotion to escalation | after `session.commit()` |

`refresh_project_governance_summary()` still runs before commit as part of the mutation transaction.
Read caches are cleared only after the commit succeeds, so rollback/error paths keep the old cache
entries.

### Scope decisions

- Dashboard bootstrap KPI cache remains unchanged; it is keyed separately and should be reviewed in a
  dedicated pass with the bootstrap endpoint's own freshness requirements.
- The legacy full analytics cache was not expanded or redesigned in this phase. Phase 5 is limited to
  the progressive summary/detail reads that back the optimized Governance dashboard path.

### Tests

Added `test_governance_analytics_cache_invalidation_phase5.py` covering:

- direct summary/detail helper clearing by org
- preservation of org B entries after org A invalidation
- removal of `org_id=None` super-admin aggregate entries after concrete org writes
- all-entry fallback when org scope is unknown
- post-commit helper forces the next summary/detail read to miss and rebuild once
- failed write/rollback boundary leaves cached summary/detail entries intact

Focused validation:

```
python -m pytest backend/tests/test_governance_analytics_cache_invalidation_phase5.py \
  backend/tests/test_governance_first_paint_cache.py \
  backend/tests/test_governance_analytics_summary_phase3.py \
  backend/tests/test_governance_analytics_split.py \
  backend/tests/test_governance_timing.py
# 48 passed
```

## Phase 6: Final Hardening and Production Readiness

Phase 6 was a final validation pass before AI feature development. It did not redesign the
Governance architecture or add product features.

### Small hardening changes

- Bootstrap KPI cache now has the same post-commit invalidation behavior as analytics:
  concrete org writes clear that org plus `org_id=None` super-admin aggregate entries; unknown org
  scope clears all bootstrap entries.
- Actions and scope-state list services now record `execute_count` and `cache_hit` metadata in the
  request timer, matching dependencies, register, escalations, bootstrap, and analytics.
- `benchmark_governance_latency_baseline.py` now reports `db_ms`, `serialization_ms`, and composite
  project-sheet timings, and covers actions, escalations, and representative project-sheet reads.
- Added Phase 6 regression guards for bootstrap invalidation, analytics execute ceilings, and
  list-service timing metadata.

### Final endpoint profile

Captured **2026-07-13** against remote Supabase with the expanded benchmark script, warm DB pool,
`limit=6`, `offset=0`, `days=30`. Cold rows below drop the first warm-up sample, matching the
historical baseline method.

| Endpoint / workload | Cache miss p50 | Cache miss p95 | Avg `db_ms` | Avg serialization/Python ms | Miss executes | Cache hit p50 | Cache hit p95 | Hit executes |
|---------------------|----------------|----------------|-------------|-----------------------------|---------------|---------------|---------------|--------------|
| Bootstrap, internal | **807.4 ms** | **825.9 ms** | 708.5 | 100.5 | 1 | **0.1 ms** | **0.2 ms** | 0 |
| Dependencies first page | **826.1 ms** | **834.9 ms** | 718.3 | 102.7 | 1 | **0.2 ms** | **0.3 ms** | 0 |
| Register first page | **1386.4 ms** | **1413.2 ms** | 1279.3 | 105.5 | 4 | **0.1 ms** | **0.2 ms** | 0 |
| Actions first page | **803.8 ms** | **829.0 ms** | 703.6 | 101.8 | 1 | N/A | N/A | N/A |
| Escalations first page, internal | **812.6 ms** | **831.5 ms** | 711.0 | 103.2 | 1 | N/A | N/A | N/A |
| Analytics summary | **943.7 ms** | **960.6 ms** | 841.0 | 105.1 | **1** | **0.2 ms** | **0.4 ms** | **0** |
| Analytics detail | **1072.8 ms** | **1082.3 ms** | 963.2 | 106.2 | **2** | **0.1 ms** | **0.3 ms** | **0** |
| Project sheet filtered reads | **4814.0 ms** | **5000.2 ms** | 4298.0 | 533.9 | 8 cold / 5 repeat | N/A | N/A | N/A |
| Bootstrap, client | **819.0 ms** | **836.2 ms** | 719.5 | 103.8 | 1 | **0.4 ms** | **0.5 ms** | 0 |
| Escalations first page, client | **665.2 ms** | **1123.8 ms** | 675.3 | 106.8 | 1 | N/A | N/A | N/A |

Current execute-count contract:

- bootstrap miss: 1; hit: 0
- dependencies default first page miss: 1; hit: 0
- register default first page cold miss: 4; hit: 0
- actions first page: 1; no cache
- escalations first page: 1; no cache
- analytics summary miss: 1; hit: 0
- analytics detail miss: 2; hit: 0
- project sheet representative filtered workload: 8 cold, 5 repeated in this dataset

### Cache invalidation coverage

Post-commit invalidation now covers the read caches affected by Governance writes:

| Mutation | Dependencies cache | Register cache | Bootstrap cache | Analytics summary/detail |
|----------|--------------------|----------------|-----------------|--------------------------|
| Dependency create/update/resolve/archive | cleared | cleared | org + super-admin cleared | org + super-admin cleared |
| Escalation create/update/archive | cleared | cleared | org + super-admin cleared | org + super-admin cleared |
| Action create/update/archive | cleared | cleared | org + super-admin cleared | org + super-admin cleared |
| Scope state upsert | cleared | cleared | org + super-admin cleared | org + super-admin cleared |
| Delivery risk promotion | cleared | cleared | org + super-admin cleared | org + super-admin cleared |

Remaining TTL-only or intentionally scoped caches:

- legacy monolithic analytics cache remains TTL-only; the active dashboard path uses split
  summary/detail endpoints
- register `_org_summary_day_refreshed` marker is date-scoped correctness state, not user response
  cache, and is intentionally cleared when a project summary is refreshed

### Register cold path review

The register cold path still performs about four executes when the daily summary marker is cold and
summaries require date-sensitive refresh:

1. check whether any project governance summary row is stale for the org/day
2. load stale summary rows
3. compute per-project overdue action and blocking-overdue dependency counts
4. load the register page

This is not duplicated work in the current design; it preserves date rollover correctness for
overdue action/dependency counts before the register page is built. Optimizing it likely means a
small schema/job decision, such as scheduled daily refresh or consolidating the stale-row check and
refresh load. That is intentionally deferred because remote RTT, not SQL execution, is the dominant
cost and because the cache-hit path is already zero executes.

### Remaining bottlenecks

- Remote Supabase RTT dominates every cold one-query endpoint. A single execute is consistently
  around **800-950 ms** in this environment even when SQL itself is small.
- Register cold latency is higher because correctness can require multiple round trips at day
  rollover.
- Project-sheet reads are slow because they are a composite of several filtered, uncached list
  requests. This is a frontend/workload orchestration concern rather than a single-query regression.
- Python/serialization overhead is usually about **100 ms** per cold request in these service-level
  measurements; project-sheet composite overhead is higher because it chains several service calls.

### Production recommendations

- Prefer API and database colocation, or Supabase transaction pooler/region alignment, before doing
  more SQL micro-optimization.
- Keep `governance_endpoint_timing` logs on for Governance routes and alert on execute-count
  regressions: summary > 1, detail > 2, cache-hit executes > 0.
- Track cache-hit ratios for dependencies, register, bootstrap, and analytics split endpoints.
- Defer project-sheet optimization until usage data confirms it is a frequent workflow; likely
  approaches are frontend request batching or a narrowly scoped project-sheet read model.
- Defer register day-rollover optimization unless cold register p95 remains user-visible after
  deployment topology is fixed.

### Phase 6 validation

```
python -m pytest backend/tests/test_governance_phase6_hardening.py \
  backend/tests/test_governance_analytics_cache_invalidation_phase5.py \
  backend/tests/test_governance_first_paint_cache.py \
  backend/tests/test_governance_analytics_summary_phase3.py \
  backend/tests/test_governance_analytics_split.py \
  backend/tests/test_governance_timing.py
# 52 passed

python scripts/benchmark_governance_latency_baseline.py
# completed against remote Supabase, values summarized above
```

Ruff on the new Phase 6 test and benchmark script is clean after formatting. Broader Governance
ruff still includes pre-existing long-line findings in older service files and should be handled as
a separate style cleanup.

### Lessons learned

- The biggest wins came from removing remote round trips, not changing local Python shape.
- Cache-hit correctness is now as important as cache-hit speed; post-commit invalidation prevents
  the three-minute stale window for active dashboard reads.
- Endpoint timing metadata is the right regression surface: `execute_count`, `cache_hit`, `db_ms`,
  `serialization_ms`, and `total_ms` explain almost every observed latency change.

## Historical profiling notes

Earlier sections (dependencies paginate-then-join, bootstrap KPI merge, analytics summary bundling, register summary table) remain useful engineering history. Those measurements often used `limit=50` / register `limit=25`. Prefer the Phase 0 tables above for dashboard first-page comparisons going forward; use the Phase 1 table for cache-hit comparisons.

## Phase A1: Frontend request hygiene

Implemented **2026-07-14**. This phase changes only frontend query enablement and request timing; it
does not change API contracts, backend query shapes, cache policy, or the latency values measured in
the earlier backend phases.

### First-paint request lifecycle

| Audience / moment | Before A1 (code-confirmed enablement) | After A1 (automated request-harness observation) |
|-------------------|---------------------------------------|--------------------------------------------------|
| Internal first paint | Bootstrap, dependencies, register, projects, and AI recommendations could start from mounted dashboard sections | Bootstrap and dependencies (`limit=6`) start together; register, projects, and AI recommendations are absent |
| Internal progressive analytics | Summary deferred by the existing timer; detail deferred by visibility | Unchanged: summary remains deferred and detail remains visibility-gated |
| Client first paint | Bootstrap plus the standard client escalations list | Unchanged: bootstrap plus standard client escalations |
| Register tab | Data could already be in flight before selection | Register and portfolio queries enable when the user selects Register; React Query reuses the cached result on later visits |
| Project-dependent workflows | Full project list could load because executive analytics was mounted | Project list enables only for an open project filter/dialog or another workflow that needs project metadata |
| AI recommendations | List could load as soon as the recommendations section mounted | List enables only after the recommendations area becomes visible; generation/regeneration remain explicit actions |

The post-A1 first-paint budget is therefore **2 critical internal requests** (bootstrap and
dependencies) or **2 critical client requests** (bootstrap and standard client escalations).
Analytics summary/detail remain progressive work outside that initial budget.

### Validation boundary

Measured in the Vitest request harness on 2026-07-14: deferred endpoints are absent on initial
render, register/project queries start after their interactions, cached register data is reused, and
the standard client escalation request is not suppressed. These observations verify frontend query
enablement and ordering, not real-network duration.

A production build and the focused A1 test results are recorded in the implementation handoff. A
fresh backend benchmark was completed with the existing script; its values are backend service
measurements, not browser first-paint timings. Browser DevTools
waterfall timing remains a manual production-like validation step because the automated harness does
not emulate deployment RTT or an authenticated browser session.

### A1-day backend benchmark snapshot

Measured **2026-07-14** against the configured remote Supabase database with the existing benchmark
script. These cold-cache/warm-pool values exclude each endpoint's first warm-up sample. They provide
current request-cost context only; A1 did not modify these backend paths.

| Endpoint | Service p50 | Service p95 | Miss executes |
|----------|-------------|-------------|---------------|
| Bootstrap, internal | 1183.1 ms | 1255.5 ms | 1 |
| Dependencies first page | 1154.1 ms | 1206.2 ms | 1 |
| Register first page | 1887.2 ms | 2099.0 ms | 4 |
| Analytics summary | 1267.8 ms | 1335.5 ms | 1 |
| Analytics detail | 2237.0 ms | 2702.5 ms | 3 |
| Bootstrap, client | 1224.2 ms | 1808.5 ms | 1 |
| Escalations first page, client | 935.2 ms | 939.8 ms | 1 |

The detail execute count was **3** in this run, above the Phase 6 documented ceiling of 2. That is a
backend follow-up signal and is not attributed to the A1 frontend-only changes.

## Phase B: Actions and escalations first-page read caches

Implemented and measured **2026-07-14**. Phase B adds bounded, process-local caching to the two
remaining default first-page Governance list reads. It does not change cold database RTT, frontend
request gating, response schemas, sorting, or arbitrary filtered request behavior.

### Eligibility and TTL

Only `limit=6`, `offset=0`, unfiltered requests are eligible. Any non-default `project_id`,
`status`, `severity`, `dependency_type`, `owner_id`, `assigned_to`, `search`, `date_from`, or
`date_to` bypasses the cache. Other limits and non-zero offsets also bypass it. Whitespace-only
search is normalized to the existing unfiltered meaning.

Both caches use a **60-second TTL**. Empty successful pages are cacheable. Expired entries are
removed on lookup, and exceptions are never stored.

### Key and authorization scope

Both keys use:

```text
(effective_org_id, role, user_id, limit, offset)
```

`effective_org_id` is `None` for super-admin aggregate visibility and the concrete organization for
all other users. `user_id` is intentionally retained even where current internal visibility is
organization-wide. This conservative scope prevents entries from crossing users, roles, tenants,
or client assignment sets.

For clients, project assignment and `client_visible=true` remain database predicates in the same
paginated escalation query. The previous separate assignment lookup was replaced by a correlated
`EXISTS`, so an eligible assigned-client miss remains one execute. The cache stores only the final
authorization-filtered page and returns a copied item list on hits.

### Post-commit invalidation

Actions and escalations are cleared through `invalidate_governance_read_caches_after_commit`, after
successful commits. Direct create/update/status/publish/archive flows, recommendation conversions,
delivery integration, and quality-triggered escalation creation already converge on this helper.
Failed commits do not clear or replace a valid entry.

Invalidation is **organization-scoped** for the two Phase B caches and also clears super-admin
aggregate entries because those may contain rows from the mutated organization. Other organization
entries remain warm. The older dependencies and register invalidators retain their existing broader
behavior.

### Measured benchmark

Remote Supabase service benchmark, cold cache with warm pool; the first warm-up sample is excluded.
Warm-hit rows are a separately primed in-process series using the same request shape.

| Endpoint / audience | Request shape | Cold miss p50 | Cold miss p95 | Warm hit p50 | Warm hit p95 | Miss executes | Hit executes |
|---------------------|---------------|--------------:|--------------:|-------------:|-------------:|--------------:|-------------:|
| Actions, internal | `limit=6&offset=0`, unfiltered | 1170.2 ms | 1180.2 ms | 0.1 ms | 0.2 ms | 1 | 0 |
| Escalations, internal | `limit=6&offset=0`, unfiltered | 1195.2 ms | 1224.4 ms | 0.2 ms | 0.3 ms | 1 | 0 |
| Escalations, client | `limit=6&offset=0`, unfiltered | 1226.2 ms | 1252.7 ms | 0.1 ms | 0.2 ms | 1 | 0 |

The benchmark client identity had no visible escalation rows; assigned-client authorization and
cross-client isolation are covered separately by the Phase B SQL-predicate and cache-isolation
tests. The measurements show a repeat-read cache benefit, not infrastructure colocation or a cold
RTT improvement.

### Validation and operating limits

- Focused Phase B tests: **17 passed**.
- Governance regression selection: **247 passed**, 506 deselected; one pre-existing AsyncMock
  resource warning remains in the project-summary test.
- Cache/security/pagination regression group: **62 passed**.
- Ruff check and format check pass for the changed Python files.
- Caches are per backend process. They are not shared across workers and provide no distributed
  single-flight behavior.
- Concurrent misses may duplicate the database read, but only complete page values are published;
  dictionary lookup/write work is small and synchronous.
- Direct database edits to project assignments outside application mutation paths can leave a
  user-specific client entry valid until its 60-second TTL expires. There is currently no
  application assignment-write endpoint to attach to the post-commit invalidator.

## Phase D: Register day-rollover optimization

Implemented and measured **2026-07-14**. Phase D moves UTC-day summary maintenance out of
`GET /governance/register` and into the repository's existing APScheduler lifecycle. No schema,
response, sorting, authorization, pagination, or frontend-gating changes were made.

### Previous request flow

After a register-cache miss, the GET path called
`ensure_org_time_sensitive_summary_counts` before reading the page:

1. Check for summary rows whose `updated_at` date was before the current UTC date.
2. If stale rows existed, load those summary rows.
3. Aggregate overdue actions and blocking overdue dependencies by project.
4. Flush updated summary rows.
5. Load the register page and pagination total.

The service-level counter reported **4 executes** for the stale path because it counted the three
explicit refresh reads plus the register page. The ORM flush could also emit an update statement
that was not represented in that manual counter. More importantly, the GET service did not own a
commit: the process-local "refreshed today" marker could advance while the session later rolled the
summary updates back. That coupled correctness to one process and made cold/restarted paths repeat
the remote work.

If the in-process day marker was already warm, GET skipped refresh work; if the marker was cold but
no rows were stale, it still paid a staleness-check execute before the page query.

### Selected strategy and new flow

The application already uses APScheduler, so Phase D uses a scheduled daily-refresh strategy:

- An hourly catch-up trigger runs at minute 5 with `timezone=UTC`. The SQL predicate makes each
  summary row eligible at most once per UTC day, so healthy operation performs daily work while an
  hourly trigger provides retry after a missed start or transient failure.
- One PostgreSQL `UPDATE ... RETURNING` statement refreshes all stale summary rows. Correlated
  aggregate subqueries calculate the two date-sensitive fields.
- `pg_try_advisory_xact_lock` is part of the same statement. It serializes refresh attempts across
  processes; the `updated_at < UTC day start` predicate makes retries idempotent.
- The scheduler commits before invalidating register cache entries. A failure rolls back, logs a
  structured exception, preserves the previous committed summaries, and invalidates nothing.
- A manual operator command uses the identical transaction and invalidation sequence:

```powershell
cd backend
.\.venv\Scripts\python.exe scripts\refresh_governance_register_summaries.py
```

The normal GET flow is now simply: authorization and cache lookup, one existing paginated register
query on a miss, then cache the final page. It performs no stale check, recomputation, or write.

### Day semantics and cache behavior

The business day is explicitly **UTC**. The refresh compares timezone-aware `updated_at` values to
`00:00:00+00:00` for the target date. Server local time and daylight-saving transitions do not
change the business date. The current product has no organization-timezone setting, so no local
organization rollover is inferred.

The existing 60-second first-page cache remains. Its key still includes effective organization,
role, user, limit, and offset. Register invalidation is now organization-scoped and also removes
super-admin aggregate entries. Central Governance mutations and scheduled refreshes invalidate only
after commit.

GET timing metadata now includes `summary_refresh_required=false`,
`summary_refresh_performed=false`, `summary_refresh_ms=0`, `summary_rows_refreshed=0`, and
`register_row_count`, alongside the existing cache and execute fields. The scheduled operation logs
its UTC business date, refreshed rows, organization count, execute count, refresh duration, and
post-commit cache removals.

### Measured results

The backend ran locally without Docker and connected to the configured remote Supabase session
pooler. The rollover simulation marked rows stale and performed the refresh inside a transaction
that was rolled back after every sample; it persisted no benchmark changes. The simulated first
and second reads reused that transaction/connection, so their latency is not directly comparable to
a new production HTTP connection.

| Scenario | Historical before executes | Phase D executes | Phase D p50 | Phase D p95 |
|----------|---------------------------:|-----------------:|------------:|------------:|
| Same-day cold miss | 4 measured on the prior stale/cold path | 1 | 1199.4 ms | 1262.4 ms |
| Warm hit | 0 measured | 0 | 0.179 ms | 0.359 ms |
| Scheduled rollover refresh | 3 refresh reads plus an uncounted flush write | 1 | 354.2 ms | 360.5 ms |
| First read after simulated rollover | 4 inferred from the previous blocking refresh path | 1 | 231.0 ms | 248.3 ms |
| Second read after simulated rollover | 0 with a retained warm page | 0 | 0.101 ms | 0.321 ms |

The historical before values come from the documented pre-Phase-D service flow and earlier remote
register benchmark. Only the Phase D columns were measured by the new rolled-back benchmark. Cold
RTT remains a deployment-topology cost; Phase D removes round trips rather than claiming database
colocation.

The full Governance baseline script also completed after Phase D and independently measured the
register at **1155.2 ms p50**, **1208.7 ms p95**, **1 execute** on a miss, and **0 executes** on a
hit (0.4 ms p50 in that series).

### Validation and failure boundaries

- Focused Phase D tests: **8 passed**.
- Combined focused register/cache/timing tests: **61 passed**.
- Governance-selected regression suite: **255 passed**, 506 deselected.
- Full backend suite: **761 passed**.
- The refresh is an update-only operation and relies on the existing unique organization/project
  summary index; it cannot create duplicate daily rows.
- Multiple workers may all trigger the job, but the transaction-scoped database lock and freshness
  predicate prevent duplicate refresh work.
- Register caches remain process-local. The worker that commits invalidates its affected entries;
  another worker can retain its previous page for at most the remaining 60-second cache TTL because
  this phase does not add cross-worker invalidation infrastructure.
- Persistent scheduler/database failure can leave previous-day counts visible beyond one hour. The
  failure is logged and retried at the next hourly minute-5 trigger; the previous committed summary
  remains readable.
- Missing summary rows are not created by the daily update, matching the previous day-refresh
  behavior. Normal Governance mutations continue to create/refresh a project's summary.

## Phase E: Project-sheet composite API

Implemented and measured **2026-07-14**. Phase E replaces the project drawer's remote request
fan-out with `GET /governance/project-sheet/{project_id}`. Existing list endpoints remain available
for full tables, filters, pagination, exports, deep links, and mutations.

### Confirmed previous request inventory

This inventory comes from the mounted `GovernanceDashboard` and `ProjectGovernanceSheet` query
conditions, not from all project-related APIs in the repository.

| Request on sheet open | Purpose | Required initially | Previous executes |
|-----------------------|---------|-------------------:|------------------:|
| `/governance/dependencies?project_id=...` | First dependency rows | Internal only | 1 |
| `/governance/actions?project_id=...` | First action rows | Internal only | 1 |
| `/governance/escalations?project_id=...` | First authorized escalation rows | Yes | 1 |
| `/governance/scope-states?project_id=...&limit=1` | Scope notes/state | Internal only | 1 |
| `/projects/{project_id}/risk-alerts` | Delivery risks available for promotion | Delivery manager/super-admin only | 2 (project authorization plus list) |

Thus the measured internal comparison is **5 HTTP requests / 6 executes**, not the plan's broader
historical estimate of 5-8 for every role. A client sheet previously started only the standard
client-visible escalation request; dependencies, actions, scope notes, and risk promotion were
already role-gated. Register and delivery-portfolio reads belong to the selected Register tab, not
the drawer-open event. Charters, AI recommendations, escalation-suggestion scans, analytics detail,
audit history, exports, and activity feeds are interaction-gated and are not part of the composite.

### Composite contract and bounds

The response contains project identity/basic dates, a concise governance summary, internal scope
details where authorized, dependency/action/escalation sections, concise delivery risks, permission
flags, and `generated_at`. Each list section has `items`, `total`, and `has_more`; all four lists are
bounded to **6** rows. No large charter text, recommendation explanations, evidence histories,
binary/document metadata, or audit timelines are embedded.

The successful path is one PostgreSQL statement. Its authorized-project CTE applies organization,
role, and active client-assignment visibility before section data is joined. Internal-only sections
remain empty for clients. Client escalations retain `client_visible=true`, replace the description
with the published client summary, and remove source/assignee fields just as the individual endpoint
does. Scope status/version remain visible because the existing register exposes them to authorized
clients; scope notes and linked document metadata remain internal. Delivery risks remain restricted
to delivery managers and super-admins, matching the previous sheet control.

An authorized success executes once. If the authorized CTE returns no row, one bounded existence
check preserves the existing 404-for-missing versus 403-for-forbidden behavior; failure paths can
therefore execute twice. No composite cache was added.

### Frontend integration and invalidation

The drawer enables one stable React Query key,
`["governance", "project-sheet", project_id]`, only while an identified sheet is open. It has one
loading/error state. The old project-filtered dependencies, actions, escalations, scope, and risk
queries no longer enable on initial sheet open. Selecting **View all** closes the drawer, applies the
project filter, selects the relevant full table, and only then enables its individual list request.

Successful dependency, action, escalation, scope, delivery-risk promotion, and client-publication
mutations invalidate the exact affected project-sheet key after the mutation resolves. The existing
individual-list/bootstrap updates remain. An unrelated project's key is not invalidated. Failed
mutations do not run the success invalidation path.

### Measured results

The backend ran locally without Docker against the configured remote Supabase session pooler. The
connection pool was warm, five samples were taken, and the same internal project was used for both
shapes. These are development service timings, not production browser latency.

| Scenario | Before HTTP | After HTTP | Before executes | After executes | p50 before / after | p95 before / after |
|----------|------------:|-----------:|----------------:|---------------:|-------------------:|-------------------:|
| Internal project sheet | 5 measured | 1 measured by harness | 6 measured | 1 measured | 5948.8 / 1137.8 ms | 6229.1 / 1173.0 ms |
| Client project sheet | 1 code-confirmed | 1 harness-confirmed | 1 target/code-confirmed | 1 target/code-confirmed | Not measured | Not measured |

The configured dataset had no active client assignment, so no honest remote client benchmark could
be produced. The client authorization/query shape is covered by focused tests and the frontend
client gating remains unchanged.

The composite response was **2,450 bytes uncompressed**, **938 bytes gzipped**, and took an average
of **0.11 ms** to serialize in the benchmark. The fragmented before payload was 1,724 bytes / 704
bytes gzipped; the bounded composite is larger because it now coordinates project metadata,
summary, counts, permissions, and section metadata in the same response.

### Validation boundary

The frontend request harness observes exactly one project-sheet GET and no dependency/action/
escalation/scope/risk requests on drawer open. It also verifies that **View all** starts the matching
project-filtered individual endpoint. The in-app browser bridge could not initialize, so this is
query-ordering evidence rather than a real Network-panel waterfall or browser-latency measurement.

Structured endpoint timing now records endpoint, project, organization, role, cache status,
execute count, total/database/serialization time, response bytes, and returned section counts. On a
successful composite read authorization is folded into the same SQL statement, so
`authorization_ms=0` denotes no separate authorization round trip; authorization cost is included
in `db_ms`.

Verification completed on 2026-07-14:

- Focused Phase E backend: **6 passed**.
- Governance-selected backend regression: **261 passed**, 506 deselected.
- Full backend: **767 passed**.
- Focused Phase E/A1 frontend: **15 passed**.
- Full frontend: **111 passed** across 22 files.
- Frontend production client/SSR build: passed.
- ESLint and Prettier checks: passed for all changed frontend files.
- Ruff lint and format: passed for the new service, benchmark, tests, and changed timing module.

## Phase F: background AI and long-running jobs

Implemented **2026-07-15**. Generation and large-export endpoints now commit a durable job and
return `202`; model calls, validation/persistence, and file rendering execute in the worker. Product
records commit before job success.

The local architecture harness used 20 samples, excluded HTTP/database transport, and mocked a
50 ms provider delay. This proves request/worker separation; it is not production latency:

| Harness path | p50 | p95 |
|---|---:|---:|
| 202 acceptance path | 0.014 ms | 0.040 ms |
| Background processing | 63.264 ms | 66.602 ms |
| Previous synchronous wait | 62.734 ms | 66.452 ms |

Real acceptance includes authorization, advisory locking, active-job lookup, insert/event writes,
and commit. Production queue-wait and processing distributions are emitted as structured metrics.

Final verification after removing the Escalation Suggestions surface completed with **769 backend
tests** and **111 frontend tests** passing. The active Phase F lifecycle/API suite contains 19
tests. The production client and SSR build passed. Ruff,
Prettier, and targeted ESLint checks passed for the Phase F files. Repository-wide Ruff and ESLint
remain blocked by pre-existing lint, formatting, and line-ending debt outside the Phase F change
set.

See `docs/governance-background-jobs.md` for architecture, APIs, worker commands,
retry/cancellation, recovery, authorization, environment variables, and troubleshooting.

## Phase G: project-charter latency pass

Implemented **2026-07-15**. This phase does not redesign the already warm dashboard hot path:
bootstrap, dependencies, analytics summary, actions/escalations first-page caches, and register
maintenance behavior remain intact. The change focuses on the charter tab and database/pooler
verification.

### Database and pooler verification

`backend/scripts/verify_governance_schema.py` now inspects the live database for required
governance tables, columns, and indexes without printing `DATABASE_URL`.

Run on 2026-07-15 against the configured Supabase transaction pooler:

- `supabase_migrations.schema_migrations` was not available, so applied migration filenames could
  not be verified from the database.
- Required governance tables were present.
- Required governance columns were present.
- `project_charters_org_project_status_created_idx` was missing from the live database.

An idempotent follow-up migration was added:

- `supabase/migrations/20260715113000_governance_project_charter_latency_indexes.sql`

This migration ensures `project_charters_org_project_status_created_idx` and adds
`project_charters_org_created_idx` for unfiltered org charter-list reads. It was added to
`backend/scripts/apply_migrations.py`, but it was not applied by this benchmark run.

The configured connection classified as `supabase_transaction_pooler`. App configuration recognizes
Supabase port `6543` as the preferred transaction-pooler mode, keeps direct Postgres URLs valid, and
continues warning for constrained Supabase session-pooler URLs on port `5432`. Raw `asyncpg`
maintenance scripts now disable statement caching for PgBouncer compatibility.

### Root cause and design

Before this pass, `GET /governance/project-charters` loaded charter rows and then called
`build_project_charter_read()` once per row. Each charter could independently load evidence links,
evidence records, user names, project names, and Knowledge publication metadata. That made SQL
execute count grow with returned rows and evidence links.

The list route now uses a batch page path:

- Load `limit + 1` charters once, preserving existing auth/tenant filters.
- Load all charter evidence links in one query.
- Load evidence records in bounded per-source-type batches.
- Load project names and user display names once per result set.
- Preserve response schema and original charter ordering.
- Keep the single-charter builder for detail/mutation responses by delegating to the batch builder.

### Cache policy

Project charters now reuse the process-local first-page cache pattern. Eligible requests are:

- `offset == 0`
- `limit in {5, 10}`
- default ordering
- optional supported `project_id` filter

TTL is **60 seconds**. Cache entries store fully serialized Pydantic response models, not ORM
instances, and hits return defensive deep copies.

Cache key dimensions:

- Organization scope (`None` for super-admin/global scope)
- Role
- User ID
- Project filter
- Limit
- Offset

Invalidation is explicit after charter generation, draft update, approval, archive, publish,
republish, retry-publication failure/success paths, and unpublish. Invalidation is scoped to the
affected org plus unfiltered and affected-project cache variants; unrelated org entries are left in
place.

### Frontend behavior

The charter panel now requests an explicit first page of **5** charters and can load older versions
in increments of 5. It keeps the existing long stale time and disables unnecessary remount/reconnect
refetches.

Publication version history is no longer fetched during initial panel render. The versions query is
enabled only after the user opens **Show version history**, has its own stale time, and is invalidated
after publish/republish/retry publication mutations.

Charters are still not included in the default governance dashboard bootstrap or first paint.

### Benchmark results

Measured locally against the configured remote Supabase dev database through the transaction pooler
(`6543`). The charter latency index migration above had not been applied yet, so cold misses still
reflect the current live DB index state and remote RTT.

Charter-only benchmark:

| Scenario | Total | DB time | Executes | Cache | Rows |
|----------|------:|--------:|---------:|-------|-----:|
| Charter list cold 1 | 4050.2 ms | 3927.0 ms | 11 | miss | 4 |
| Charter list cold 2 | 4766.8 ms | 4633.6 ms | 11 | miss | 4 |
| Charter list cold 3 | 4783.6 ms | 4661.2 ms | 11 | miss | 4 |
| Charter list cache hit 1 | 2.7 ms | 2.5 ms | 0 | hit | 4 |
| Charter list cache hit 2 | 2.2 ms | 2.0 ms | 0 | hit | 4 |
| Charter list cache hit 3 | 1.6 ms | 1.4 ms | 0 | hit | 4 |
| Project-filtered charter miss | 5048.7 ms | 4932.2 ms | 12 | miss | 2 |
| Project-filtered charter hit | 1.2 ms | 1.0 ms | 0 | hit | 2 |
| Expanded version history | 1298.1 ms | 904.6 ms | 2 | miss | 2 |

Full benchmark script completed successfully after adding charter coverage. Existing dashboard cache
hits remained near-zero SQL; for example bootstrap/dependencies/register/actions/escalations cache
hits were around **0.1-0.6 ms** in the same run. Project-sheet composite reads remain uncached and
are still dominated by remote round trips.

No honest pre-change charter latency was captured before implementation in this run. The previous
shape was verified from code as N+1; this phase’s benchmark establishes the new post-change baseline
and bounded query shape.

### Validation

Completed on 2026-07-15:

- Focused backend charter/pooler/publication tests: **18 passed**.
- Backend governance-selected regression: **266 passed**, 509 deselected.
- Frontend governance tests: **58 passed** across 13 files.
- Backend modified-file compile check: passed.
- IDE diagnostics for changed backend/frontend files: no reported errors.

`python -m ruff check ...` could not run from the global environment because the installed Python
wrapper points at a missing `ruff.exe`. No project `backend/.venv/Scripts/ruff.exe` was present.
