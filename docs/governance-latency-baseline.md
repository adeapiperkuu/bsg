# Governance Page Latency Baseline

Measurement-only baseline captured **2026-07-06** before any governance performance refactors. Use this document to compare each optimization phase against the same endpoints and log fields.

## What loads on first paint

Route: `/governance` → `GovernanceDashboard` (`frontend/src/features/governance/GovernanceDashboard.tsx`).

The page composes KPIs client-side from paginated list responses; it does **not** call `GET /governance/bootstrap` on initial load (that query helper exists but is unused here).

### Internal users (`delivery_manager`, `bsg_leadership`, `super_admin`)

| Order | React Query | HTTP endpoint | Blocks first paint? |
|------|-------------|---------------|---------------------|
| 1 | `governanceDependenciesQueryOptions` | `GET /api/v1/governance/dependencies?limit=50&offset=0` | Yes — primary table tab (default) |
| 2 | `governanceAnalyticsQueryOptions(30)` | `GET /api/v1/governance/analytics?days=30` | Yes — executive analytics header |
| 3 | `projectsQueryOptions` | `GET /api/v1/projects` | Partial — filter dropdowns; page shell renders before this completes |

**Not on first load:** register, actions, scope states, bootstrap, delivery portfolio, users, charters, agent chat.

### Client users (`client`)

| Order | React Query | HTTP endpoint | Blocks first paint? |
|------|-------------|---------------|---------------------|
| 1 | `governanceEscalationsQueryOptions` | `GET /api/v1/governance/escalations?limit=50&offset=0` | Yes — primary table tab (default) |
| 2 | `projectsQueryOptions` | `GET /api/v1/projects` | Partial — filter dropdowns |

**Not on first load:** dependencies, actions, analytics, register, bootstrap, agent/charters tools (internal-only section).

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
governance_endpoint_timing endpoint=GET /governance/analytics role=delivery_manager org_id=<uuid> row_count=1 total_ms=1426.6 db_ms=1426.6 serialization_ms=0.1
```

Structured fields (also in `logging` `extra`):

- `endpoint` — HTTP method + path
- `role` — caller role (`delivery_manager`, `client`, …)
- `org_id` — organisation UUID (or `null` for cross-org super admin)
- `row_count` — rows returned (list endpoints) or `1`/`0` for data payloads
- `total_ms` — full handler time
- `db_ms` — time inside `governance_db_section` / `@governance_db_timed` service calls
- `serialization_ms` — `total_ms - db_ms` (Pydantic mapping, response build, cache hits)

DB-timed service entry points include list pages, register, analytics, bootstrap KPI computation, and shared pagination helpers.

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
| `GET /governance/analytics` | **1427** | 1427 | 0.1 | **Slowest** — multiple aggregate queries + delivery portfolio join |
| `GET /governance/escalations` | 441 | 439 | 2.1 | Internal-user path |
| `GET /governance/register` | 403 | 403 | 0.1 | Not on first paint; heavy per-project subqueries |
| `GET /governance/dependencies` | 375 | 374 | 1.6 | Internal first-paint table |
| `GET /governance/bootstrap` | 343 | 342 | 0.1 | Not called by current UI; KPI-only payload |

Client user escalations (representative client org): **~60–120 ms** after connection warm-up.

Internal first-paint critical path (parallel requests): dominated by **analytics (~1.4 s)** + **dependencies (~375 ms)** + projects list. Perceived load follows the slower of analytics and the primary table.

## What to optimize first

1. **`GET /governance/analytics`** — Largest share of internal-user first paint; almost entirely `db_ms`. Likely wins: reduce query fan-out, avoid redundant delivery portfolio pull, tighten date-range scans, ensure partial indexes are applied (`20260703120000_governance_active_partial_indexes.sql`).
2. **`GET /governance/dependencies`** — Second on internal critical path; list + count pagination. Verify index use on `org_id`, `status`, `due_date`.
3. **`GET /governance/register`** — Not first paint, but expensive when users switch tabs; same class of multi-subquery aggregation as analytics.
4. **`GET /governance/bootstrap`** — Moderate latency if reintroduced to the UI; already has a short in-process KPI cache (not Redis).

Defer: agent chat, charter generation, export endpoints — not on dashboard first paint.

## Metrics to compare after each phase

Track the same fields from `governance_endpoint_timing` logs:

| Metric | Target direction | Phase comparison |
|--------|------------------|------------------|
| `total_ms` (p50 / p95) per endpoint | Down | Primary success metric |
| `db_ms` / `total_ms` ratio | Down if DB-bound | Confirms DB vs serialization work |
| `serialization_ms` | Stable or down | Catches mapping/payload regressions |
| Internal first-paint wall time | Down | Browser DevTools → Network, slowest of analytics + dependencies + projects |
| Client first-paint wall time | Down | Network: escalations + projects |
| `row_count` at fixed filters | Stable | Ensures optimizations did not truncate data |

Suggested acceptance checks per phase:

- Internal cold load: `analytics` p95 < 800 ms, `dependencies` p95 < 250 ms
- Client cold load: `escalations` p95 < 150 ms
- No increase in error rate on the four baseline endpoints

## Related files

- Frontend load orchestration: `frontend/src/features/governance/GovernanceDashboard.tsx`
- Query definitions: `frontend/src/lib/queries/governance.ts`
- Timing helper: `backend/app/agents/governance/timing.py`
- Timing tests: `backend/tests/test_governance_timing.py`

## Cleanup notes

**Cleanup Batch 1 (2026-07-06):** Removed the unmounted legacy governance API layer (`app/api/routes/governance.py`, `app/services/governance.py`, `app/agents/governance/dependencies.py`). These were not registered in `main.py` and formed an isolated import chain. The live router is `app.agents.governance.routes.governance`, mounted via `app.include_router(governance_routes.router, prefix=api_prefix)` in `main.py`.
