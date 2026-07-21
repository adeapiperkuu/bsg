# Delivery Performance Agent — Phase 0 Architecture Decisions

**Status:** Accepted for Phase 0  
**Authority:** This document is the source of truth for the decisions below.  
**Scope:** Contracts and architecture validation only; no later-phase analytics or response shaping.

## 1. Purpose

Phase 0 removes ambiguity before scoring, persistence, API, dashboard, and client-safety work changes. Runtime code, ORM models, migrations, schemas, and tests were audited as the source of truth. When older Delivery Agent documentation conflicts with this record, this record wins.

## 2. Current-state implementation inventory

| Capability | Current module(s) | Actual behavior | Prior docs accurate? | Later change? |
|---|---|---|---|---|
| Event publication | `services/scoring_service.py`, `events/domain_events.py`, `events/event_bus.py` | Scoring emits `DeliveryScoredEvent` through a process-wide, in-memory async bus. | No; the main document called it conceptual. | Retain; hardening may be considered separately. |
| Event consumption | `events/handlers.py` | `register_delivery_handlers()` subscribes `handle_delivery_scored`; dispatch is sequential and awaited. | No. | No Phase 0 change. |
| Failure/retry behavior | `events/event_bus.py`, `services/ingestion.py` | Each handler uses a DB savepoint. Exceptions are logged and returned as failed results; ingestion preserves the snapshot and exposes sanitized scoring failure. There is no queue, automatic retry, replay, or durable event log. | Previously unspecified. | Retry policy remains open. |
| Duplicate safety | `events/handlers.py` | Confidence is upserted/compared by milestone/date; open risk alerts and notifications are checked before creation; recommendation sync is keyed to source risks. Safety is handler-specific, not a universal event idempotency guarantee. | Partly. | Define durable idempotency only if transport changes. |
| Scoring persistence | `events/handlers.py`, `db/models/entities.py` | Handler updates milestone status, confidence history, risk alerts, recommendations, notifications, and append-only audit entries. Traffic light is derived, not persisted. | Partly. | Configurable scoring is deferred. |
| Throughput-triggered scoring | `services/ingestion.py`, `api/routes/delivery.py` | A project/date snapshot upsert flushes, recalculates rolling seven-day units, then synchronously awaits scoring inside a nested transaction before the route commits. | Open item is stale. | Retain flow. |
| Dashboard aggregation | `services/dashboard_service.py`, `services/scoring_service.py`, `routes/dashboard.py` | Scoped project data is bulk-loaded and deterministically scored. Dashboard route forces `daily_summary=None`; it does not call AI. `structured_summary` is computed in `build_dashboard_response`. | Partly; older flow showed AI invocation. | Optional AI narrative wiring remains deferred. |
| Portfolio aggregation/cache | `services/dashboard_service.py` | Visible projects are limited, inputs are loaded in one bundled round trip, projects are scored in memory, and default reads use a 30-second in-process cache keyed by org/role/user. | No cache was documented. | Preserve bulk loading; do not add per-project queries. |
| Cache invalidation | `api/routes/delivery.py` | Committed throughput writes and risk-resolution writes invalidate org and super-admin portfolio entries. Event handlers do not independently invalidate the cache. | Previously unspecified. | Review all future write paths. |
| Traffic light | `analytics/status.py`, `schemas/dashboard_schema.py`, `frontend/src/lib/api.ts` | Runtime/API values are `green`, `yellow`, `red`; there is no DB traffic-light column. | Older prose used Amber as if it were a value. | Keep `yellow`; present it as Amber. |
| Daily/AI summary | `schemas/dashboard_schema.py`, `ai/summary_service.py`, `routes/dashboard.py` | `daily_summary: str | None`; generator returns `None` when unconfigured, timed out, failed, or empty, but is currently not wired into the dashboard route. | Partly. | Optional narrative may be wired later behind a feature control. |
| Client visibility | `services/scoping.py`, dashboard schemas/routes | Project access is scoped, but Delivery dashboard/portfolio fields are not yet shaped by client-specific allowlists. | Requirement existed without implementation. | Full shaping is Phase 5. |
| Role/project access | `db/models/entities.py`, `services/scoping.py` | Real roles are `super_admin`, `bsg_leadership`, `delivery_manager`, `client`. There is no `project_manager` role. Super admin is cross-org; leadership/DM are org-scoped; clients require active project assignments. | Mostly. | Product must decide whether PM is a future role or a DM persona. |
| Chat evidence | `services/chat_service.py` | Chat uses visible project dashboards/portfolio, includes risk/bottleneck details and at-risk/missed milestones, and persists cited evidence links. It does not yet apply client evidence allowlists. | Incomplete. | Phase 5 shaping required. |
| Recommendations | `services/recommendation_service.py`, `api/routes/delivery.py` | Recommendations derive from delivery risks; visible-project readers can list full grouped data and owners, while mutation is DM/super-admin only and audited. | Partly. | Client-safe recommendation contract needed. |
| Throughput/bottlenecks | `services/team_throughput_service.py`, `analytics/bottlenecks.py`, `services/bottleneck_service.py` | Phase 2 adds tenant/project/team/day snapshots, deterministic share-decline detection, lifecycle, audit, notification, and existing scoring integration. | Superseded. | See the Phase 2 operations record. |
| Cross-agent signals | `services/quality_signal_consumer.py`, `services/signal_dispatcher.py` | Pending quality-risk records are polled from `inter_agent_signals`; consumption annotates an alert, may notify DMs, acknowledges an open alert, and marks the signal consumed/failed. This is separate from the delivery event bus. | Partly. | Refactor deferred. |
| Audit/notifications | `audit/audit_logger.py`, `events/handlers.py` | Delivery state transitions and recommendation mutations append `audit_logs`; scoring may create user notifications with duplicate checks. | Mostly. | No Phase 0 change. |

## 3. Decision: retain the event bus

**Decision.** Retain the existing in-process `EventBus`, `DeliveryScoredEvent`, and registered `handle_delivery_scored` consumer.

**Context.** The bus is working runtime infrastructure, not prospective documentation. Throughput ingestion directly awaits `run_delivery_scoring()`, which emits the event; the consumer owns the persistence and notification flow.

**Rationale.** Removing it would require reworking functioning scoring, confidence/risk persistence, milestone transitions, recommendations, notifications, and audit behavior with no Phase 0 benefit.

```text
ThroughputSnapshot create/update
  → upsert_throughput_snapshot
  → run_delivery_scoring
  → DeliveryScoredEvent emitted on EventBus
  → handle_delivery_scored
  → milestone/confidence/risk/recommendation/notification/audit writes
  → route commit
  → clear_delivery_portfolio_cache
  → refreshed dashboard/portfolio read
```

**Consequences.** Handling is mixed: async functions are used, but dispatch is synchronous to the request transaction (sequential and awaited). Handler savepoints isolate failures. There is no durable queue or automatic retry.

**Compatibility impact.** None.

**Deferred work.** Any retry, replay, outbox, background-worker, or event-versioning design.

## 4. Decision: preserve `yellow` as the API value

**Decision.** The only Delivery traffic-light wire values are `green`, `yellow`, and `red`. UI copy maps them to Green, Amber, and Red.

**Context.** Scoring and downstream consumers already branch on `yellow`; schemas and TypeScript types expose it.

**Rationale.** Renaming a wire value would break filters, analytics, chat weighting, tests, and clients for a presentation-only terminology preference.

**Consequences.** Frontend code must call `getTrafficLightLabel()` when rendering the delivery value. Requests, filters, persistence, exports, and analytics must never send `amber` as a Delivery traffic light.

**Compatibility impact.** Additive type/helper centralization only.

**Deferred work.** Adopt the helper on additional delivery surfaces as those surfaces expose traffic-light labels.

## 5. Decision: separate deterministic and AI summaries

**Decision.** Reserve `structured_summary` for a future deterministic object. Retain `daily_summary: str | None` as optional generated prose.

**Phase 3 update.** `structured_summary` is now implemented as documented in [Delivery Performance Agent — Deterministic Structured Summary](delivery-agent-structured-summary.md). `daily_summary` remains nullable and is still not AI-wired on the dashboard route.

**Context.** The dashboard already returns deterministic fields and a nullable narrative. The AI generator fails closed to `None`, and the current route does not invoke it.

**Rationale.** Facts must remain available and trustworthy without an AI provider.

**Consequences.** The structured summary is authoritative. The AI narrative may restate or explain structured facts, but it must not create new facts. Future dashboards must succeed when credentials are missing, the provider times out, or generation fails. Generation status, if added, is optional and feature-controlled.

The future `structured_summary` may include latest throughput, change, target variance, risks created/escalated, bottlenecks opened/resolved, milestones due soon, and current traffic light. No placeholder response field is added in Phase 0, avoiding a premature public contract.

**Compatibility impact.** `daily_summary` remains nullable and existing response shapes remain unchanged.

**Deferred work.** Structured aggregation service and optional AI wiring.

## 6. Decision: client-safe allowlist shaping

**Decision.** Phase 5 must shape every client Delivery surface from explicit allowlists. Unknown or unresolved fields default to hidden. Internal roles continue to use scoped operational contracts.

**Context.** Project access control exists, but field-level Delivery shaping does not. “Project-visible” is not equivalent to “client-approved.”

**Rationale.** An allowlist prevents newly added internal fields from leaking by default.

**Consequences.** Client delivery responses must be constructed from approved fields rather than copied from internal models and pruned. New fields remain internal until explicitly approved.

Future policy shape:

```python
CLIENT_DASHBOARD_ALLOWED_FIELDS = {...}
CLIENT_PORTFOLIO_ALLOWED_FIELDS = {...}
CLIENT_SUMMARY_ALLOWED_FIELDS = {...}
CLIENT_CHAT_EVIDENCE_ALLOWED_FIELDS = {...}
CLIENT_RECOMMENDATION_ALLOWED_FIELDS = {...}
```

Legend: **A** client-approved; **I** internal operational; **R** restricted to leadership/super-admin unless approved; **N/A** not applicable. DM means `delivery_manager`; Leadership means `bsg_leadership`. `project_manager` is not a current role and is recorded as N/A pending product/RBAC work.

| Area / field | Super admin | Leadership | DM | Project manager | Client |
|---|---:|---:|---:|---:|---:|
| Dashboard: approved project name/metadata | I | I | I | N/A | A |
| Delivery confidence, risk, traffic light | I | I | I | N/A | A |
| Throughput totals/trends/target comparison | I | I | I | N/A | R |
| Milestone status | I | I | I | N/A | A |
| Risk title/severity | I | I | I | N/A | R |
| Risk contributing causes | I | I | I | N/A | R |
| Internal mitigation notes | I | I | I | N/A | R |
| Bottleneck title | I | I | I | N/A | R |
| Bottleneck evidence/detail | I | I | I | N/A | R |
| Team identifiers | I | I | I | N/A | R |
| Staffing/allocation recommendations | I | I | I | N/A | R |
| Audit/recommendation/scoring-debug metadata | I | R | I | N/A | R |
| Portfolio: aggregate confidence/risk and color counts | I | I | I | N/A | A |
| Portfolio: project drill-down | I | I | I | N/A | A (assigned projects only) |
| Portfolio: internal causes/staffing/team contribution | I | I | I | N/A | R |
| Structured summary: approved aggregate facts | I | I | I | N/A | A |
| Structured summary: operational explanations/team/audit data | I | I | I | N/A | R |
| Chat: client-approved source evidence | I | I | I | N/A | A |
| Chat: raw records/internal causes/hidden recommendations | I | I | I | N/A | R |
| Chat: staffing/team/individual identifiers | I | I | I | N/A | R |
| Recommendation: title/client-safe explanation | I | I | I | N/A | R |
| Recommendation: evidence/actions/owner/history | I | I | I | N/A | R |

**Compatibility impact.** Policy only in Phase 0; current response behavior is not changed.

**Deferred work.** Implement and test allowlists only after product approves all `R` items.

## 7. Decision: separate team throughput snapshots

**Phase 2 update.** This decision is implemented. The authoritative schema, ingestion, access, and correction contract is documented in [the Phase 2 operations record](delivery-agent-team-throughput-and-bottlenecks.md). Remaining work is limited to selecting final upstream sources and any approved historical backfill.

**Decision.** A later migration will add `team_throughput_snapshots`; it will not overload project-level `throughput_snapshots`.

**Context.** The current unique key `(project_id, snapshot_date)` permits only one project aggregate per day and has no team identity or headcount. Existing `bottlenecks.team_id` and utilization data cannot reconstruct completed delivery units attributed to each team.

**Rationale.** Bottleneck share analytics need an idempotent team/project/day fact table while preserving existing project snapshot semantics.

**Consequences.** Team contribution cannot be inferred from current project snapshots. Later detection must wait for an independently governed, tenant-scoped ingestion path and sufficient history.

Proposed minimum contract:

| Field | Meaning |
|---|---|
| `id` | UUID primary key. |
| `organisation_id` | Direct tenant scope, following existing tenant-scoped delivery tables. |
| `project_id` | Project receiving the attributed delivery units. |
| `team_id` | Stable team UUID, never a display label. |
| `snapshot_date` | Reporting date in the agreed organisation/project timezone. |
| `units_completed` | Completed delivery units attributed to the team during that reporting period. |
| `active_headcount` | Active contributors included for that team and reporting period. |
| `created_at`, `updated_at` | Audit timestamps. |

Required uniqueness: `(organisation_id, project_id, team_id, snapshot_date)`. Foreign keys and queries must enforce organisation consistency and tenant isolation.

### Ownership and ingestion

**Primary approach: hybrid.** Import from an upstream operational source where available, with authorised delivery-manager correction. This matches the existing throughput upsert pattern and avoids mandatory duplicate manual reporting.

- **Source of truth:** approved row in `team_throughput_snapshots`, with source/provenance metadata to be finalized before migration.
- **Writers:** system integration/service role for imports; `delivery_manager` and `super_admin` for correction/approval. Leadership and clients are read-only.
- **Corrections:** idempotent upsert followed by an audited before/after record and deterministic recomputation.
- **Late arrivals:** upsert the historical date and recompute affected windows; do not rewrite unrelated dates.
- **Zero-output day:** store an explicit zero when the team was active and reported no units.
- **Missing snapshot:** absence means unknown/incomplete, never zero.
- **Membership changes:** snapshot the period headcount; retain stable `team_id`; team merges/splits require an explicit mapping policy.
- **Headcount definition:** unique active contributors who participated in the team during the period; partial-day/FTE treatment is an open decision.
- **Timezone:** one agreed project or organisation timezone determines the date boundary; UTC timestamps remain audit metadata.
- **Idempotency key:** the unique tenant/project/team/date tuple, plus upstream event/source id if provided.
- **Backfill:** authorised batch upserts using the same validation and audit path, then bounded recomputation.
- **Tenant isolation:** direct organisation key, scoped foreign keys/checks where feasible, RLS consistent with current tables.
- **Retention:** retain at least the configured historical window plus audit/legal needs; exact period is open.

**Compatibility impact.** None in Phase 0; no migration is created.

**Deferred work.** Final source metadata, migration, RLS, ingestion endpoint/events, backfill tooling.

## 8. Bottleneck detection prerequisites

**Phase 2 update.** The deterministic detector and its lifecycle are now implemented. The requirements below remain the governing design rationale; see [the Phase 2 operations record](delivery-agent-team-throughput-and-bottlenecks.md) for the running contract.

**Decision.** Future detection is deterministic and must not run until complete team-throughput inputs exist.

**Context.** Current bottleneck rows can identify a team but the repository has no team-attributed delivery-unit history from which to calculate contribution-share decline.

**Rationale.** Explicit definitions and data-quality guards prevent missing data, headcount changes, and zero-throughput days from being misclassified as operational bottlenecks.

For team `t` and valid period `d`:

```text
current_share(t,d) = team_units_completed(t,d) / total_project_units_completed(d)
historical_share(t) = average(valid historical current_share(t,d))
decline_pct = (historical_share - current_share) / historical_share × 100
```

A team is a candidate when current share is at least configurable **X%** below its historical average, the condition persists for configurable **N** consecutive valid days, active headcount has not fallen proportionally, and sample/data-quality guards pass. A comparable headcount decline explains the throughput-share decline and suppresses the candidate; the tolerance formula is deferred.

Detection must not run when project throughput is zero, team coverage is incomplete, the historical sample is insufficient, required headcount is missing, team identity lacks a stable mapping, or data is stale. Invalid/incomplete periods are excluded, not coerced to zero.

Expected typed output (final details deferred):

```python
class BottleneckDetectionSignal(BaseModel):
    project_id: UUID
    team_id: UUID
    source_key: str
    severity: Literal["low", "medium", "high", "critical"]
    current_share: float
    historical_share: float
    decline_pct: float
    headcount_change_pct: float | None
    consecutive_days: int
    evidence: list[...]
```

`source_key` must be stable for idempotent lifecycle handling. Severity thresholds, evidence schema, historical window, X, N, minimum sample size, staleness window, and headcount tolerance remain configuration/product decisions.

**Consequences.** Invalid periods produce no signal, not a zero-valued signal. Detectors must emit typed evidence and lifecycle code must deduplicate by stable source key.

**Compatibility impact.** None in Phase 0; no detector, schema, or bottleneck lifecycle behavior is added.

**Deferred work.** Final typed schema, configuration, detection service, lifecycle, notifications, and backfill evaluation.

## 9. Compatibility commitments

- Delivery APIs and persisted values continue to use `green | yellow | red`.
- Frontend presentation uses Green / Amber / Red.
- `daily_summary` remains nullable; `structured_summary` is additive and optional on the schema for backward compatibility.
- Existing dashboard and portfolio shapes remain valid.
- Event-driven scoring and handler persistence remain intact.
- Portfolio scoring remains bulk-loaded; Phase 0 adds no per-project query loop.
- Existing project visibility and mutation roles do not change.

## 10. Deferred implementation phases

Phase 0 did **not** implement configurable scoring thresholds. Phase 1 has now implemented them as documented in [Delivery Performance Agent — Configurable Scoring](delivery-agent-configurable-scoring.md). Phase 2 has now implemented the team-throughput migration and deterministic bottleneck lifecycle as documented in [Delivery Performance Agent — Team Throughput and Bottlenecks](delivery-agent-team-throughput-and-bottlenecks.md). Phase 3 has now implemented deterministic `structured_summary` as documented in [Delivery Performance Agent — Deterministic Structured Summary](delivery-agent-structured-summary.md). Optional AI summaries, resource-allocation summaries, full client response shaping, and an inter-agent signal refactor remain deferred.

## 11. Open product decisions

1. Approve which `R` fields in the visibility matrix may be client-visible and whether publication is per-field, per-record, or per-report.
2. Decide whether “project manager” is a new role or a Delivery Manager persona.
3. Select upstream team-throughput source(s), provenance fields, approval SLA, and correction authority.
4. Define active headcount treatment for part-time, partial-day, transferred, and temporarily inactive contributors.
5. Choose project-versus-organisation timezone precedence and retention period.
6. Approve X, N, historical/minimum sample windows, staleness, headcount tolerance, and severity bands.
7. Decide whether event-handler failure needs automatic retry/replay beyond current next-ingest recovery.

## 12. Acceptance checklist

- [x] Runtime architecture audited across backend, frontend, models, migrations, tests, and docs.
- [x] Existing event bus explicitly retained.
- [x] `yellow` API and Amber presentation contract enforced.
- [x] `structured_summary` and optional `daily_summary` responsibilities separated.
- [x] Client visibility defined as allowlist-first with conservative unresolved defaults.
- [x] Team-throughput contract, migration, and secure idempotent ingestion implemented in Phase 2.
- [x] Deterministic bottleneck formula, data-quality guards, lifecycle, audit, and existing scoring integration implemented in Phase 2.
- [x] Compatibility contracts covered by focused backend/frontend tests.
- [x] Phase 1 configurable thresholds are now implemented without introducing Phase 2 features.
- [x] Later Phase 3 structured summary is now implemented; Phase 4+ AI narrative, resource-allocation summary, and client allowlists remain deferred.
