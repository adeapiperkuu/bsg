# Client Intelligence Agent — Current-State Implementation Gap Audit

**Canonical product name:** Client Intelligence Agent  
**Agent ID:** 05  
**Audit date:** 2026-07-13  
**Authoritative roadmap:** [`docs/agents/client_intelligence_roadmap.md`](../../../docs/agents/client_intelligence_roadmap.md)  
**Related derived spec (not modified by this audit):** [`docs/AI Agents/05. Client Interaction Agent.md`](../../../docs/AI%20Agents/05.%20Client%20Interaction%20Agent.md)

**Scope of this document:** Evidence-based gap analysis only. No production code, migrations, or product decisions are introduced here.

**Method:** Requirements from roadmap Sections 4, 14, 15, 18, and 22 were traced to repository symbols, routes, models, UI routes, and tests. A table, route, or UI shell is **not** treated as feature completion.

---

## 1. Executive summary

### Overall readiness estimate: **~15%**

Estimated by weighting all CI-F / CI-D / CI-O / CI-G / CI-N requirements by status (Implemented ≈ 1.0, Partial ≈ 0.35–0.5, Mock only ≈ 0.1, Missing/Blocked ≈ 0), then adjusting for the fact that most “Partial” items are platform primitives owned by other agents or a thin communications lifecycle—not Client Intelligence engines. Upstream Delivery / Quality / Workforce / Governance / Knowledge services are comparatively mature; the Client Intelligence product layer itself is largely unbuilt.

### Fully implemented

Nothing in the Client Intelligence product surface is fully implemented end-to-end.

Platform capabilities that **do** work today and are relevant as dependencies (but are not CI completion):

- Org/project scoping primitives (`app.services.scoping.get_visible_project`).
- Delivery confidence persistence and scoring (`DeliveryConfidenceScore`, delivery analytics/services).
- Sanitized quality summary for client narrative context (`app.services.quality.generate_quality_summary`).
- Knowledge document visibility including `client_safe` (`app.services.knowledge` / `can_access_visibility`).
- Communications **status machine** for draft → in_review → approved → sent / rejected (`app.services.communications`).
- Evidence requirement helper (`app.services.evidence.require_evidence`) used by communications and agent queries.
- CSAT **write** path for CLIENT role (`POST /projects/{id}/csat`).

### Partially implemented

- **Communications lifecycle (CI-F09 / CI-F20 / CI-O02 / CI-O07):** Governed transition matrix in `app.services.communications` with `PATCH /communications/{id}/draft`, review/approve/reject/send. Allowed: create→draft; edit draft|rejected→draft; draft→in_review; in_review→approved|rejected; approved→sent. Reject requires `rejection_reason` (+ `rejected_by`/`rejected_at` migration). Audit events: `client_communication.edited|submitted_for_review|approved|rejected|sent`. Evidence links immutable on edit. Send is approval-gated in-app visibility (no auto-send; no external email claim).
- **Approved & Sent report history:** `GET /api/v1/projects/{project_id}/client-intelligence/reports` reads only `client_communications` where `drafted_by_agent = client_interaction_agent` and status ∈ `{approved, sent}`. Body is `body_approved` only; provenance `complete`/`partial`/`unavailable` with stable limitation codes; order by lifecycle timestamp DESC + id DESC; limit 1–50 (default 20); evidence bulk-loaded per page (≤3 queries after auth). Internal roles only (DM / Leadership / Super Admin); Client denied. Unfiltered `total` reconciles with Reports summary `approved_count`. Approved may appear in both active queue and history; Sent leaves the queue and remains client-visible via existing sent-only communications read. No export/download; no external email; no mutations/LLM.
- **Grounded Client Intelligence Q&A (implemented + acceptance corrections):** Internal `POST/GET /api/v1/projects/{project_id}/client-intelligence/queries` and client-only `POST/GET /api/v1/client/ask/queries` build the same governed `ClientEvidencePack`, return structured availability (`answered`/`insufficient_evidence`/`unsupported`/`provider_unavailable`), and persist under the authorized project’s `org_id` with real `latency_ms`. The client endpoint enforces assigned-project access and client-safe evidence projection. Generative LLM refinement remains **disabled** until complete structured claim validation exists (`model_used=null`). **Evidence/source registry + pack/provenance hardening for CI-D01–CI-D15 is in place (partial sources + explicit unavailable); full evidence/source closure is not claimed while CI-DQ07/08/09, readiness, and Milestone/Change UI remain open.** Remaining lifecycle gaps: narrative claim validation and readiness/go-live report types. **Next roadmap item: Milestone/Change Intelligence UI.**
- **Agent query infrastructure (CI-F16 / CI-O10):** `client_interaction_agent` is routed through the grounded CI Q&A handler (no placeholder answer). Generic `/agent-queries` for other agents is unchanged; CI rows are excluded from generic reads.
- **CSAT (CI-F19):** Submit-only; no read aggregation, trend, sample disclosure, or UI.
- **Upstream data sources (CI-D01–CI-D15):** Canonical registry in `source_coverage.py` with contributing owners and adapter-table agreement. Delivery/Quality/Workforce/Governance/Knowledge adapters assemble `ClientEvidencePack`. Explicitly unavailable: CI-D07 workflow status, CI-D09 backlog queue, CI-D14 client communication notes. CI-D03 throughput logs remain **partial**; governed plan series absence is a sibling limitation (`PLAN_SERIES_UNAVAILABLE`), not a claim that throughput itself is unavailable. Freshness SLA unresolved (`FRESHNESS_SLA_UNRESOLVED` — no age-only stale). CLIENT_SAFE redacts identities and internal-only risks/knowledge text.
- **Metric visibility config:** `MetricConfiguration.is_client_visible` wired through `ClientVisibilityPolicy` for CLIENT_SAFE packs.

### Placeholder / mock-only

| Area | Evidence |
|---|---|
| Agent module | `backend/app/agents/client_interaction.py::draft_placeholder` — dead stub; zero callers |
| Q&A answers | Internal CI Q&A grounded; generic non-CI agent placeholder path unchanged | Client portal `/client/ask` still hardcoded |
| Comms drafts without LLM / on LLM error | `COMMS_PLACEHOLDER_BODY` in `communications.py` |
| Client portal `/client`, `/client/status`, `/client/reports`, `/client/ask` | Static literals / synthetic chart / hardcoded chat reply |
| Portfolio-style CSAT card | UI text “across 8 clients” — Phase 7 future scope, mock only |

### Still missing / deferred (not started in this closure task)

- Milestone Intelligence UI and Change Intelligence UI (next roadmap task).
- Client-safe portal (`/client*`) and client-facing evidence-link publication policy.
- Readiness / go-live scoring, recommendation engines, scheduled weekly automation.
- Production policy thresholds (CI-DQ07), readiness schema (CI-DQ08), quantified impact/mitigation (CI-DQ09).
- Final integration acceptance across all CI phases.

**Conclusion:** Core Client Intelligence engines, evidence pack, grounded Q&A, communications provenance/stale-approval, internal dashboard, and client portal exist as partial/implemented foundations. Do **not** treat evidence/source closure as complete while unavailable sources, unresolved freshness, readiness and Milestone/Change UI work, and **live Postgres migration execution** (fresh/upgrade/duplicate/RLS) remain open in this test environment.

---

## 2. Current backend inventory

### 2.1 `backend/app/agents/client_interaction.py`

| Symbol | Status |
|---|---|
| `draft_placeholder(subject: str) -> str` | **Placeholder only.** Returns a static “awaits LLM provider” string. **No callers** in the repository. |

There is a live `backend/app/agents/client_intelligence/` package (evidence pack, adapters, engines, Q&A). `client_interaction.py::draft_placeholder` remains an unused stub and must not be treated as the CI implementation.

### 2.2 `backend/app/services/communications.py`

| Symbol | Behavior | CI gap |
|---|---|---|
| `COMMS_PLACEHOLDER_BODY` | Static placeholder when LLM key missing or `ApiError` | Explicit mock narrative |
| `build_comms_context` | JSON from latest throughput + optional `QualitySummaryRead` or raw quality snaps/drift alerts | Missing milestones, confidence, risks, readiness, changes, mitigations |
| `generate_comms_draft_body` | Hybrid: LLM via `LLMClient.generate_structured` + `COMMS_SYSTEM_PROMPT` from Quality Intelligence; else placeholder | No structured schema, claim validation, or deterministic template fallback matching roadmap §10.3 |
| `create_draft` | Creates `ClientCommunication` with `drafted_by_agent="client_interaction_agent"`; requires complete server-authored provenance + pack fingerprint for new drafts | Legacy null fingerprints remain for pre-migration rows only |
| `move_to_review` / `approve` / `reject` / `send` / `edit_draft` | Central transition matrix; reject requires reason; send requires approved + approver + approved_at + body | Stale-approval check; channel policy beyond in-app `sent` |
| `get_visible_communication` | CLIENT: same org + `SENT` only | Aligns with client-sent-only rule; no client-safe field redaction beyond status filter |

### 2.3 `backend/app/services/agent_queries.py`

| Symbol | Behavior |
|---|---|
| `SUPPORTED_AGENTS` | Includes `"client_interaction_agent"` |
| `answer_query` | Routes quality → `answer_quality_query`; governance → `answer_governance_query`; **`client_interaction_agent` → grounded Client Intelligence Q&A handler**; other agents keep the generic placeholder path |

**Placeholder answer text (verbatim):**  
`"The LLM provider is not configured yet; this response is grounded in the attached evidence placeholders."`

No Client Intelligence evidence pack, intent classification, claim validation, or insufficiency path.

### 2.4 `backend/app/api/routes/communications.py`

Mounted at `/api/v1` via `app.main.create_app`.

| Method | Path | Roles | Notes |
|---|---|---|---|
| GET | `/projects/{project_id}/communications` | Authenticated; CLIENT sees `SENT` only | Reusable list |
| POST | `/projects/{project_id}/communications/draft` | DM / Super Admin | Requires latest throughput; weekly attaches quality summary |
| GET | `/communications/{communication_id}` | Visibility helper | |
| PATCH | `/communications/{communication_id}/draft` | DM / SA | Edit draft/rejected only; no LLM |
| PATCH | `/communications/{communication_id}/review` | DM / SA | `draft → in_review` only |
| POST | `/communications/{id}/approve` | DM / SA | `in_review → approved`; body replacement rejected |
| POST | `/communications/{id}/reject` | DM / SA | Requires `rejection_reason` |
| POST | `/communications/{id}/send` | DM / SA | Approval-gated in-app `sent` |

`CommunicationDraftCreate.instructions` is accepted by schema and **unused** by the route.

### 2.5 `backend/app/api/routes/agents.py`

| Method | Path | CI relevance |
|---|---|---|
| POST | `/agent-queries` | `client_interaction_agent` routes to grounded CI Q&A; Client role → 403; DM/Leadership/Super Admin allowed with mandatory `project_id`; other agents unchanged |
| GET | `/agent-queries` | Excludes `client_interaction_agent` rows; CLIENT=own / DM+Leadership=org filtering for remaining agents |
| GET | `/agent-queries/{query_id}` | Same exclusion + RBAC; CI history is dedicated project-scoped endpoint only |

Workforce is special-cased to `answer_workforce_query` before `answer_query`.

### 2.6 `backend/app/api/routes/csat.py`

| Method | Path | Role | Status |
|---|---|---|---|
| POST | `/projects/{project_id}/csat` | `CLIENT` only | **Implemented write path** |
| GET / aggregate / trend | — | — | **Missing** |

Returns `{"id": "<uuid>"}` only. No `ClientCsatRead` schema usage for lists.

### 2.7 `backend/app/api/routes/delivery.py` (+ delivery agent routes)

Reusable **source** endpoints (not CI APIs):

| Path | Use for CI |
|---|---|
| GET `/projects/{id}/throughput` | Throughput / trend inputs |
| GET `/projects/{id}/delivery-confidence` | Confidence history (Delivery-owned) |
| GET `/projects/{id}/risk-alerts` | Risk inputs |
| GET `/projects/{id}/recommendations` | Delivery mitigations (not CI readiness recs) |
| GET `/projects/{id}/milestones` | Milestone inputs |
| GET `/delivery/dashboard/{project_id}` | Aggregated delivery overview |
| GET `/delivery/portfolio` | Portfolio — **must not** become Phase 1–6 CI portfolio intelligence |

### 2.8 `backend/app/agents/delivery/`

| Prefer for CI (shared contracts) | Do not import (private internals) |
|---|---|
| `services.dashboard_service.get_dashboard_data` / `get_portfolio_data` (portfolio for internal Delivery only) | Chat/conversation internals |
| Analytics: `calculate_confidence*`, milestone selectors, risk/throughput helpers | Event handlers, unused AI summary wiring treated as Delivery-owned |
| ORM: `DeliveryConfidenceScore`, `ThroughputSnapshot`, `Milestone`, `RiskAlert`, `Bottleneck` | Recalculating Delivery scores inside CI |

Package `__init__.py` exports no public `__all__`; consumers should use stable service functions / shared tables, not private reasoning modules.

### 2.9 Quality (`backend/app/services/quality.py`, `backend/app/agents/quality_intelligence/`)

| Safe public contract | Private — do not import into CI engines |
|---|---|
| `generate_quality_summary` → `QualitySummaryRead` (CLIENT role strips metrics/drift) | `EvidencePack` / `build_evidence_pack` (Quality-agent internal) |
| GET `/projects/{id}/quality-summary` | Root-cause, reviewer scorecards, item-level RCA |
| `comms_prompts.COMMS_SYSTEM_PROMPT` (already used by communications) | Drift/RCA private modules as CI fact sources without sanitization |

### 2.10 Workforce (`backend/app/services/workforce*`, `backend/app/agents/workforce/`)

| Surface | Path | CI note |
|---|---|---|
| `get_project_workforce_summary`, `get_workforce_dashboard`, `get_sme_allocation` | `workforce.py` | Contains identities / annotator detail — **not client-safe** |
| Training gaps / capability gaps | `workforce_training.py`, `workforce_gaps.py` | Useful internal readiness inputs after aggregation/redaction |
| `answer_workforce_query` | `workforce_agent.py` | Redirects client-comms keywords toward Client Interaction Agent; real NL for workforce only |

**Missing for CI:** Aggregated capacity / SME coverage / training completion projection **without** employee identities.

### 2.11 Governance (`backend/app/agents/governance/`)

Reusable service contracts:

- Summaries: `generate_weekly_governance_summary`, list/approve weekly summaries.
- Registers: dependencies, actions, escalations, scope states (`governance_service`, routes).
- Charter: generate/list/approve.
- Knowledge links: `list_approved_governance_document_refs`.
- Delivery signals: `fetch_governance_delivery_signals`.

Package public export is primarily `answer_governance_query`. Prefer scoped list/get services over private prompt/analytics internals.

### 2.12 Knowledge (`backend/app/services/knowledge/`, `backend/app/agents/knowledge/`)

| Contract | Relevance |
|---|---|
| `KnowledgeVisibility.CLIENT_SAFE` + `can_access_visibility` | Required for unstructured CI-D11–CI-D15 |
| Retrieval / ask pipelines with approved+indexed filters | Phase 1 unstructured adapter + Phase 5 Q&A |
| `RetrievalReadinessAssessment` / `assess_retrieval_readiness` | **Name collision only** — document retrieval readiness, **not** client go-live readiness |

Thin `app.agents.knowledge` shim (`keyword_search`, lesson write-back) is not the primary CI contract; prefer `app.services.knowledge` public APIs.

### 2.13 Models (`backend/app/db/models/entities.py`)

**Exist and reusable (roadmap §14.1):**

| Model | Table |
|---|---|
| `ClientCommunication` | `client_communications` |
| `CommunicationEvidenceLink` | `communication_evidence_links` |
| `AgentQuery` / `AgentQueryEvidenceLink` | `agent_queries` / `agent_query_evidence_links` |
| `ClientCsatScore` | `client_csat_scores` |
| `DeliveryConfidenceScore` | `delivery_confidence_scores` |
| `Milestone`, `ThroughputSnapshot` | `milestones`, `throughput_snapshots` |
| `QualitySnapshot`, `RiskAlert`, `MitigationRecommendation`, `Bottleneck` | respective tables |
| `MetricConfiguration` | `metric_configurations` |
| `Notification` | `notifications` |
| Workforce / governance / knowledge entities | as implemented by those agents |

**Enums of note:**

- `CommunicationStatus`: draft, in_review, approved, sent, rejected.
- `CommunicationType`: `weekly_summary`, `executive_summary`, `ad_hoc` only — **no** readiness / go-live report type.

**Do not exist (roadmap §14.2):**

- `client_intelligence_snapshots`
- `client_readiness_assessments`
- `client_readiness_dimensions`
- `client_intelligence_insights`
- `client_intelligence_recommendations`
- `client_intelligence_evidence_links`

Zero backend matches for `client_intelligence` / `ClientIntelligence` / `ClientEvidencePack`.

### 2.14 Schemas (`backend/app/schemas/domain.py`)

Present: `CommunicationDraftCreate`, `CommunicationReview`, `CommunicationApprove`, `CommunicationRead`, `AgentQueryCreate` / `AgentQueryRead`, `ClientCsatCreate`, `QualitySummaryRead`, delivery/quality/workforce DTOs.

Missing: CI dashboard, changes, readiness, recommendations, client-safe intelligence projection, CSAT read/aggregate, evidence-pack schemas.

### 2.15 Migrations

Not Alembic — `supabase/migrations/`:

| Migration | Relevance |
|---|---|
| `20260622090000_initial_backend_schema.sql` | Creates communications, evidence links, agent queries, csat, delivery confidence, enums, RLS enable |
| `20260623100000_rls_policies.sql` | RLS for those tables |

No migrations for Section 14 CI entities.

### 2.16 Relevant tests (existing)

No `test_client_intelligence_*` files.

Adjacent coverage:

| File | Relevance |
|---|---|
| `backend/tests/test_quality_comms.py` | `generate_comms_draft_body`, `build_comms_context` |
| `backend/tests/test_quality_summary.py` | Sanitized quality summary / CLIENT stripping |
| `backend/tests/test_quality_api.py` | Quality summary auth |
| `backend/tests/test_workforce_agent.py` | Redirect to Client Interaction; `SUPPORTED_AGENTS` |
| `backend/tests/test_delivery_scoring.py` | Confidence / risk / status math |
| `backend/tests/test_delivery_rbac.py` | Delivery RBAC |
| `backend/tests/test_rbac.py`, `test_tenant_isolation.py` | Platform RBAC / isolation |
| `backend/tests/test_knowledge_retrieval.py`, `test_knowledge_prompt_security.py` | RAG / injection adjacent |
| Governance / workforce / quality suites | Upstream source contracts |

**Missing:** Entire roadmap §21.3 CI suite list (see Section 8).

### 2.17 Router registration (`backend/app/main.py`)

Registered: auth, me, orgs, users, projects, delivery (+ dashboard/chat), quality, workforce, agents, communications, metrics, csat, knowledge, governance.

**No** `client_intelligence` router.

---

## 3. Current frontend inventory

### 3.1 Routes

| File | Path | Data source | Live API? |
|---|---|---|---|
| `frontend/src/routes/client-intelligence.tsx` | `/client-intelligence` | Authorized Projects API + selected project Client Intelligence overview API | **Yes** — internal roles, read-only, project-level |
| `frontend/src/routes/client.index.tsx` | `/client/` | Client dashboard API | **Yes** — assigned projects and client-safe summary |
| `frontend/src/routes/client.status.tsx` | `/client/status` | Client dashboard API through `ClientProjectWorkspace` | **Yes** — governed confidence, milestones, and status |
| `frontend/src/routes/client.reports.tsx` | `/client/reports` | Client portal reports API | **Yes** — sent-only reports with scoped PDF/CSV download |
| `frontend/src/routes/client.ask.tsx` | `/client/ask` | Client Q&A API | **Yes** — evidence-grounded answers and safe insufficiency states |

Shared widgets used: `Card`, `SectionHeader`, `KpiCard`, `AiBadge`, `StatusPill` from `@/components/bsg/widgets`. `EvidenceBadge` is **not** used on CI routes.

### 3.2 `frontend/src/lib/bsg/data.ts`

`export const clients = [...]` — eight mock clients (Aurora Health, Helios Bank, …) remain for unrelated mock surfaces. The internal `/client-intelligence` route no longer imports or uses this dataset.

### 3.3 `frontend/src/lib/api.ts`

| Present | Used by CI routes? |
|---|---|
| `createAgentQuery` / `postAgentQuery` / `listAgentQueries` | **No** — used by Workforce / Quality / Knowledge elsewhere |
| `listProjectDeliveryConfidence`, `listProjectMilestones`, `listProjectRiskAlerts`, `listProjectThroughput` | **No** on CI routes |

**Missing wrappers:** all `/client-intelligence/*`, `/client/projects*`, communications lifecycle, CSAT submit/read.

`MePermissions.can_approve_communications` exists in auth types; unused by CI UI.

### 3.4 Navigation

`frontend/src/components/bsg/Shell.tsx`:

- Internal: `/client-intelligence` labeled “Client Intelligence”.
- Client: `/client`, `/client/status`, `/client/reports`, `/client/ask`.

### 3.5 Feature module

`frontend/src/features/client-intelligence/ClientIntelligenceDashboard.tsx` now provides the bounded internal project navigator, four-engine overview, Draft lifecycle, Approved & Sent history, and grounded Client Intelligence Q&A. Backend evidence registry + provenance/stale-approval hardening for CI-D01–CI-D15 is partial (with explicit unavailable sources). Roadmap readiness, Milestone/Change UI, alert, client-safe portal, and broader portfolio components remain missing.

### 3.6 Phase 7 leakage in mock UI

Internal KPI card shows “Avg CSAT … across 8 clients” — portfolio aggregate presentation. Core phases must treat client list as **navigator only**; such aggregates require Phase 7 approval.

---

## 4. Requirement traceability

Status legend: **Implemented** / **Partial** / **Missing** / **Mock only** / **Blocked**.

### 4.1 Functional — CI-F01–CI-F22

| ID | Status | Existing evidence | Exact missing behavior | Phase |
|---|---|---|---|---:|
| CI-F01 | Partial | Policy-driven Project Health foundation (`assess_project_health`); no production thresholds | Approved CI-DQ07 policy + persistence/API | 2 |
| CI-F02 | Partial | Delivery Confidence Intelligence foundation (`assess_delivery_confidence`); Delivery-owned score/status; context-only explanation policy + engine-owned pack/candidate isolation; pack-owned candidate source quality (no COMPLETE fallback); closed driver lineage; structured `limitations` vs pack `source_limitations`; top-level evidence aggregates driver lineage; no production thresholds | Persistence/API/UI + production explanation policy | 2 |
| CI-F03 | Partial | Risk Transparency foundation (`assess_risk_transparency`); public contract source/claim/category/visibility closure; exact top-level evidence union; mixed source-quality fails closed; verified pack candidates; policy isolation; no production materiality/visibility policy | Client-safe publication policy + narratives | 2 |
| CI-F04 | Partial | Business impact/mitigation contracts remain UNAVAILABLE with required limitation codes (CI-DQ09 open; no pack mitigation facts) | Quantified impact + mitigation progress when evidenced | 2 |
| CI-F05 | Partial | `throughput_series` in ClientEvidencePack with claim-to-fact binding + full latest↔series equality; Delivery Trend foundation (`assess_delivery_trend`) with public contract closure (window/order/UTC/deviation↔point/policy provenance); actual/forecast source-backed; plan MISSING_SOURCE; missing quality remains None; no interpolation | Aligned actual vs plan vs forecast when governed plan source exists | 2 |
| CI-F06 | Partial (foundation) | `change_intelligence.py` | Deterministic cross-pack candidate detection; materiality/business meaning policy-owned; no production policy/persistence/API/UI | 2 |
| CI-F07 | Partial | `Milestone` model + list API; frontend mock tables | Deterministic on-track counts, at-risk reasons, next key milestone selection for CI | 2 |
| CI-F08 | Partial | `generate_comms_draft_body` + LLM/placeholder | Executive narratives from full evidence pack + claim validation + deterministic fallback | 4 |
| CI-F09 | Partial | `CommunicationType` weekly/executive/ad_hoc + draft API | Readiness/go-live report types; full required content sections | 4 |
| CI-F10 | Missing | Knowledge `RetrievalReadinessAssessment` is unrelated | Overall readiness score + dimension breakdown | 3 |
| CI-F11 | Missing | Upstream workforce/governance/quality data | Resources, training, planning, tracking, risk-preparedness dimensions | 3 |
| CI-F12 | Missing | SME/training/quality/historical sources exist elsewhere | Cross-cutting readiness reasoning without identity leakage | 3 |
| CI-F13 | Missing | — | Gaps, confidence level, mitigation recommendations | 3 |
| CI-F14 | Missing | — | Go-live readiness report + human sign-off state | 4 |
| CI-F15 | Missing | Delivery `MitigationRecommendation` is different concept | Pre-go-live, training, resource, mitigation, pilot-validation recommendation types | 3 |
| CI-F16 | Implemented | Internal project Q&A plus client-only `POST/GET /client/ask/queries`; both use governed Client Intelligence evidence | Continue negative authorization and end-to-end UX coverage | 5 |
| CI-F17 | Missing | Evidence links persist but answer ignores content | Answer only from authorized structured + approved unstructured evidence | 5 |
| CI-F18 | Mock only | Hardcoded “Delivery narrative” / “Today” style copy in UI | Deterministic recent changes + Today’s Insight fact set | 5 |
| CI-F19 | Partial | POST `/projects/{id}/csat` | Read aggregation, trend, sample disclosure, UI | 5 |
| CI-F20 | Partial | Governed lifecycle + reject reason + draft edit + audits + Approved/Sent history + stale fingerprint Approve/Send block + exact provenance on new drafts | Channel policy; readiness/go-live report types | 4 |
| CI-F21 | Missing | `NotificationType.COMMUNICATION_PENDING` exists | Scheduled weekly drafts, idempotency, notify PM, **never** auto-send | 6 |
| CI-F22 | Missing | Role filters on some routes | Role-tailored response shapes (client / PM / leadership) from same fact models | 5 |

### 4.2 Data inputs — CI-D01–CI-D15

| ID | Status | Existing evidence | Exact missing behavior | Phase |
|---|---|---|---|---:|
| CI-D01 | Partial | `projects`, `throughput_snapshots`, `delivery_confidence_scores` via Delivery adapter | Freshness SLA + complete sensitivity classification | 1 |
| CI-D02 | Partial | `milestones` via Delivery/Milestone adapters | Milestone Intelligence UI; production milestone policy | 1–2 |
| CI-D03 | Partial | `throughput_snapshots` actual/forecast in pack; Delivery Trend | Governed plan series (`PLAN_SERIES_UNAVAILABLE` sibling limitation — throughput itself is not unavailable) | 1–2 |
| CI-D04 | Partial | `quality_snapshots` via Quality adapter | Broader QA/rework contract coverage | 1–2 |
| CI-D05 | Partial | `utilization_snapshots` via Workforce adapter | Stronger client-safe aggregated resource projection | 1–3 |
| CI-D06 | Partial | `project_skill_requirements`, `capability_gaps` | Aggregated SME coverage without identities | 1–3 |
| CI-D07 | Unavailable | No approved Workflow Status source (`WORKFLOW_STATUS_UNAVAILABLE`). `project.status` is CI-D01; bottlenecks remain CI-D10 | Dedicated workflow-status source | 1–2 |
| CI-D08 | Partial | `utilization_snapshots` capacity facts | Aggregated capacity-vs-demand for readiness | 1–3 |
| CI-D09 | Unavailable | No governed backlog queue (`BACKLOG_QUEUE_UNAVAILABLE`) | Explicit backlog queue source | 1–2 |
| CI-D10 | Partial | `risk_alerts`, `bottlenecks`, `governance_escalations`, `project_dependencies` (multi-owner) | Client-visible material risk publication policy | 1–2 |
| CI-D11 | Partial | `knowledge_documents` / chunks via Knowledge adapter | Broader approved SOP publication | 1, 5 |
| CI-D12 | Partial | Knowledge docs + `training_programs` / `training_records` | Training retrieval for readiness | 1, 3 |
| CI-D13 | Partial | `project_charters`, `project_scope_states`, knowledge docs | Charter completeness for planning dimension | 1–3 |
| CI-D14 | Unavailable | No dedicated communication-note source (`CLIENT_COMMUNICATION_NOTES_UNAVAILABLE`). Lifecycle records are not approved unstructured notes | Dedicated communication-note source | 1, 5 |
| CI-D15 | Partial | Knowledge docs + `governance_escalations` / `governance_actions` | Client-safe escalation-note publication | 1–3 |

*Note: Status reflects `source_coverage.py` and real adapter allowlists. Partial = governed adapter source with unresolved freshness and/or incomplete coverage. Unavailable = explicit blocked reasons; do not fabricate facts.*

### 4.3 Outputs — CI-O01–CI-O10

| ID | Status | Existing evidence | Exact missing behavior | Phase |
|---|---|---|---|---:|
| CI-O01 | Partial | Typed `ProjectHealthAssessment` only; no snapshot/API | Persist assessments + client-safe projection endpoint | 2–4 |
| CI-O02 | Partial | `ClientCommunication` executive_summary type | Full executive content contract + evidence versioning | 4 |
| CI-O03 | Partial | Typed `DeliveryConfidenceAssessment`; Delivery score consumed unchanged | Persist assessments + client-safe narrative/API | 2–4 |
| CI-O04 | Missing | — | Versioned readiness assessment + dimensions | 3–4 |
| CI-O05 | Partial | Typed Risk Transparency assessment with contract integrity; no narrative | Risk narrative insight/report component | 2–4 |
| CI-O06 | Missing | — | Go-live readiness report with limitations | 4 |
| CI-O07 | Partial | Weekly communication lifecycle | Full weekly content + scheduling + stale protection | 4–6 |
| CI-O08 | Partial | Mitigation remains UNAVAILABLE in Risk Transparency; upstream mitigations/actions exist elsewhere | Client-safe mitigation plan summary | 2–4 |
| CI-O09 | Missing | Delivery recommendations ≠ CI typed set | Evidence-linked CI recommendations with visibility | 3 |
| CI-O10 | Partial | `AgentQuery` + evidence links | Grounded CI answer; no zero-evidence “normal” answers | 5 |

### 4.4 Governance / non-functional — CI-G01–CI-G10, CI-N01–CI-N04

| ID | Status | Existing evidence | Exact missing behavior | Phase |
|---|---|---|---|---:|
| CI-G01 | Missing | Placeholder answers can assert grounding without content use | Claim validator + insufficiency path for CI outputs | 1–4 |
| CI-G02 | Partial | `require_evidence` on drafts/queries | Evidence for insights/readiness/recommendations; visibility field | 1 |
| CI-G03 | Partial | QI/governance put confidence in `retrieval_params`; CI placeholder does not | Mandatory confidence when reliability discussed | 2–5 |
| CI-G04 | Partial | Org/project RBAC, CLIENT sent-only comms | Persona field redaction matrix §17; negative CI tests | 1–5 |
| CI-G05 | Partial | Quality summary CLIENT stripping; knowledge visibility | Workforce identity redaction; PM-note protection; no cross-client examples | 1–5 |
| CI-G06 | Partial | Send requires approval; stale fingerprint blocks Approve/Send; legacy null fingerprint disclosed | Scheduled job must not approve/send; channel policy | 4–6 |
| CI-G07 | Partial | Platform audit logs; query/comms evidence | Full lineage for CI snapshots/assessments | 1–6 |
| CI-G08 | Missing / Blocked | — | Production client data approval gate (process + feature flags) | 6 |
| CI-G09 | Missing / Blocked | — | Pilot synthetic/sanitized checklist + human-reviewed outputs | 6 |
| CI-G10 | Missing | — | Data-quality states before intelligence generation | 1 |
| CI-N01 | Missing | — | Near-real-time dashboard SLO for ingested data | 5–6 |
| CI-N02 | Missing | Delivery portfolio exists separately | Multi-project nav inside authorized scope without leakage | 5–6 |
| CI-N03 | Missing | — | Graceful missing/stale/conflicting handling in CI | 1–5 |
| CI-N04 | Partial | Knowledge prompt-security tests exist | CI Q&A + retrieved-doc injection resistance | 5–6 |

---

## 5. Existing reusable components

### 5.1 Safe public / shared contracts (prefer these)

| Domain | Reuse |
|---|---|
| **Delivery Performance** | `get_dashboard_data`; delivery confidence / throughput / milestone / risk-alert HTTP APIs and ORM rows; scoring results as **facts**, not re-derived |
| **Quality Intelligence** | `generate_quality_summary` / `QualitySummaryRead`; quality-summary HTTP; weekly comms prompt only as temporary narrative aid until CI narratives own prompts |
| **Workforce & Capability** | Aggregated KPI/gap/training **services** after building a client-safe projection; redirect classification already points client-comms questions at Client Interaction |
| **Project Governance** | Scoped dependencies/actions/escalations/summaries/charters; `fetch_governance_delivery_signals`; approved document refs |
| **Operational Knowledge** | Visibility-aware retrieval; `CLIENT_SAFE` filtering; approved/indexed readiness for RAG |
| **Shared platform** | `get_visible_project`; `EvidenceInput` / `require_evidence`; `LLMClient`; `Notification` + `COMMUNICATION_PENDING`; communications lifecycle service; audit log patterns; RBAC `require_role` / RLS policies |

### 5.2 Private agent internals (must not import)

| Domain | Avoid |
|---|---|
| Delivery | Chat/conversation private services; event-bus handlers; recalculating confidence inside CI |
| Quality | `quality_intelligence.evidence_pack.EvidencePack`; root-cause/reviewer attribution; drift internals as client payloads |
| Workforce | Annotator identity lists, raw skill matrices, individual utilization as client-facing fields |
| Governance | Unapproved draft charters/summaries; unrestricted analytics as client projection |
| Knowledge | Internal-only documents; `_`-prefixed retrieval helpers bypassing visibility |

### 5.3 Pattern to copy (not copy-paste private code)

Quality Intelligence’s evidence-pack + citation validation pattern (`evidence_pack.py`, `citations.py`) is a **design reference** for `ClientEvidencePack` + claim validation. CI must implement its **own** pack under `backend/app/agents/client_intelligence/`, not import Quality’s pack as the client contract.

---

## 6. Data-model gap analysis (roadmap Section 14)

### 6.1 Existing entities — reuse / extend

| Concept | Existing table | Extension required? | Indexes / RLS / audit / evidence |
|---|---|---|---|
| Orgs, users, projects, milestones | Yes | None for identity; milestone risk/progress fields as Delivery owns them | Existing RLS |
| Throughput | `throughput_snapshots` | Likely need explicit **plan** series support (no `units_plan` today) | Existing indexes; plan source TBD |
| Delivery confidence | `delivery_confidence_scores` | CI stores **reference** + explanation, does not replace | Existing |
| Quality | `quality_snapshots` + sanitized summary API | None for storage; projection rules in CI | Existing |
| Risks / bottlenecks / mitigations | `risk_alerts`, `bottlenecks`, `mitigation_recommendations` | Client-visibility classification may need column or projection rules | Existing |
| Workforce aggregates | utilization/skills/training/gaps tables | **New projection contract**, not necessarily new tables | Must not expose identities |
| Governance | dependencies/actions/escalations/charters/summaries | Consume approved/scoped rows | Existing |
| Knowledge | documents/chunks + visibility | Ensure project-scoped approved client-safe retrieval metadata | Existing visibility enum |
| Communications | `client_communications` + evidence links | Extend `CommunicationType` for readiness/go-live; reject reason; evidence fingerprint / prompt/model version fields | Extend RLS as needed; append-only sent bodies |
| Agent queries | `agent_queries` + evidence links | Confidence/insufficiency already partly via `retrieval_params`; formalize for CI | Existing indexes |
| CSAT | `client_csat_scores` | Read models / aggregation views or queries | Unique (project, user, month) exists |
| Metrics | `metric_configurations` | CI visibility keys / thresholds | Existing `is_client_visible` |
| Notifications / audit | `notifications`, audit logs | Wire CI draft-ready events | Existing |

### 6.2 Proposed CI concepts — genuinely new

| Concept | Reuse? | New table required? | Requirements |
|---|---|---|---|
| `client_intelligence_snapshots` | No equivalent | **Yes — implemented (Phase 1 substrate)** | Append-only RLS (SELECT/INSERT); idempotency UNIQUE NULLS NOT DISTINCT including `policy_fingerprint`; link identity UNIQUE `(id, org_id, project_id, source_fingerprint)` |
| `client_readiness_assessments` | No (knowledge retrieval readiness ≠ this) | **Yes** | Deferred — **CI-DQ08 unresolved**; do not invent readiness schema yet |
| `client_readiness_dimensions` | No | **Yes** | Deferred — blocked on CI-DQ08 |
| `client_intelligence_insights` | No | **Yes** | Deferred (Phase 2+) |
| `client_intelligence_recommendations` | Delivery mitigations insufficient | **Yes** (or extend platform recs **only if** client visibility + readiness linkage preserved) | Deferred (Phase 2+) |
| `client_intelligence_evidence_links` | Comms/query evidence links are narrower | **Yes — snapshot-scoped links implemented** | Composite FK to snapshot identity; visibility; claim_keys JSON array CHECK; source fingerprint; append-only RLS |

**Phase 1 note:** Snapshot + snapshot-scoped evidence-link migration exists with savepoint idempotency and append-only policies. Loads and idempotent reuses share fail-closed integrity verification (reconstruct, re-validate, row↔payload + link consistency; CLIENT_SAFE stored form must already be persistence-redacted). Application auth rejects CLIENT/Leadership writes; Leadership INTERNAL reads fail closed until an approved sanitized aggregate scope exists. Super Admin operational “explicit scope” beyond `get_visible_project` + RLS INSERT is **not** fully solved. Live migration/RLS CI gate remains open.

**Phase 2 note (bounded):** Project Health contracts + policy-injected deterministic engine foundation landed with exact source ownership/availability binding, **engine-owned pack source-quality resolution** (policies cannot upgrade/downgrade/invent `data_quality`), whole-driver reliability checks, pack-limitation propagation, Decimal-safe/float-rejected observed values, and sanitized policy-boundary errors. Injected policies classify verified pack facts only; they cannot invent Delivery Confidence or other source facts. **Delivery Confidence Intelligence foundation** (`assess_delivery_confidence`) consumes Delivery-owned score/status/forecast/milestone, deep-copies validated packs, passes only an isolated verified candidate context to the explanation policy, requires pack-owned candidate source quality (no COMPLETE fallback), separates structured engine/policy limitation codes from pack `source_limitations` text, aggregates top-level evidence across core/history/driver lineage, and enforces closed driver↔candidate↔evidence plus exact nullable timestamp binding. Unreliable current confidence does not evaluate the explanation policy. **Risk Transparency foundation** (`assess_risk_transparency`) builds verified risk/bottleneck candidates from validated packs, enforces public contract integrity (source-type/table/agent/status/tier/type/claim/category closure; exact top-level evidence = item union; reject UNDECIDED published visibility; AVAILABLE requires valid `rules_version`; missing-policy assessments require fail-closed policy limitations; candidate keys bound to `source_type`+`source_row_id.hex`; published source identities unique), fails closed on mixed populated source quality that would hide incomplete coverage, isolates an injected selection policy (never the pack), fails closed without a production materiality/client-visibility policy, keeps CLIENT_SAFE publication fail-closed, and leaves business impact (`CI-DQ09`) and mitigation UNAVAILABLE with required limitation codes. **Delivery Trend foundation** (`assess_delivery_trend`) adds bounded `throughput_series` with exact claim-to-fact binding and full latest↔series equality, aligns actual/forecast on daily UTC grain with explicit missing plan/forecast states, keeps missing source quality as `None` (never invents UNAVAILABLE/COMPLETE), binds published deviations exactly to COMPLETE trend points, enforces public reporting-window/ordering/UTC-midnight/policy-provenance/evidence-union closure, excludes rolling-seven-day claims from trend output, computes exact arithmetic deltas only, isolates deviation materiality policy (unreliable source uses `DEVIATION_NOT_EVALUATED_UNRELIABLE_SOURCE` without reading `rules_version`), fails closed for CLIENT_SAFE actual/forecast, and never interpolates or invents plan values. **Accelerated internal overview API** (`GET /api/v1/projects/{project_id}/client-intelligence/overview`) exposes all four engines from one governed `ClientEvidencePack` with `policy=None` / `explanation_policy=None` (no production policies invented). Internal roles only (`delivery_manager`, `bsg_leadership`, `super_admin`); read-only; no persistence. Project Health and Risk Transparency may remain unavailable until governed policies exist; Delivery Trend may remain partial without plan evidence. **Accelerated internal overview UI:** `/client-intelligence` now uses the governed Projects API as an authorized project navigator and loads one selected project's overview. It renders all four accepted assessments and preserves partial/insufficient/unavailable states; the former mock client portfolio, CSAT, report, narrative, and Q&A content was removed from this route. This remains project-level intelligence, not a completed client portfolio aggregate. **No production health/explanation/risk/trend/change materiality policy/thresholds (CI-DQ07/CI-DQ09 open).** CI-F01 / CI-F02 / CI-F03 / CI-F04 / CI-F05 / CI-O01 / CI-O03 / CI-O05 / CI-O08 remain partial. No assessment persistence/client-safe API/narrative/report/Q&A. **Change Intelligence foundation (TASK 14 / CI-F06 bounded):** `build_change_comparison`, `build_change_candidates`, and `assess_change_intelligence` compare two validated, aligned `ClientEvidencePack` instances in memory only; candidate detection is deterministic, evidence-linked, and source-identity closed (`ChangeSourceRowIdentity`, exact claim binding, period-aware source limitations, immutable `org_id`/`project_id`/`comparison_period` on candidates and published items); materiality/business meaning require an injected `ChangeMaterialityPolicy` (no production policy); `policy_evaluated` records whether reliable candidates were passed to policy (including zero-selection outcomes); missing previous pack → `PREVIOUS_REPORTING_CYCLE_UNAVAILABLE`; missing policy → `CHANGE_MATERIALITY_POLICY_UNAVAILABLE` with `policy_evaluated=false` and no published material changes; `detected_candidate_count` / `evaluated_candidate_count` / `published_change_count` have distinct semantics; availability is capped at `PARTIAL` for this bounded foundation; domain coverage separates evaluated/no-change, unavailable, unreliable, and policy-not-evaluated; milestone/risk set-difference does not infer creation/closure; mixed unreliable coverage surfaces `CHANGE_NOT_EVALUATED_UNRELIABLE_SOURCE` even when other domains evaluate; readiness and resource onboarding remain explicitly unavailable. Milestone Intelligence, Today’s Insight, and Phase 3 readiness were **not** started. Readiness / insight / recommendation tables remain blocked until CI-DQ08 and later engines are defined.

### 6.3 Evidence link gaps on existing tables

`CommunicationEvidenceLink` / `AgentQueryEvidenceLink` today store `source_table`, `source_row_id`, `description` only — **no** visibility classification, claim key, or source timestamp/fingerprint (roadmap §7.3 / §14.2).

---

## 7. API gap analysis (roadmap Section 15)

### 7.1 Reusable endpoints

| Endpoint | Reuse |
|---|---|
| GET/POST communications lifecycle | Extend for report types, reject reason, stale checks, richer draft context |
| POST/GET `/agent-queries` (+ GET by id) | Replace placeholder handler for `client_interaction_agent` / rename to Client Intelligence agent name after CI-DQ01 |
| POST `/projects/{id}/csat` | Keep; add reads |
| Delivery / quality / workforce / governance / knowledge source APIs | Consume as upstream facts |

### 7.2 Endpoints requiring extension

| Endpoint | Extension |
|---|---|
| POST `.../communications/draft` | Broader evidence pack; readiness/go-live types; structured generation; fix `EvidenceInput` import; honor instructions or drop field |
| PATCH/POST review/approve/reject/send | Reject reason; stale-approval; audit completeness |
| POST `/agent-queries` | CI query handler, project requirement, insufficiency semantics (CI-DQ06) |
| CSAT | GET list/aggregate/trend with sample policy (CI-DQ13) |
| Metric configurations | CI visibility policy keys |

### 7.3 Missing endpoints

**Internal:**

- `GET /projects/{id}/client-intelligence/overview` — **implemented (accelerated slice):** read-only internal overview from one evidence pack + four engines; no persistence
- `GET /client-intelligence/projects`
- `GET /projects/{id}/client-intelligence/dashboard`
- `GET /projects/{id}/client-intelligence/changes`
- `GET /projects/{id}/client-intelligence/risks`
- `GET /projects/{id}/client-intelligence/readiness`
- `POST /projects/{id}/client-intelligence/readiness/assess`
- `GET /projects/{id}/client-intelligence/recommendations`

**Client-facing:**

- `GET /client/projects`
- `GET /client/projects/{id}/intelligence`
- `GET /client/projects/{id}/reports` (or enforce sent-only via existing communications list with dedicated client DTO)

### 7.4 Current RBAC behavior (relevant)

| Capability | Current | Gap vs §17 |
|---|---|---|
| Communications draft/review/approve/send | DM + Super Admin | Leadership “read/request” nuance unresolved |
| Communications list for CLIENT | `SENT` only | Good baseline |
| CSAT submit | CLIENT only | Aligns |
| Agent queries | CLIENT own queries; DM org | CI project-scope + role-shaped answers missing |
| Super Admin | Broad operational access patterns elsewhere | Must not silently bypass tenant isolation for CI (explicit test requirement) |

### 7.5 Response-contract gaps

Dashboard/Q&A responses lack mandatory fields from §15.3: `as_of`, reporting period, data-quality/freshness, confidence, limitations, safe evidence links, source-agent attribution (internal), and client-mode exclusion of internal-only fields.

---

## 8. Testing gap analysis

### 8.1 Existing relevant tests

Listed in §2.16. Coverage is upstream (delivery scoring, quality summary/comms, workforce redirect, knowledge security, platform RBAC)—**not** Client Intelligence acceptance.

### 8.2 Missing suites (roadmap §18 / §21.3)

| Required suite | Status |
|---|---|
| `test_client_intelligence_evidence.py` | Present, with persistence, validation, provenance, and source-coverage companion suites |
| `test_client_intelligence_project_health.py` | Present — foundation only; fixture policies are not production thresholds |
| `test_client_intelligence_confidence.py` | Covered by delivery-confidence and confidence-history suites |
| `test_client_intelligence_risk.py` | Present |
| `test_client_intelligence_changes.py` | Present |
| `test_client_intelligence_readiness.py` | Missing |
| `test_client_intelligence_recommendations.py` | Missing |
| `test_client_intelligence_narratives.py` | Missing |
| `test_client_intelligence_query.py` | Covered by `test_client_intelligence_qa.py` and API tests |
| `test_client_intelligence_communications.py` | Covered across communications lifecycle/RBAC and Client Intelligence provenance/stale-evidence suites |
| `test_client_intelligence_rbac.py` | Covered across visibility, governance, API, and provenance acceptance suites |
| `test_client_intelligence_acceptance.py` | Partial — focused API/provenance acceptance exists; full cross-phase acceptance remains open |
| Phase 0 contract fixtures | Missing |
| Scheduler/idempotency/stale-draft tests | Partial — evidence idempotency and stale-evidence integration exist; scheduled weekly draft coverage remains open |
| Internal overview and client portal API/UI integration / a11y / no-mock route gates | Partial — API-backed routes and focused UI tests exist; full accessibility and cross-persona acceptance remain open |
| AI evaluation set (§12.3 / §18.5) | Missing |

Dedicated communications route tests are present. CSAT read/aggregation coverage remains incomplete.

---

## 9. Product blockers (roadmap Section 22)

Copied unresolved decisions. **This audit does not resolve them by assumption.**

### 9.1 Blockers for Phase 1 (and Phase 0 exit for Phases 1–5)

| ID | Decision | Why it blocks Phase 1 |
|---|---|---|
| CI-DQ01 | Confirm Client Intelligence as canonical name | Package/API/agent_name/analytics consistency |
| CI-DQ02 | Is source DOCX authoritative over derived docs for readiness/go-live? | Scope of evidence adapters and later readiness fields |
| CI-DQ03 | Client list = navigator only vs portfolio intelligence? | Prevents wrong APIs/UI aggregates in foundation |
| CI-DQ04 | Which metrics/evidence are client-visible? | **Core** to `ClientEvidencePack` visibility classification |
| CI-DQ05 | Q&A immediate vs PM-reviewed? | Affects query persistence/approval contracts touching evidence APIs |
| CI-DQ06 | Exact insufficient-evidence API behavior | Evidence/query response semantics |
| CI-DQ07 | Project-health formula and thresholds | **Unresolved.** Engine is policy-injected; no production default policy or hardcoded thresholds. Missing policy → `INSUFFICIENT` / `POLICY_UNAVAILABLE`. Client Master bulk Health remains `not_assessed` / `health_status=null` and must **not** reuse Delivery Confidence status. Delivery Confidence history sparkline reads persisted `delivery_confidence_scores` only and does **not** invent CI confidence thresholds. |
| CI-DQ08 | Readiness dimensions, weights, blockers, approval owner | Roadmap: **before Phase 1 migration** |

### 9.2 Decisions that can wait until later phases

| ID | Decision | Earliest needed |
|---|---|---|
| CI-DQ09 | How business impact may be quantified (**unresolved**: Risk Transparency keeps impact UNAVAILABLE with `BUSINESS_IMPACT_POLICY_UNRESOLVED`) | Before Phase 2 completion |
| CI-DQ10 | Manual vs scheduled weekly drafts and cadence | Before Phase 4 |
| CI-DQ11 | In-app only vs export/email/download | Before Phase 4 UI |
| CI-DQ12 | Evidence links visible directly vs safe labels | Before Phase 5 |
| CI-DQ13 | CSAT aggregation and minimum sample policy | Before Phase 5 |
| CI-DQ14 | LLM provider, pinned model, data residency | Before Phase 4 production |
| CI-DQ15 | Baselines/survey definitions for business targets | Before pilot |

---

## 10. Recommended technical build order

Numbered small implementation tasks. **First implementation task after this audit:**

1. **Client Intelligence contracts and client-safe evidence pack foundation.**  
   Freeze naming (pending CI-DQ01), typed contracts, visibility classes, data-quality states, reporting-period resolver interface, and `ClientEvidencePack` assembly from authorized sources—without LLM narration.

Then:

2. Resolve Phase 1–blocking open decisions (Section 9.1) with product/security sign-off; capture acceptance fixtures for green/amber/red/missing/stale/conflicting.
3. ~~Schema migration for CI evidence snapshots + evidence links~~ **Done (Phase 1 substrate).** Readiness/insight/recommendation schema remains deferred until CI-DQ08.
4. Implement source adapters for CI-D01–CI-D15 (explicit `unavailable` where blocked) + RBAC retrieval matrix tests.
5. Wire routes/UoW owners to call `persist_client_evidence_snapshot` when a durable snapshot is required; claim-to-evidence validator already gates persistence. Do **not** auto-persist from the pack builder.
6. Project Health Engine (deterministic) + history comparison.
7. Delivery Confidence Intelligence (consume Delivery scores; explain only).
8. Risk Transparency + business-impact mapping (after CI-DQ09).
9. Delivery Trend Engine (actual/plan/forecast; mark missing plan).
10. Change Intelligence + Milestone Intelligence + Today’s Insight fact models.
11. Readiness scoring engine (five dimensions + cross-cutting factors) + versioned assessments (**after CI-DQ08**).
12. Gap analysis + Recommendation/Guidance Engine (five recommendation types).
13. Harden communications lifecycle (reject reason, stale approval, report types, richer draft context).
14. Narrative generation with structured schema, claim validation, redaction, deterministic fallback.
15. Internal dashboard API + replace `/client-intelligence` mocks (navigator-only list). **Bounded project-level overview completed; no persistence or production policy added.**
16. Client-facing intelligence / reports / CSAT read APIs + replace `/client*` mocks.
17. Grounded CI Q&A handler replacing placeholder `client_interaction_agent` answers.
18. Role-tailored projections (CI-F22) and evidence UX per CI-DQ12.
19. Scheduled weekly drafts + notifications (CI-F21); never auto-send.
20. Inter-agent integration tests, security/RBAC negative matrix, performance SLOs, pilot hardening (Phase 6).
21. Defer portfolio, sentiment, predictive escalation to Phase 7 (explicit approval).

---

## Validation notes (audit task)

- Pre-change git status included unrelated user changes to `docs/AI Agents/05. Client Interaction Agent.md` and untracked roadmap/media; those were **not** modified by this audit.
- This task creates **only** `backend/app/agents/CLIENT_INTELLIGENCE_V1_GAPS.md`.
- No production application code was changed.

---

*Update this gap audit when Phase 1 contracts land or when an open decision changes a requirement’s status.*
