# Quality Intelligence Performance — Implementation Plan

Goal: fix the load times measured on 2026-07-15 (first load ~7.5s, project switch ~2.5s, agent ~19s).
Executor model: **Sonnet 5** agents, highest effort ("ultracode"). Each task below is written to be self-contained and pasteable, with explicit **DONE** criteria.

## Baseline (numbers to beat)

| Scenario | Baseline | Target |
|---|---|---|
| First load `/quality` (cold) | ~7.5 s | ≤ 2.5 s |
| Switch project | ~2.5 s | ≤ 0.8 s |
| Agent query (`POST /agent-queries`) | ~19 s | ≤ 10 s (or streamed first-token ≤ 4 s) |
| Any authenticated endpoint (fixed tax) | ~1.7 s | ≤ 0.4 s warm |

Root cause: remote Supabase DB (AWS eu-west-1) + `NullPool` (new connection per request, zero reuse) + sequential per-query round-trips + a sequential request waterfall on first load + agent doing 3 sequential LLM calls.

## Phase & parallelism map

| Phase | Agents | Parallel? | Depends on |
|---|---|---|---|
| 0 — Benchmark harness + baseline | 1 | (1B may start alongside) | — |
| 1 — Foundation | **1A backend pool** ∥ **1B frontend waterfall** | Yes (disjoint files) | 0 for verification |
| 2 — Deep optimization | **2A quality-page parallelize** ∥ **2B agent LLM** | Yes (disjoint files) | **1A merged** |
| 3 — Integration, verify, tune | 1 | — | 1 + 2 merged |

Peak concurrency: 2 agents. Files are partitioned so parallel agents never edit the same file.

---

## SHARED CONTEXT (paste into every agent prompt)

You are working in the `bsg/` app. Backend: FastAPI + SQLAlchemy async + asyncpg against a **remote** Supabase Postgres (AWS eu-west-1). Frontend: TanStack Start/Router + React Query, Vite dev on :3000 proxying `/api` → backend :8000. API base is `/api/v1`.

Run the app: repo-root `.claude/launch.json` defines `backend` (uvicorn app.main:app :8000) and `frontend` (`npm run dev --prefix frontend` :3000). Backend venv: `bsg/backend/.venv`.

Auth for testing: dev login accounts, password `bsg-dev-2026`. **Use the PM account `pm@bsg.dev` (role delivery_manager)** — the Quality Intelligence agent is PM-facing and admin is not correctly scoped for it. Mutations require header `X-CSRF-Token` set to the `csrf_token` cookie value.

Key files:
- DB engine/pool: `backend/app/db/session.py`; RLS: `backend/app/db/rls.py`; config: `backend/app/core/config.py`; auth/user load: `backend/app/core/security.py` (`_load_user` calls `set_rls_context`).
- Quality page service: `backend/app/services/quality.py` (`build_quality_page`, has step-level timing logs).
- Quality route: `backend/app/api/routes/quality.py`.
- QI agent: `backend/app/agents/quality_intelligence/` (`query_handler.py`, `reasoning.py`, `oka_client.py`), route `backend/app/api/routes/agents.py`, service `backend/app/services/agent_queries.py`.
- Frontend quality: `frontend/src/routes/quality.tsx`, `frontend/src/lib/queries/quality.ts`, `frontend/src/lib/queries/delivery.ts` (projects), `frontend/src/routes/__root.tsx` (auth/me), `frontend/src/lib/api.ts`.

Hard constraints (do not violate):
- **Multi-tenant RLS must stay enforced** — a PM must never read another org's data. `set_rls_context` uses transaction-scoped `SET LOCAL` + `set_config('request.jwt.claims', ..., true)` and `SET LOCAL ROLE authenticated`; these only apply **within the same transaction**. Any change to sessions/pooling/concurrency must keep RLS working and add/keep a regression test proving cross-org isolation.
- Keep all tests green: backend `cd backend && .venv/Scripts/python -m pytest`; frontend `cd frontend && npm run test` and `npm run lint`.
- Do not exceed Supabase connection limits (session pooler ~15 client cap; transaction pooler allows many). No `EMAXCONNSESSION`, no "prepared statement already exists", no "another operation is in progress".
- Match existing code style. After backend code changes, optionally run `graphify update .`.

Verification recipe (browser, works today): open the app via the preview tools, log in as PM, then in the page context run timed `fetch('/api/v1/...', {credentials:'include'})` around `performance.now()`, and read `performance.getEntriesByType('resource')` for request start/duration. Backend step timings: grep uvicorn output for `quality_page ... elapsed_ms`. Prefer the Phase 0 harness (`backend/scripts/bench_perf.py`) once it exists.

**Use graphify for codebase navigation (do this before blind grep):** this repo maintains a knowledge graph in `bsg/graphify-out/`. Start there to locate modules and understand relationships:
- `GRAPH_REPORT.md` — plain-language architecture overview; skim to find the relevant subsystems.
- `manifest.json` — symbol/file index for pinpointing definitions.
- `graph.json` — full node/edge graph for relationships (large — query specific ids, don't read whole).
If a `graphify` CLI is available in your shell, prefer `graphify query "<question>"`, `graphify path "<A>" "<B>"`, `graphify explain "<concept>"`. NOTE: in the current environment the query CLI is **not** on PATH (`python -m graphify` is only the skill installer) — if `graphify query` fails, fall back to reading the `graphify-out/` files directly. After finishing code changes, run `graphify update .` if the CLI is available; otherwise skip.

---

## PHASE 0 — Benchmark harness + baseline (1 agent)

**Task:** Build a repeatable performance harness so every later phase can prove its numbers.

Requirements:
1. Create `backend/scripts/bench_perf.py` (runnable with the backend venv). It must:
   - Log in as PM (`pm@bsg.dev`/`bsg-dev-2026`) against `http://127.0.0.1:8000/api/v1` — read `backend/app/api/routes/auth.py` to implement the exact login request and capture session cookie(s) + CSRF token.
   - Time these, N=5 each, reporting min / p50 / p95 / max (ms): `GET /me`, `GET /projects`, `GET /projects/{firstProjectId}/quality-page` (report cold vs repeat), and `POST /agent-queries` (quality_intelligence_agent, N=3).
   - Also emit a "first-load waterfall" simulation: time `/me`, then `/projects`, then `/quality-page` strictly sequentially and sum — this is the number Phase 1B must break.
   - Accept `--base-url` and `--n` flags; exit non-zero on any non-2xx.
2. Record current results to `docs/perf-baseline.md` (a table + the raw ms).
3. Add a short "How to run" note to that file.

**DONE when:** `python backend/scripts/bench_perf.py` prints a clean table against the running app; `docs/perf-baseline.md` committed with baseline numbers that match the report (~1.7s /me, ~2.5–3s quality-page, ~19s agent, ~7.5s summed waterfall). No secrets hard-coded (read from `.env`/env).

---

## PHASE 1A — Backend connection pooling (1 agent) — CRITICAL PATH

**Problem:** `backend/app/db/session.py` uses `poolclass=NullPool`, so every request opens and discards a fresh connection to the remote pooler. This is a ~1s fixed tax on every authenticated request (proven: repeated calls never warm up). The startup log itself recommends the transaction pooler.

**Task:** Make connections reusable while keeping RLS correct.

Requirements:
1. **Switch to the Supabase transaction pooler (port 6543).** In `.env`, change `DATABASE_URL` port `5432` → `6543` (same host `aws-0-eu-west-1.pooler.supabase.com`, same `postgres.<ref>` user). Keep the old 5432 URL as a commented fallback. Confirm `app/core/config.py` `async_database_url` still yields `postgresql+asyncpg://…:6543/…`.
2. **Persistent client-side pool.** In `session.py`, for the transaction-pooler branch replace `NullPool` with a real pool: `pool_size=10, max_overflow=10, pool_pre_ping=True, pool_recycle=1800`. **Keep** the asyncpg PgBouncer-safety settings already present (`statement_cache_size=0`, `prepared_statement_cache_size=0`, unique `prepared_statement_name_func`). Keep the session-pooler (5432) branch and its semaphore intact as a fallback path selected by URL.
3. **Remove the concurrency gate for the transaction pooler.** The `_SESSION_MODE_MAX_CONCURRENT=4` semaphore exists only to protect the session pooler; do not apply it when on 6543.
4. **RLS correctness under connection reuse (most important).** With a reused pooled connection, `SET LOCAL` reverts at transaction end — good — but it also means RLS context must be (re)applied for **every** transaction, not once per physical connection. Implement a robust pattern: set the request's JWT claims into a `contextvar`, and register a SQLAlchemy `after_begin` (session) event that calls `set_rls_context` using that contextvar at the start of every transaction. Verify read endpoints (single transaction) and write endpoints (which `commit()` mid-request, e.g. `PATCH /me/notifications`) both keep RLS enforced. If the event-based approach is too invasive, the minimum bar is: prove via test that RLS is still enforced after the pooling change across both a read and a post-commit query.
5. Update the misleading startup warning/comments to reflect the new default.

Pitfalls: PgBouncer transaction mode + asyncpg prepared statements → must keep caches disabled (already done); a plain `SET`/`SET ROLE` (non-LOCAL) would leak across reused connections — never introduce one; don't set `pool_size` so high it exhausts the pooler under `uvicorn --reload` double-load.

**DONE when:**
- Phase 0 harness shows `GET /me` warm p50 ≤ 400 ms (from ~1.7 s) and repeated calls now speed up (connection reuse visible).
- A burst test of ≥ 30 concurrent `GET /projects/{id}/quality-page` completes with zero DB connection errors (`EMAXCONNSESSION`, "prepared statement already exists", "another operation is in progress").
- RLS regression test passes: PM (`pm@bsg.dev`) receives 404/empty for a project belonging to another org, both on a read and immediately after a write/commit in the same session lifecycle.
- `pytest` green. Provide before/after `/me` and `/quality-page` numbers in the PR description.

---

## PHASE 1B — Frontend first-load de-waterfall (1 agent) — parallel with 1A

**Problem:** On cold load of `/quality`, three requests run strictly sequentially: `/me` (~1.8s) → `/projects` (~1.8s) → `/quality-page` (~2.7s) ≈ 7.5s. They chain because `/projects` waits for auth and `/quality-page` waits for `/projects` to resolve the first project id.

**Task:** Overlap these requests. Independent of backend internals — only consumes the same endpoints.

Requirements:
1. Inspect `frontend/src/routes/__root.tsx` (or wherever `/me`/auth is resolved) to see how auth gates rendering, and how other routes use TanStack Router `loader`s (respect the app's SSR setup — this is TanStack **Start**; do not break SSR/hydration).
2. Add a `loader` to the `/quality` route (`frontend/src/routes/quality.tsx`) that kicks off, **in parallel** (`Promise.all`, not awaited one-by-one), `queryClient.ensureQueryData(projectsQueryOptions())` and — when `search.projectId` is present — `queryClient.ensureQueryData(qualityPageQueryOptions(projectId))`. This starts both fetches at route-match instead of after render + after each other.
3. **Prefetch projects earlier** so entering `/quality` is warm: once authenticated (root loader / post-login), prefetch the projects list. Ensure `/me` has a sensible `staleTime` so navigation doesn't refetch it and re-serialize.
4. When no `projectId` is in the URL, you still need `/projects` to choose the first id — but with prefetch it should already be in flight/cached, so `/quality-page` starts as soon as possible. Keep `keepPreviousData` for smooth switches (already set).
5. Do not change endpoint contracts. No visual regressions to the page in the screenshot (`QualityDashboard`).

**DONE when:**
- Using the browser resource-timing recipe on a cold load of `/quality?projectId=…`, the `projects` and `quality-page` requests **start within ~100 ms of each other** (overlapped), not chained ~1.8s apart.
- First-load-to-data drops from ~7.5 s toward ≤ 2.5 s once Phase 1A/2A land (frontend change alone must remove the serialization; verify the waterfall is gone even before backend speedups).
- No hydration/SSR errors in the console; `npm run test` and `npm run lint` green. Include a before/after resource-timing screenshot in the PR.

---

## PHASE 2A — Parallelize the quality-page queries (1 agent) — after 1A

**Problem:** `build_quality_page` runs ~6 independent DB loaders sequentially (`load_snapshots`, `load_teams`, `load_open_alerts`, `load_week_scorecards`, `load_error_entries`, plus `get_visible_project` first), each ~130–240 ms → ~0.8–0.9 s serialized.

**Task:** Run the independent loaders concurrently.

Requirements:
1. In `backend/app/services/quality.py`, map data dependencies first (use the existing step logs). `get_visible_project` (authorization + returns the project) must run **before** the concurrent batch. `assemble_dashboard` / calibration brief depend on the loaded data and stay after.
2. **Concurrency constraint:** a single SQLAlchemy `AsyncSession` cannot run concurrent queries. Add a small helper (put it in a **new** file, e.g. `backend/app/db/parallel.py`, to avoid editing `session.py` and conflicting with Phase 1A) that runs each loader on its **own** session via `session_scope()`, applies RLS context for the request's user on each session, executes one loader, and returns its result. Use `asyncio.gather` with bounded concurrency (≤ 6). Reuse the Phase 1A RLS-context mechanism (contextvar) so each parallel session is correctly scoped — do **not** bypass RLS.
3. Keep the response byte-for-byte equivalent to the sequential version for a given project (ordering, rounding, fields). Preserve all existing step logs (or equivalent) so timing stays observable.
4. If per-session RLS for parallel loaders proves unsafe/complex, fall back to overlapping only what's provably safe and document why — but the target is real query overlap.

**DONE when:**
- `quality_page ... step=build_quality_page.total elapsed_ms` drops from ~800–900 ms to ≤ 300 ms; warm endpoint total ≤ 600 ms (with 1A merged).
- A snapshot/response-equality test proves the parallel result equals the previous sequential result for a known seeded project.
- RLS still enforced for the parallel loaders (add a test where a loader would return cross-org rows without RLS and assert it doesn't). `pytest` green. Include before/after step-timing logs in the PR.

---

## PHASE 2B — Quality Intelligence agent LLM optimization (1 agent) — after 1A

> **⚠️ PHASE 0 FINDINGS — READ FIRST; they change this phase's scope in the current dev environment:**
> - **Intent LLM routing is already OFF by default** (`llm_intent_routing=False`, unset in `.env`). Server logs show exactly **2** sequential OpenAI calls per query (reasoning + synthesis), **not 3**. Requirement 1 below is already satisfied in dev — keep the concurrent-overlap guard only for when the flag is enabled (prod); it is **not** a dev win.
> - **OKA is a complete no-op in dev** (`oka_base_url` unset → `oka_client.py` short-circuits, zero HTTP calls, confirmed in logs). Requirements 2 & 3's OKA parts are **prod-hardening/correctness only, with zero measurable dev gain**. Do them for safety but don't expect the numbers to move.
> - **Therefore the only meaningful dev latency reduction is requirement 4 (merge reasoning+synthesis) and/or streaming (promote #5 from stretch to primary).** Baseline agent p50 ≈ 18.3 s is essentially two back-to-back LLM calls.

**Problem:** One `POST /agent-queries` makes sequential OpenAI calls — root-cause reasoning (`reason_root_cause`) then final synthesis (`generate_structured`) — (plus, only when `llm_intent_routing` is enabled, a preceding intent-classification call; and an OKA HTTP call that is inert unless `oka_base_url` is configured). In dev that's 2 serial LLM calls → ~18 s.

**Task:** Cut serial latency without degrading answer quality. Focus effort on #4 and #5 — they are the only dev-measurable wins.

Requirements:
1. **Intent call (prod-only guard):** ensure that when `llm_intent_routing` IS enabled, `classify_intent_llm` runs **concurrently** with DB evidence gathering rather than serially. No-op for dev perf but prevents a regression in prod. Keyword `classify_intent` remains the default path.
2. **OKA (prod-hardening):** it's referenced twice (`query_handler.py` ~lines 171 and 292) — dedupe to a single call, reduce the `httpx` timeout from 30 s to ≤ 3 s, keep failure non-blocking (already degrades to `OKA_UNAVAILABLE`). Add a test. Expect **zero** dev-perf change (OKA inert here) — this is for when `oka_base_url` is set.
3. **Overlap non-DB work with DB work:** OKA/HTTP and any independent LLM call don't use the `AsyncSession`, so they may `gather` alongside the sequential DB evidence building (respect the single-session constraint — never run concurrent queries on one session; use the Phase 2A `app/db/parallel.py` helper for concurrent DB reads).
4. **PRIMARY WIN — merge reasoning + synthesis:** `reason_root_cause` feeds the synthesis and is data-dependent, so they're sequential today (the two OpenAI calls that make up ~all dev latency). Evaluate a single combined prompt that reasons and answers in one call. Build a 5-query eval set (status/diagnostic/action/what-if/impact) and compare answers pre/post; **only merge if quality holds** (grounded citations preserved, no ungrounded claims). If quality regresses, keep them separate and note it — then #5 becomes the main lever.
5. **PRIMARY WIN — stream the synthesis** via SSE and render tokens in `frontend/src/features/quality/AskQualityAgentPanel.tsx` so first token appears ~3–4 s. This is now a primary deliverable (not stretch), since perceived latency is the main user complaint and the total LLM time is hard to compress below ~2 calls if #4 can't merge.

**DONE when:**
- Agent-query p50 improved with **no answer-quality regression** on the 5-query eval set (attach the comparison): target ≤ 10 s non-streamed **if** #4 merges, otherwise streamed **first-token ≤ 4 s** with the panel rendering incrementally.
- OKA: exactly one call per query, capped ≤ 3 s, non-blocking (test added) — even though inert in dev.
- Intent routing, when enabled, is overlapped not serial (test/log evidence).
- Existing agent tests pass; no console errors if streaming shipped.

---

## PHASE 3 — Integration, verification, tuning (1 agent)

**Task:** Confirm the whole system hits targets and is safe under load.

Requirements:
1. Re-run `backend/scripts/bench_perf.py`; produce a before/after table in `docs/perf-baseline.md` (append an "After" section).
2. End-to-end UI check via the preview tools as PM: cold first load, three project switches, one agent query — record real numbers.
3. Tune `pool_size`/`max_overflow` and Phase 2A gather concurrency for best p95 without connection errors; run a 30–50 concurrent burst against `/quality-page` and the agent endpoint.
4. RLS regression suite green (cross-org isolation on read, post-commit, and parallel loaders). No connection errors in a sustained burst.
5. Update `docs/` (and `DEVELOPMENT_PLAN.md` if it tracks this) with the final architecture notes (transaction pooler, pooled connections, parallel loaders, agent changes).

**DONE when:** first load ≤ 2.5 s, switch ≤ 0.8 s, agent ≤ 10 s (or streamed first-token ≤ 4 s); `pytest`, `npm run test`, `npm run lint` all green; no RLS regression; no DB connection errors under burst. Final before/after table committed.

---

## Sequencing / merge notes
- Merge order: 0 → 1A (and 1B any time) → 2A, 2B → 3.
- 1A and 1B edit disjoint trees (backend DB layer vs `frontend/src`) — zero conflict, run together.
- 2A and 2B edit disjoint files (`services/quality.py` + new `db/parallel.py` vs `agents/quality_intelligence/*` + agent route) — run together, but both must branch from a merged 1A because they rely on the pool and the shared RLS-context mechanism.
- Every agent verifies with the Phase 0 harness and must not weaken RLS or break tests.

---

# PHASE 4 — Post-login idle prefetch of Quality Intelligence data

Status as of 2026-07-16: Phases 0, 1A, 1B, 2A-corrected, and agent SSE streaming are SHIPPED and verified (see `docs/perf-baseline.md` "Final results" section). Phase 2A (parallelize loaders) and the 2B LLM-merge were tried and REVERTED — do not retry either; the reasons are documented in `perf-baseline.md` and must not be repeated by whoever implements this phase.

**SHIPPED AND VERIFIED 2026-07-16** — see `docs/perf-baseline.md` "Phase 4" section for the full verification writeup (network evidence, the one deliberate deviation from this doc's suggested "ref-guard" option, and a follow-on opportunity found but out of scope).

## User's ask (verbatim intent)
After a PM logs in, the **Operational Tower** (the `/dashboard` route — confirmed via `defaultRouteForRole()` in `frontend/src/lib/api.ts`, which sends role `delivery_manager` to `/dashboard`; the sidebar labels it "Operational Tower" in `components/bsg/Shell.tsx`) must render with **zero added delay** — it is the first thing the user sees and must not be delayed for any other page's sake. **Only after** the Operational Tower has loaded should the app fetch the Quality Intelligence (QI) page's data in the background, so that when the user later navigates to `/quality` it's already warm.

Two scoping decisions already confirmed with the user (do not re-litigate):
1. **Prefetch only the ONE default project** the QI page would show first (`projects[0]`, same resolution the `/quality` route itself uses) — NOT all ~28 projects. Project-switching is already fast (~1.3 s post-Phase-2A) so there is no need to warm more than the first project.
2. **Keep the existing 5-minute `staleTime`** (`STALE_TIME_MS` in `frontend/src/lib/queries/keys.ts`) as-is for the `quality-page` query — no change requested.

## Grounding facts (verified by reading the code, not assumed)
- `frontend/src/routes/dashboard.tsx` (the Operational Tower) is **100% static** today — it renders from hardcoded imports in `frontend/src/lib/bsg/data.ts` (`kpis`, `riskTrend`, `qualityTrend`, etc.), with **zero** `useQuery`/`fetch`/loader calls. So today nothing can delay it — but the implementation must not assume this stays true forever (the point of "after ops tower loads" as an explicit gate is to be safe if the dashboard becomes data-driven later). Do not make the prefetch a `loader` on the dashboard route — a loader runs BEFORE the component renders and could delay first paint if the dashboard ever gains real data fetching. It must be a post-mount effect.
- Phase 1B already added, in `frontend/src/components/AuthProvider.tsx`, a `useEffect` that fires `queryClient.prefetchQuery(projectsQueryOptions)` the moment `isAuthenticated` flips true. This means the **projects list is already warm** by the time the dashboard mounts — Phase 4 does NOT need to re-fetch it, just `ensureQueryData` it (cheap, cache hit) to resolve `projects[0].id`.
- Reusable pieces that already exist — reuse them, don't duplicate:
  - `frontend/src/lib/queries/delivery.ts` — `projectsQueryOptions`.
  - `frontend/src/lib/queries/quality.ts` — `qualityPageQueryOptions(projectId)`, and the existing `loadQualityRouteData(queryClient, projectId)` helper (used by the `/quality` route's own loader/mount-effect from Phase 1B) — Phase 4 should add a **new**, small helper here (e.g. `prefetchDefaultQualityPage`) rather than repurposing `loadQualityRouteData`, because that function's contract is "given a possibly-undefined projectId, warm exactly that" — Phase 4 needs "resolve the default project id, THEN warm it," which is a different (if related) operation and a different call site (dashboard mount vs quality-route loader).
  - `frontend/src/lib/api.ts` — `canAccessPath(role, path)` for an explicit role guard, and `defaultRouteForRole`.
- `AuthProvider` wraps the router's `Outlet` and never remounts on client-side navigation (established in Phase 1B) — so a dashboard-mount effect fires once per dashboard visit, which is the right granularity (not once per app load).

## Design

### 1. New query helper — `frontend/src/lib/queries/quality.ts`
Add `prefetchDefaultQualityPage(queryClient: QueryClient): Promise<void>`:
- `const projects = await queryClient.ensureQueryData(projectsQueryOptions).catch(() => [])` — cache hit in the common case (already warmed by `AuthProvider`).
- If `projects.length === 0`, return (no-op).
- `await queryClient.prefetchQuery(qualityPageQueryOptions(projects[0].id))` — wrapped so a failure here is swallowed (background warm-up, not a data source — same posture as `loadQualityRouteData`).
- Unit-test: (a) calls prefetch with `projects[0].id` when projects exist, (b) no-ops when projects is empty, (c) swallows a rejected `ensureQueryData`/`prefetchQuery`.

### 2. New hook — `frontend/src/hooks/usePrefetchQualityIntelligence.ts`
A hook, not inline dashboard code, so it's independently testable and reusable if another "ops-tower-first" page needs the same pattern later.
- Takes no args (reads `useQueryClient()` internally) or optionally accepts the role for the guard — check how other hooks in this codebase access the current user/role (e.g. `useAuthStore`) and follow that convention.
- Guard: only run if the current user's role can access `/quality` (`canAccessPath(role, "/quality")`) — defensive, since today only `delivery_manager` lands on `/dashboard`, but this keeps the hook correct if that ever changes.
- Scheduling: on mount, schedule the prefetch via `requestIdleCallback` (with a `setTimeout(fn, 200)` fallback for environments without it — check if the codebase already has a small utility for this pattern before writing a new one; if not, a local inline fallback is fine, don't over-abstract) so it runs after the browser has finished the dashboard's own paint/layout work, not competing with it.
- Must fire **only once per dashboard mount** (a ref-guard or effect-dependency array that doesn't re-trigger on unrelated re-renders — mirror the "only ever fires once" reasoning already documented in `AuthProvider.tsx`'s existing prefetch effect).
- Cleanup: if `requestIdleCallback` is used, cancel it (`cancelIdleCallback`) on unmount in case the user navigates away from the dashboard before it fires; if the `setTimeout` fallback is used, `clearTimeout` on unmount.

### 3. Wire it in — `frontend/src/routes/dashboard.tsx`
One line inside the `Dashboard()` component: `usePrefetchQualityIntelligence();`. Do NOT add a route `loader` for this (see "must be a post-mount effect" above).

## Verification (hard gates)
1. **Ops tower is not delayed**: using resource-timing / network-log inspection (as done for Phase 1B), confirm the `quality-page` prefetch request's `startTime` is AFTER the dashboard route's own paint/DOMContentLoaded — i.e., it should not appear anywhere near the top of the network waterfall for `/dashboard`, it should trail it by roughly one idle-callback tick.
2. **QI is warm after**: log in as PM, land on `/dashboard`, wait briefly (long enough for the idle prefetch + the ~1.3 s `quality-page` fetch to complete), then navigate to `/quality`. Confirm via browser resource timing / backend request log that **no new `quality-page` HTTP request fires** on that navigation (served from the React Query cache) and the page shows data immediately (no loading skeleton flash).
3. **No regression to the existing `/quality` direct-load path** (Phase 1B's own loader/mount-effect) — e.g., a user who navigates straight to `/quality` without visiting `/dashboard` first must still get the existing (already-fast) parallel-fetch behavior, unaffected by this change.
4. `usePrefetchQualityIntelligence`/`prefetchDefaultQualityPage` unit tests pass; `npm run test`, scoped `eslint`, and `tsc --noEmit` (scoped diff, matching the standard used for prior phases) are clean.
5. Full frontend suite still green (no count regression from the 89 baseline established in Phase 1B / streaming work).

## Explicit non-goals (do not do these — already decided)
- Do NOT prefetch more than the single default project's `quality-page`.
- Do NOT change `STALE_TIME_MS` / the `quality-page` query's `staleTime`.
- Do NOT re-attempt backend-side parallelization of independent loaders (proven regression, Phase 2A revert).
- Do NOT touch the agent-query/streaming code — this phase is frontend-only, dashboard/QI prefetch scope.
- Do NOT make the dashboard route's data-loading (currently none) a blocking `loader` for this prefetch.

## DONE means
Idle-scheduled prefetch fires after the Operational Tower's own render, warms exactly the default project's `quality-page` (verified network evidence, not just code review), does not alter the dashboard's own load time (before/after resource-timing comparison), makes a subsequent `/quality` visit within the 5-minute stale window a cache hit with no visible loading state, and all test/lint/typecheck gates are clean.
