# Delivery Performance Agent — Root Cause Intelligence

**Status:** Implemented in Phase 15.1  
**Scope:** Deterministic explanation of delivery confidence loss with configurable weights, snapshot persistence, APIs, and dashboard Main Contributors. No timesheet/absenteeism ingestion, PM action planner, AI briefing wiring, knowledge RAG, or full dashboard redesign.

## Architecture

Root-cause intelligence **explains** confidence shortfall. It does not replace Delivery confidence or risk scoring.

```text
Scoring run / POST recalculate
  → load existing signals (throughput, teams, bottlenecks, quality, milestones)
  → load DELIVERY_ROOT_CAUSE weights from metric_configurations
  → analytics/root_cause.py (pure severity + allocation)
  → upsert delivery_root_cause_snapshots + factors
  → GET APIs / Delivery dashboard Main Contributors
```

```mermaid
sequenceDiagram
  participant API
  participant Scoring as scoring_service
  participant Handler as event_handlers
  participant RCA as root_cause_service
  participant Analytics as root_cause_analytics
  participant DB

  API->>Scoring: run_delivery_scoring
  Scoring->>Handler: DeliveryScoredEvent
  Handler->>RCA: safe_recalculate_after_scoring
  RCA->>Analytics: build_factor_signals + allocate
  Analytics-->>RCA: RootCauseBreakdown
  RCA->>DB: upsert snapshot + factors
  API->>RCA: GET project root-causes
  RCA->>DB: read latest snapshot
  RCA-->>API: Main Contributors payload
```

AI modules must ground narratives in stored causes (`root_cause_summary`). They never invent causes. Optional AI `daily_summary` remains unwired (Phase 15.4).

## Formulas

```text
overall_confidence = existing confidence score_pct
confidence_loss = max(0, on_track_threshold - overall_confidence)

raw_i = weight_i × severity_signal_i   # only data_available factors with signal > 0
impact_points_i = -confidence_loss × (raw_i / sum(raw))
impact_percent_i = 100 × |impact_points_i| / confidence_loss
```

Severity bands use configurable point thresholds (`severity_medium_points`, `severity_high_points`, `severity_critical_points`).

## Cause taxonomy (15.1 signal mapping)

| Factor | Evidence today | Phase 15.2 |
|---|---|---|
| review_turnaround | Review/queue-titled bottlenecks | Review queue metrics |
| rework | Quality rework rate | Dedicated rework sheets |
| capacity | Team headcount decline vs throughput | Capacity snapshots |
| absenteeism | Unavailable (`data_available=false`) | Absenteeism series |
| queue | Open bottlenecks + target shortfall | Backlog queue analytics |
| blocked_work | Active bottleneck severity ranks | Richer blocker ages |
| dependency_delays | Unavailable | Dependency graph |
| milestone_slippage | Overdue / warning-window milestones | Unchanged |
| quality_regression | Drift flag / elevated rework | Deeper quality series |
| scope_volatility | Unavailable | Scope change events |

Default weights (normalized to 1.0 at load): review 0.25, rework 0.20, capacity 0.15, queue 0.10, blocked_work 0.10, milestone_slippage 0.08, quality_regression 0.07, absenteeism 0.03, dependency_delays 0.01, scope_volatility 0.01.

Weights live in `metric_configurations.metric_key = delivery_root_cause` (global template + org override). No hardcoded runtime constants beyond code defaults used as fallback.

## Database

Migration: `supabase/migrations/20260720120000_delivery_root_cause_intelligence.sql`

- `delivery_root_cause_snapshots` — one row per `(project_id, snapshot_date)` with `overall_confidence`, `confidence_loss`, `model_version`, `generated_at`
- `delivery_root_cause_factors` — per-factor impact, severity, explanation, `evidence_json`
- RLS: delivery_manager ALL (own org), bsg_leadership SELECT, super_admin ALL; **no client** on raw tables

## APIs

| Method | Path | Roles |
|---|---|---|
| GET | `/delivery/root-causes` | DM, leadership, super_admin |
| GET | `/delivery/root-causes/trends` | DM, leadership, super_admin |
| GET | `/delivery/projects/{id}/root-causes` | Any authenticated user with project visibility |
| POST | `/delivery/projects/{id}/recalculate-root-causes` | DM, super_admin |

### Permissions shaping

- **Leadership / DM:** full factor list + `evidence_json` (why, calculation, affected KPIs, inputs)
- **Client:** high-level only — top contributors, no staffing factors (`capacity`, `absenteeism`), no evidence payloads

## Frontend

`frontend/src/features/delivery/root-cause/`:

- `DeliveryRootCauseSection` — Confidence + Main Contributors panel
- `RootCauseBreakdownCard` — bars + explainability drawer
- `RootCauseTrendChart` / `RootCauseTimeline` / `ImpactDistributionChart` — thin shells for trends/history

Wired into `/delivery` in place of the prior risk `contributing_causes` bar list.

## Performance

- Reads reuse latest same-day snapshot; recalculate on POST or post-scoring hook
- Org analytics cached in-process (~60s TTL); cleared on recalculate with portfolio cache
- Hook failures are isolated (`safe_recalculate_after_scoring`) so scoring persistence is not blocked

## Calculation flow

1. Load scoring thresholds + root-cause weights for the org
2. Load project scoring inputs (same path as Delivery scoring)
3. Merge optional Phase 15.2 operational stubs (`operational_signals.py` — all return `None` today)
4. Build factor severity signals
5. Allocate confidence loss; persist snapshot + factors
6. Dashboard/API read snapshot; AI may consume `root_cause_summary` only

## Deferred (15.2–15.6)

| Phase | Item |
|---|---|
| 15.2 | Timesheets, absenteeism, review queue, backlog queue, capacity history ingestion |
| 15.3 | PM Daily Action Planner |
| 15.4 | Wire `generate_daily_summary` using root-cause grounding |
| 15.5 | Knowledge Agent retrieval into Delivery evidence |
| 15.6 | Full Delivery dashboard redesign beyond Main Contributors |

Stub hook module: `backend/app/agents/delivery/services/operational_signals.py`.

## Compatibility

- Existing `risk_alerts.contributing_causes` and risk formula causes remain unchanged
- Confidence/risk scoring thresholds and Phase 1–3 contracts are untouched
- Clients without snapshots see empty Main Contributors until recalculate/scoring runs
