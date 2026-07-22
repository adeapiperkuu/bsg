# KPI Semantic Layer (Phase 18.1)

The KPI Semantic Layer is the single source of truth for platform metric
definitions, versioned calculation metadata, and reusable typed calculators.

## Goals

- One registry for Delivery, Governance, Quality, Workforce, Client Intelligence,
  Operational Tower, and future agents
- Typed Python calculators (no declarative formula DSL)
- Immutable version history for future time-series compatibility
- Additive APIs that do not change existing dashboard DTOs or UI behavior

## Package layout

| Path | Role |
|------|------|
| `backend/app/kpis/registry.py` | Versioned KPI + calculator registry, DAG validation |
| `backend/app/kpis/contracts.py` | Immutable registration / evaluation contracts |
| `backend/app/kpis/formulas.py` | Shared pure helpers used by agents and providers |
| `backend/app/kpis/thresholds.py` | Org → global → code-default threshold resolver |
| `backend/app/kpis/evaluation.py` | RBAC-aware evaluate / metadata builders |
| `backend/app/kpis/catalog.py` | DB-enriched catalog with in-code fallback |
| `backend/app/kpis/adapters.py` | Compatibility helpers for existing agent services |
| `backend/app/kpis/providers/` | Domain calculator registrations |
| `backend/app/api/routes/kpis.py` | `/api/v1/kpis` HTTP surface |
| `supabase/migrations/20260721150000_kpi_semantic_layer.sql` | Catalog tables, RLS, seed rows |

Existing `metric_configurations` remains the override store for thresholds and
client visibility. Do not duplicate that contract.

## APIs

All routes use the standard `DataResponse` / `ListResponse` envelopes.

| Method | Path | Purpose |
|--------|------|---------|
| `GET` | `/api/v1/kpis` | Authorized catalog (`owner_agent` filter optional) |
| `GET` | `/api/v1/kpis/{kpi_id}` | Definition + versions/dependencies |
| `GET` | `/api/v1/kpis/{kpi_id}/calculation` | Formula, sources, thresholds, explainability |
| `POST` | `/api/v1/kpis/{kpi_id}/evaluate` | Evaluate one KPI |
| `POST` | `/api/v1/kpis/evaluate` | Batch evaluate (`kpi_ids`) |

Evaluate request fields:

- `project_id` / `org_id` — scoped from the caller; non-admins cannot supply another org
- `version` — optional explicit semantic version
- `as_of` — historical evaluation; without an explicit `version`, returns `no_data`
- `inputs` — optional pure-formula inputs (skips project requirement when provided)
- `include_explainability` — clients only receive summary text

## Adding a KPI for a future agent

1. Implement a pure calculator in `backend/app/kpis/providers/<agent>.py`.
2. Register a `RegisteredKpi` with a **new** `calculator_key` ending in `.vN`.
   Never reinterpret an existing calculator key.
3. Declare dependencies with `KpiDependencySpec` (must remain a DAG).
4. Call `register(...)` from `register_all_providers`.
5. Add an additive migration row to `kpi_definitions` / `kpi_definition_versions`
   (and `kpi_dependencies` when needed).
6. Add unit + API tests proving numeric parity with the agent’s previous formula.
7. Optionally adopt the shared helper from `app.kpis.adapters` / `formulas` in the
   agent service so dashboards and `/kpis/evaluate` stay aligned.

No core registry changes are required for new agents.

## Versioning rules

- `kpi_definition_versions` rows are immutable.
- Deprecate with `compatibility_status=deprecated|historical` and `effective_to`.
- Historical reads that cannot select a compatible version must return `no_data`,
  never silently apply current semantics.
- Optional `kpi_observations` stores provenance for future writers; dashboard GETs
  do not write observations in Phase 18.1.
- Phase 18.2 adds durable writers, history APIs, and forecasting — see
  [`docs/platform-time-series-engine.md`](platform-time-series-engine.md).

## Permissions

- Catalog visibility uses each version’s `allowed_roles` and `is_client_visible`.
- Clients never receive internal explainability detail beyond `summary`.
- Observation RLS mirrors org/project visibility patterns used elsewhere.
