# Delivery Performance Agent — Operational Data Sources

**Status:** Implemented in Phase 15.2  
**Scope:** Deterministic operational ingestion that feeds the root-cause engine. No AI reads of these tables, no PM action planner, no daily briefing wiring.

## Purpose

Operational signals explain *why* confidence changed. They are inputs to [`delivery_root_cause_service.py`](../backend/app/agents/delivery/services/delivery_root_cause_service.py) via [`DbOperationalSignalProvider`](../backend/app/agents/delivery/services/operational_signals.py). AI narratives must ground in root-cause snapshots only — never invent absenteeism, review queues, or capacity from prose.

```text
Ingest (DM/super_admin)
  → validated upsert into operational tables
  → DbOperationalSignalProvider derives 0–100 severity
  → root-cause allocate_confidence_loss (overrides proxies when present)
```

## Tables

Migration: `supabase/migrations/20260720140000_delivery_operational_data_sources.sql`

| Table | Grain | Key fields |
|---|---|---|
| `delivery_timesheet_entries` | project+team+day | `hours_logged`, `expected_hours` |
| `delivery_absenteeism_snapshots` | project+day | `absent_fte`, `planned_fte`, `absence_rate_pct` |
| `delivery_review_queue_snapshots` | project+day | `pending_count`, `avg_turnaround_hours`, `sla_breach_count` |
| `delivery_backlog_queue_snapshots` | project+day | `item_count`, `aging_item_count`, `oldest_item_age_days` |
| `delivery_capacity_snapshots` | project+day | `planned_capacity_hours`, `available_capacity_hours` |
| `delivery_team_availability_snapshots` | project+team+day | `available_headcount`, `planned_headcount`, `available_fte` |

Shared: `source_type` (`manual|import|event|derived|correction`), optional `source_reference` / `notes`, actor columns, timestamps.

RLS matches Phase 2 ops tables: DM ALL (own org), leadership SELECT, super_admin ALL; **no client**.

## Severity formulas (deterministic)

| Source | Severity |
|---|---|
| Timesheet | `underfill% = (expected − logged) / expected × 100` when expected known |
| Absenteeism | `min(100, absence_rate_pct × 2)` |
| Review queue | pending×4 (cap 40) + turnaround overrun (cap 40) + SLA×5 (cap 20) |
| Backlog | size×0.5 (cap 35) + aging×4 (cap 40) + oldest_age×0.5 (cap 25) |
| Capacity | `(planned − available) / planned × 100` |
| Team availability | `(planned − available) / planned × 100` headcount |

Capacity root-cause factor uses `max(capacity_shortage, team_unavailability, timesheet_underfill)` when any are present.

## Root-cause mapping

| Operational signal | Root-cause factor |
|---|---|
| Review queue | `review_turnaround` (overrides bottleneck keyword proxy) |
| Backlog queue | `queue` (overrides bottleneck/shortfall proxy) |
| Capacity + availability + timesheet | `capacity` (overrides headcount-decline proxy) |
| Absenteeism | `absenteeism` (was unavailable in 15.1) |
| Dependency / scope | Still reserved (provider returns `None`) |

## Ingestion rules

- Future UTC dates rejected (`FUTURE_SNAPSHOT_DATE`)
- Idempotent upsert on natural key; unchanged repeat is a no-op
- Changed repeat marks `source_type=correction` and audits
- Advisory transaction lock per logical key
- Clears Delivery portfolio + root-cause analytics caches on change

Service: `backend/app/agents/delivery/services/operational_ingestion_service.py`  
Schemas: `backend/app/agents/delivery/schemas/operational_data.py`

## APIs (internal)

Read: delivery_manager, bsg_leadership, super_admin  
Write: delivery_manager, super_admin  
Client: **403**

| Method | Path |
|---|---|
| GET/POST | `/delivery/projects/{id}/timesheets` |
| GET/POST | `/delivery/projects/{id}/absenteeism` |
| GET/POST | `/delivery/projects/{id}/review-queue` |
| GET/POST | `/delivery/projects/{id}/backlog-queue` |
| GET/POST | `/delivery/projects/{id}/capacity` |
| GET/POST | `/delivery/projects/{id}/team-availability` |

## Compatibility

- Phase 15.1 snapshots and APIs unchanged
- Without operational rows, root-cause falls back to 15.1 proxies / unavailable factors
- `StubOperationalSignalProvider` remains for tests that need empty ops context

## Deferred

- External timesheet/HR connectors (beyond manual/import API)
- Dependency graph and scope-volatility event sources
- Phase 15.6 (dashboard redesign)
- Phases 15.3–15.5 are implemented separately (PM actions, operational briefing, knowledge evidence)

