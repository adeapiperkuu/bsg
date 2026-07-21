# Quality Intelligence Performance Baseline (Phase 0)

Baseline captured **2026-07-15** against the running dev backend (`http://127.0.0.1:8000/api/v1`, uvicorn --reload) and the **remote** Supabase Postgres (AWS eu-west-1), using the harness in `backend/scripts/bench_perf.py`. This is the "before" snapshot for `docs/PERF_IMPLEMENTATION_PLAN.md`; re-run the same command after each phase and append an "After" section here (Phase 3 does this).

Captured as PM dev account `pm@bsg.dev` (role `delivery_manager`), against project `d0974a78-7c25-4c3d-97d3-32cbee98a9b5`.

## How to run

```bash
# from repo root
backend/.venv/Scripts/python.exe backend/scripts/bench_perf.py

# options
backend/.venv/Scripts/python.exe backend/scripts/bench_perf.py --base-url http://127.0.0.1:8000/api/v1 --n 5 --agent-n 3
```

Requires the backend dev server already running on the target `--base-url` (see repo-root `.claude/launch.json`, config `backend`, or start manually:
`backend/.venv/Scripts/python.exe -m uvicorn app.main:app --reload --port 8000 --app-dir backend`).

Credentials come from `BENCH_PM_EMAIL` / `BENCH_PM_PASSWORD` env vars, defaulting to the documented dev PM account (`pm@bsg.dev` / `bsg-dev-2026`). The script only talks HTTP to the running server — it never reads `.env` or prints secrets (passwords, cookies, CSRF token are never printed). Exit code is non-zero if any request returns a non-2xx status.

## Summary table (primary captured run, n=5, agent n=3)

All times in milliseconds. This is the final, definitive run against the finished script (two earlier full runs and two flag/edge-case smoke runs are folded into the reproducibility appendix below).

| Endpoint | min | p50 | p95 | max | n |
|---|---:|---:|---:|---:|---:|
| `GET /me` | 1558.6 | 1608.7 | 1966.3 | 1973.4 | 5 |
| `GET /projects` | 1636.2 | 1690.2 | 1787.2 | 1810.0 | 5 |
| `GET /projects/{id}/quality-page` (cold, 1st call) | 2932.7 | 2932.7 | 2932.7 | 2932.7 | 1 |
| `GET /projects/{id}/quality-page` (repeat) | 2677.4 | 2833.9 | 4217.2 | 4454.3 | 4 |
| `POST /agent-queries` (quality_intelligence_agent) | 17905.7 | 18296.4 | 20547.3 | 20797.4 | 3 |

**First-load waterfall** (sequential `/me` → `/projects` → `/quality-page`, single run, the number Phase 1B must break):

| Step | ms |
|---|---:|
| `/me` | 1662.1 |
| `/projects` | 1683.7 |
| `/quality-page` | 2526.7 |
| **SUM** | **5872.5** |

## Raw per-sample ms (primary captured run)

```
Login: 1651.3 ms

Waterfall (single sequential run):
  /me            1662.1 ms
  /projects      1683.7 ms
  /quality-page  2526.7 ms
  SUM            5872.5 ms

GET /me         : 1558.6, 1608.7, 1596.5, 1937.7, 1973.4
GET /projects   : 1689.3, 1695.8, 1690.2, 1810.0, 1636.2
GET /quality-page (project d0974a78-7c25-4c3d-97d3-32cbee98a9b5):
  run 1 (cold)  : 2932.7
  run 2 (repeat): 2677.4
  run 3 (repeat): 2873.6
  run 4 (repeat): 2794.1
  run 5 (repeat): 4454.3

POST /agent-queries (quality_intelligence_agent, query_text="What are the top
quality risks on this project?"):
  run 1: 20797.4 ms (status 200)
  run 2: 17905.7 ms (status 200)
  run 3: 18296.4 ms (status 200)
```

All 16 HTTP requests in this run returned `200 OK` (script exit code `0`).

## Reproducibility appendix (all runs captured while building the harness)

The harness was run 5 times total while building and smoke-testing it (3 full `--n 5 --agent-n 3` runs, 2 quick `--n 1 --agent-n 0` edge-case checks). Every run returned exit code `0` (all 2xx). Pooling all samples gives an honest variance picture instead of anchoring on one lucky/unlucky run:

**Waterfall SUM across all 5 runs:** 5872.5, 6042.5, 6165.4, 7904.0, 9240.2 ms → range **5.9–9.2 s**, average **~7.0 s**, right in line with the plan's ~7.5 s estimate.

**Agent query across all 3 full runs (9 samples):** 17905.7, 18296.4, 20406.9, 20797.4, 22275.9, 26123.0, 26437.2, 26579.0, 34349.5 ms → min **17.9 s**, median **22.3 s**, mean **23.7 s**, max **34.3 s**. The plan's ~19 s is close to the best case observed (17.9–20.8 s in the cleanest run), not the typical case — see Note 4 below.

**`/me` and `/projects`** were consistently ~1.5–2.0 s across every run, never showing warm-up. **`/quality-page`** was consistently ~2.5–4.5 s with no cold-vs-repeat pattern (occasional repeat samples exceeded the cold sample).

## Sanity check vs. plan's expected baseline

| Scenario | Plan's expected baseline | Measured (all runs pooled) |
|---|---|---|
| `/me` | ~1.6–1.8 s | ~1.5–2.0 s, p50 ~1.6 s — matches |
| `/projects` | ~1.7 s | ~1.6–1.8 s, p50 ~1.7 s — matches exactly |
| `/quality-page` | ~2.5–3.0 s, no warm-up speedup | ~2.5–4.5 s, cold ≈/< repeat — matches (no warm-up confirmed) |
| First-load waterfall | ~7.5 s | 5.9–9.2 s across 5 runs, avg ~7.0 s — matches |
| Agent query | ~19 s | 17.9–34.3 s across 9 samples, median 22.3 s, best-case run 17.9–20.8 s — matches at best case, runs hotter on the tail |

Nothing here is "wildly different" (no order-of-magnitude gaps); investigated below.

## Notes / findings (for whoever picks up Phase 1–3)

1. **No connection warm-up, confirmed.** In the primary run, `quality-page` repeat #4 (4454.3 ms) was well above the cold call (2932.7 ms) — a repeat was *slower* than the cold call. This directly corroborates the plan's root cause: `NullPool` opens a fresh DB connection per request, so there is no reuse benefit regardless of call order. Phase 1A's pooling change is the fix to look for here (repeats should get measurably faster and less variable once a real pool is in place).

2. **OKA is a full no-op in this dev environment today.** `backend/app/agents/quality_intelligence/oka_client.py` short-circuits both `retrieve_lessons` and `write_lesson` with `if not settings.oka_base_url: return [] / None` — no HTTP call, no latency, no log line. `Settings.oka_base_url` (`backend/app/core/config.py`) defaults to `None` and the repo-root `.env` does not set `OKA_BASE_URL`. Backend logs during every agent run show **zero** `oka`-related log lines and no outbound calls besides `api.openai.com`. This means:
   - The plan's stated root cause ("OKA HTTP call... invoked twice, 30s timeout... serialized") is **not currently contributing any latency** in this environment — it's already free.
   - Phase 2B's "dedupe OKA to one call + cut timeout to ≤3s" work will show **zero measurable improvement** against this dev baseline (there's nothing to save here); it will only matter in an environment where `OKA_BASE_URL` is actually configured. Worth confirming in whichever environment Phase 2B is validated against.

3. **LLM intent routing is off by default, confirmed.** `Settings.llm_intent_routing` defaults to `False` and `.env` does not set `LLM_INTENT_ROUTING`, so `classify_intent_llm()` (`backend/app/agents/quality_intelligence/query_handler.py`) short-circuits to `None` immediately and falls back to the free keyword-based `classify_intent()`. Backend logs show exactly **2** sequential `POST https://api.openai.com/v1/chat/completions` calls per agent query (not 3) across every run — consistent with only `reason_root_cause` + the final synthesis call executing, no intent-classification LLM call. So Phase 2B requirement #1 ("stop intent LLM from adding serial latency, e.g. by defaulting it off") is **already satisfied** by current config in this environment; the only remaining serial-latency lever from the plan's list is requirement #4 (investigate merging reasoning + synthesis into one call) — that merge is where 100% of today's agent latency lives, since OKA and intent-LLM both cost zero here.

4. **Agent latency is noisy and often runs hotter than the plan's ~19 s figure**, even with only 2 (not 3) sequential LLM calls and zero OKA overhead. Across 9 samples from 3 full runs: **17.9 s – 34.3 s**, median **22.3 s**. Investigated before finalizing: every sample returned `200 OK` with no retries or errors visible in server logs (each query logged exactly 2 clean `api.openai.com` round trips, nothing else, no warnings). This is real, externally-driven latency variance from the live OpenAI API (prompt/response size, model queueing, network jitter) — not a harness bug and not evidence of a serialization bug beyond what the plan already documents. Treat ~19 s as the good-case number (the cleanest run measured 17.9–20.8 s); ~22 s median is the more realistic "typical" number today, with occasional tail spikes past 30 s.

5. **Waterfall varies run to run (5.9–9.2 s across 5 runs) but averages ~7.0 s, close to the plan's ~7.5 s estimate.** The variance tracks remote-DB round-trip jitter to the eu-west-1 Supabase instance, not anything the harness does differently between runs (same 3 sequential legs every time: `/me` → `/projects` → `/quality-page`). Either way, the Phase 1B fix (parallelize `/projects` + `/quality-page`) and Phase 1A fix (kill the ~1–1.5 s fixed per-request tax) remain squarely justified — and Phase 1A's pooling should also shrink this run-to-run variance, not just the average.

## After (Phase 1A: transaction-pooler pool + RLS reapply) — captured 2026-07-15

Same harness, same host/project, captured immediately after: (1) `.env` `DATABASE_URL` port switched `5432` → `6543` (transaction pooler), (2) `backend/app/db/session.py`'s transaction-pooler branch switched from `NullPool` to a persistent pool (`pool_size=10, max_overflow=10, pool_pre_ping=True, pool_recycle=1800`), (3) `backend/app/db/rls.py`'s `after_begin` reapply hook (per-task JWT-claims contextvar reapplied on every new transaction, closing the mid-request-commit gap), and (4) one perf fix found *while verifying* 1A: `set_rls_context`/`_reapply_rls_on_begin` combined `set_config('request.jwt.claims', ...)` + `SET LOCAL ROLE authenticated` into a single `select set_config(...), set_config('role', ..., true)` round trip (semantically identical, verified against the live DB) — each round trip to the remote eu-west-1 DB costs ~170–190ms regardless of pooling, so this alone saves one full round trip per transaction.

| Endpoint | Before p50 | After p50 | Change |
|---|---:|---:|---:|
| `GET /me` | 1608.7 ms | 900.1 ms | **−44%** |
| `GET /projects` | 1690.2 ms | 875.6 ms | **−48%** |
| `GET /quality-page` (repeat) | 2833.9 ms | 2173.2 ms | **−23%** |
| First-load waterfall (sum) | ~5872–9240 ms (avg ~7.0s) | 4327.7 ms | **−38% to −53%** |

Raw "after" run (n=5, clean — no concurrent DB load):
```
Logged in as pm@bsg.dev in 894.3 ms.

Waterfall (single sequential run):
  /me            902.4 ms
  /projects      902.6 ms
  /quality-page  2522.8 ms
  SUM           4327.7 ms

GET /me         : 1114.2, 909.7, 888.5, 900.1, 889.9   (min 888.5, p50 900.1, p95 1073.3, max 1114.2)
GET /projects   : 875.6, 885.6, 916.4, 865.6, 849.0    (min 849.0, p50 875.6, p95 910.2,  max 916.4)
GET /quality-page (project d0974a78-7c25-4c3d-97d3-32cbee98a9b5):
  run 1 (cold)  : 2406.2
  run 2 (repeat): 2280.8
  run 3 (repeat): 1933.2
  run 4 (repeat): 2471.9
  run 5 (repeat): 2065.6
  (repeat min 1933.2, p50 2173.2, p95 2443.2, max 2471.9)
```
All 2xx.

### Why the plan's literal "/me ≤ 400ms" target was not reached (root-caused, not hand-waved)

Isolated measurement (a script bypassing HTTP/JWT entirely, hitting only the DB layer) proved the pool mechanism itself works exactly as designed: a cold connection open through the transaction pooler took ~1.7s; a pooled/reused connection running a single query took ~510–540ms. That is the real, verified win from Phase 1A — connection **setup** cost is gone on warm paths.

What's left is **per-query network RTT**, not connection overhead: every round trip to the remote Supabase instance (AWS eu-west-1) costs ~170–190ms regardless of whether the connection is pooled, and `GET /me` issues several serialized round trips (`select(User)`, the combined RLS `set_config`, `pool_pre_ping`'s own check, `session.get(Organisation)`). At ~3–4 unavoidable serial round trips × ~180ms, the floor is ~550–900ms — consistent with the measured ~900ms p50, and *not* reachable at ≤400ms without reducing the **number** of serial round trips per request (e.g. joining the org lookup into the user query, or parallelizing independent loaders) — that is Phase 2A's scope (`backend/app/services/quality.py`, `backend/app/db/parallel.py`), not Phase 1A's. Phase 1A's job — make connections reusable without breaking RLS — is done and verified; the remaining gap to ≤400ms is a query-count problem, not a pooling problem.

### Burst test (Phase 1A DONE criterion)

40 concurrent `GET /projects/{id}/quality-page` as PM (`asyncio.gather`, one `httpx.AsyncClient` per task, shared auth cookies): **all 40 returned `200 OK`**, zero `EMAXCONNSESSION` / prepared-statement / "another operation in progress" / asyncpg / SSL errors, confirmed both in the client responses and in the backend server log. Latency degrades under this concurrency (min 5.0s / avg 7.6s / max 9.8s per request, for pool_size=10 + max_overflow=10 = 20 connections serving 40 concurrent multi-query requests) — expected queueing behaviour, not a connection-error failure mode; a Phase 3 tuning pass could revisit pool sizing if this concurrency level is real-world expected load.

## After (Phases 1B, 2A, 2B, Streaming) — Final results, captured 2026-07-16

Each phase was implemented and then **independently verified** (numbers below are re-measured on a clean backend process, not taken on faith). Two attempts were **reverted** because measurement disproved them — recorded here honestly so nobody retries them.

### 1B — Frontend first-load de-waterfall (SHIPPED)
`frontend/src/routes/quality.tsx` gained a route `loader` (+ a mount-effect fallback for cold SSR hydration) that fires `projects` and `quality-page` via `queryClient.ensureQueryData` in parallel; projects is prefetched on auth (`AuthProvider.tsx`). **Verified live**: on a cold `/quality?projectId=…` load, `/projects` and `/quality-page` now start **~1–2 ms apart** (was ~1.8 s apart). `/me` still gates the pair (auth bootstrap). 89 frontend tests pass.

### 2A (parallelize quality-page loaders) — REVERTED (proven regression)
Ran the ~6 `build_quality_page` loaders concurrently, each on its own pooled session. Controlled A/B on one process: sequential `build_quality_page.total` **~865 ms** vs parallel **~1265 ms** (sem=4) / **~900 ms** (sem=12) — a regression or, at best, break-even. Root cause: each parallel loader opens a new pooled connection that pays `pool_pre_ping` + the RLS `after_begin` reapply (~360 ms setup) before its cheap ~180 ms query; on a remote DB, per-connection setup swamps the parallelism gain when the queries are cheap. **The doc's earlier "parallelize independent loaders" suggestion (Note 5, §"Why /me…") is therefore wrong for this cost model — do not do it.** Fully reverted (`app/db/parallel.py` removed).

### 2A-corrected — reduce round trips (SHIPPED)
`build_quality_page` (`backend/app/services/quality.py`) rewritten to collapse the ~5 independent per-table SELECTs into **one CTE round trip** (`json_agg`) on the already-warm request session (RLS already applied, no extra connection setup). Verified:
| Metric | Before (1A) | After 2A-corrected |
|---|---:|---:|
| `build_quality_page.total` | ~865 ms | **~270 ms** |
| `/quality-page` p50 | ~1770 ms (2834 ms at baseline) | **~1290 ms** |

Response proven **byte-identical** across 3 projects (captured old vs new JSON, `diff` empty). 93 quality/db tests pass.

### 2B (merge reasoning + synthesis LLM calls) — REVERTED (proven slower)
A single-call merge measured **~24.9 s → ~33.1 s** (slower). Cause: the reasoning half frequently fails grounding validation for this evidence pack and falls back to a full synthesis anyway; merging just makes each rejected attempt generate the whole answer first. Kept the two-call flow. Shipped only the harmless **prod-hardening** (dedupe the double OKA call; run `classify_intent_llm` concurrently when enabled) — **zero dev-perf effect** here (OKA inert, intent off), correct for configured environments.

### Agent SSE streaming (SHIPPED) — the real agent win
New `POST /api/v1/agent-queries/stream` (SSE, mirrors the repo's `knowledge/ask/stream` pattern) + `LLMClient.stream_structured` + frontend `streamAgentQuery` / `useAgentQuery` / `AskQualityAgentPanel`. Total agent time is unchanged (reasoning gates synthesis), but the ~18–25 s blank wait is replaced with continuous feedback. **Verified via independent SSE client**: `status:gathering_evidence` @**1.0 s** → `status:reasoning` @8.8 s → `status:writing` @15.6 s → first answer `delta` @**16.5 s** → 265 token deltas → `done` @25.3 s carrying the full grounded `AgentQueryRead`. Non-streaming endpoint unchanged. Backend suite **644 passed / 58 skipped**; frontend 89 tests + `tsc` clean.

### End-to-end (combined, verified through the real UI as PM)
| Scenario | Baseline | Final |
|---|---:|---:|
| First load (cold) | ~7.5 s | **~3.5–4.7 s** (waterfall gone; each request faster) |
| Project switch | ~2834 ms | **~1290 ms** |
| `/me`, `/projects` | ~1.6–1.7 s | **~0.9 s** |
| `build_quality_page` | ~865 ms | **~270 ms** |
| Agent query | ~18–25 s blank | same total, now **status @1 s + answer streaming @~16 s** |

## Phase 4 — Post-login idle prefetch of Quality Intelligence data (SHIPPED, verified 2026-07-16)

Frontend-only. New `prefetchDefaultQualityPage(queryClient)` in `frontend/src/lib/queries/quality.ts` (resolves `projects[0].id` from the already-warm projects cache, then `prefetchQuery`s only that project's `quality-page` — never all ~28) and a new `usePrefetchQualityIntelligence()` hook (`frontend/src/hooks/usePrefetchQualityIntelligence.ts`) that schedules it via `requestIdleCallback` (`setTimeout(200ms)` fallback), gated on `canAccessPath(role, "/quality")`. Wired into `Dashboard()` (`frontend/src/routes/dashboard.tsx`) as a single hook call — not a route `loader`, so it structurally cannot delay the dashboard's own render.

**One deliberate deviation from the plan's suggested design:** the plan offered either a ref-guard or effect-cleanup for "fire once" semantics. A ref-guard was implemented first, then reverted after tracing through React Strict Mode's dev-only double-invoke (mount → cleanup → mount): the first invocation's cleanup would cancel its own idle callback, then the ref would permanently block the second (surviving) invocation from ever scheduling one — silently disabling the whole prefetch under Strict Mode. This app doesn't currently use `StrictMode` (checked — no hits), so the bug is latent, not live, but the cleanup-based approach (no ref) is correct under both regimes and is what shipped. Same idempotency safety net as `loadQualityRouteData` covers any edge re-invocation (`ensureQueryData`/`prefetchQuery` are cache-key-deduped and `staleTime`-aware).

**Verification (network evidence, not just code review):**
- Warm re-auth trace: `/me` 183→1246 ms (gates dashboard's render) → `/projects` 1250→2284 ms (Phase 1B's existing `AuthProvider` prefetch) → **`/quality-page` 2286→4108 ms** — starts a full second-plus after the dashboard could have painted, confirmed via the dashboard's own KPI content (`ACTIVE PROJECTS`, etc.) already being visible by that point. Dashboard has zero data fetches of its own (static `lib/bsg/data.ts` imports), so nothing on its render path can be delayed by this in principle, and the measurement confirms it in practice.
- **Decisive test**: from a loaded `/dashboard`, clicked the "Quality Intelligence" nav link (client-side `Link`, confirmed `/quality` is not one of the existing hover-prefetch's paths in `nav-prefetch.ts` — `/delivery`, `/governance`, `/admin/projects` only — so this test wasn't confounded by that separate mechanism). Result: **zero new API requests fired**, page showed real data (`GOLD-SET ACCURACY`, drift alerts) instantly, no loading skeleton. Screenshot-confirmed.
- **No regression to the direct-visit path**: hard-navigating straight to `/quality?projectId=<id>` (bypassing the dashboard entirely) still shows the Phase 1B parallel-fetch behavior — `/projects` and `/quality-page` start **2 ms apart**, identical to Phase 1B's own original result.
- **Switching to a non-default project** from a dashboard-warmed `/quality` still correctly fires a real fetch (~1.4 s) — the prefetch only short-circuits the one default project, as scoped.
- Tests: 9 new (4 for `prefetchDefaultQualityPage`, 5 for the hook incl. an explicit `requestIdleCallback`-branch test, jsdom has no native `requestIdleCallback` so the natural test run exercises the `setTimeout` fallback). Full suite **98/98 passing** (was 89). Scoped `eslint` clean (2 prettier issues introduced and fixed during development). `tsc --noEmit` diffed against the pre-existing error set — zero overlap with any Phase 4 file.

**Finding, not a regression, out of scope for this phase:** hard-navigating to bare `/quality` (no `?projectId=` yet) shows a ~890 ms gap between `/projects` and `/quality-page` — because the project id isn't known until `/projects` resolves and the URL is replaced, so the two calls genuinely can't overlap on that specific cold path. This is pre-existing Phase-1B-era behavior, not something Phase 4 touches or regresses (confirmed by reproducing the same ~2 ms gap when a `projectId` is already in the URL, matching Phase 1B's original result exactly). Worth a future micro-phase if it matters: seed the loader from a synchronously-available cached `projects` entry before the network resolves.

## Files

- Harness: `backend/scripts/bench_perf.py` (idempotent, safe to re-run; add `--n`/`--agent-n`/`--base-url` as needed)
- Plan: `docs/PERF_IMPLEMENTATION_PLAN.md`
- Login route referenced: `backend/app/api/routes/auth.py` (`POST /auth/login`, body `{"email", "password"}`, sets `access_token`/`refresh_token`/`csrf_token` cookies via `backend/app/core/cookies.py`; CSRF enforced by `backend/app/core/csrf.py` for mutating requests)
