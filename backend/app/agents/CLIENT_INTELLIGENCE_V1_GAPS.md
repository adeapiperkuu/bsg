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

- **Communications lifecycle (CI-F09 / CI-F20 / CI-O02 / CI-O07):** Real CRUD and RBAC exist under `backend/app/api/routes/communications.py` + `backend/app/services/communications.py`. Gaps include reject-without-reason, no stale-approval/evidence fingerprint, send is status-only (no channel policy), draft context is throughput + optional quality only (not milestones/confidence/risks/readiness/changes), `CommunicationType` lacks readiness/go-live report types, and narrative claim validation is absent.
- **Agent query infrastructure (CI-F16 / CI-O10 substrate):** `client_interaction_agent` is registered in `SUPPORTED_AGENTS` (`backend/app/services/agent_queries.py`) and queries persist with evidence links, but answers are a **placeholder** string—not Client Intelligence retrieval or grounded answering.
- **CSAT (CI-F19):** Submit-only; no read aggregation, trend, sample disclosure, or UI.
- **Upstream data sources (CI-D01–CI-D15):** Most structured sources exist in other agents’ tables/APIs; Client Intelligence has **no adapters**, no `ClientEvidencePack`, and no client-safe projection layer.
- **Metric visibility config:** `MetricConfiguration.is_client_visible` exists; not wired into a Client Intelligence visibility policy.

### Placeholder / mock-only

| Area | Evidence |
|---|---|
| Agent module | `backend/app/agents/client_interaction.py::draft_placeholder` — dead stub; zero callers |
| Q&A answers | `answer_query` fallback: `"The LLM provider is not configured yet; this response is grounded in the attached evidence placeholders."` |
| Comms drafts without LLM / on LLM error | `COMMS_PLACEHOLDER_BODY` in `communications.py` |
| Internal dashboard `/client-intelligence` | Hardcoded KPIs + `clients` fixture from `frontend/src/lib/bsg/data.ts` |
| Client portal `/client`, `/client/status`, `/client/reports`, `/client/ask` | Static literals / synthetic chart / hardcoded chat reply |
| Portfolio-style CSAT card | UI text “across 8 clients” — Phase 7 future scope, mock only |

### Completely missing

- `backend/app/agents/client_intelligence/` package and all engines (health, confidence explanation, risk transparency, trends, changes, milestones, readiness, recommendations, narratives, validation, query handler).
- Section 14 CI tables: snapshots, readiness assessments/dimensions, insights, recommendations, CI evidence links.
- Section 15 Client Intelligence and client-facing intelligence APIs.
- Client-safe workforce aggregation projection (no identities).
- Readiness / go-live assessment and recommendation engines.
- Deterministic “Today’s Insight”, change intelligence, and reporting-period resolver.
- Claim-to-evidence validators, client-safe redaction validators, scheduled weekly drafts.
- Dedicated CI test suites (roadmap Section 18 / Section 21.3).
- Frontend `frontend/src/features/client-intelligence/` and live API wiring.

**Conclusion (aligned with roadmap §3.4):** Platform primitives exist; the Client Intelligence capability itself is **not implemented**. Route and service names must not be treated as completion.

---

## 2. Current backend inventory

### 2.1 `backend/app/agents/client_interaction.py`

| Symbol | Status |
|---|---|
| `draft_placeholder(subject: str) -> str` | **Placeholder only.** Returns a static “awaits LLM provider” string. **No callers** in the repository. |

There is **no** `client_intelligence` package. Live draft generation does not use this module.

### 2.2 `backend/app/services/communications.py`

| Symbol | Behavior | CI gap |
|---|---|---|
| `COMMS_PLACEHOLDER_BODY` | Static placeholder when LLM key missing or `ApiError` | Explicit mock narrative |
| `build_comms_context` | JSON from latest throughput + optional `QualitySummaryRead` or raw quality snaps/drift alerts | Missing milestones, confidence, risks, readiness, changes, mitigations |
| `generate_comms_draft_body` | Hybrid: LLM via `LLMClient.generate_structured` + `COMMS_SYSTEM_PROMPT` from Quality Intelligence; else placeholder | No structured schema, claim validation, or deterministic template fallback matching roadmap §10.3 |
| `create_draft` | Creates `ClientCommunication` with `drafted_by_agent="client_interaction_agent"`; requires evidence; writes `CommunicationEvidenceLink` | Agent name still “client_interaction”; no evidence visibility / freshness fingerprint |
| `move_to_review` / `approve` / `reject` / `send` | Status transitions; `send` requires `APPROVED` + `approved_by` | `reject` has **no reason**; no stale-approval check; `send` is **in-app status flip only** |
| `get_visible_communication` | CLIENT: same org + `SENT` only | Aligns with client-sent-only rule; no client-safe field redaction beyond status filter |

### 2.3 `backend/app/services/agent_queries.py`

| Symbol | Behavior |
|---|---|
| `SUPPORTED_AGENTS` | Includes `"client_interaction_agent"` |
| `answer_query` | Routes quality → `answer_quality_query`; governance → `answer_governance_query`; **all other agents including `client_interaction_agent`** fall through to placeholder answer + evidence persistence |

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
| PATCH | `/communications/{communication_id}/review` | DM / SA | |
| POST | `/communications/{id}/approve` | DM / SA | |
| POST | `/communications/{id}/reject` | DM / SA | No reject reason payload |
| POST | `/communications/{id}/send` | DM / SA | Status publication only |

**Defect:** Route body constructs `EvidenceInput(...)` but does **not** import `EvidenceInput` from `app.services.evidence` (service layer does). Draft creation would raise `NameError` at runtime unless fixed before use.

`CommunicationDraftCreate.instructions` is accepted by schema and **unused** by the route.

### 2.5 `backend/app/api/routes/agents.py`

| Method | Path | CI relevance |
|---|---|---|
| POST | `/agent-queries` | Accepts `client_interaction_agent`; gathers throughput (or quality for QI) evidence; returns placeholder answer for CI |
| GET | `/agent-queries` | List with CLIENT=own / DM=org filtering |
| GET | `/agent-queries/{query_id}` | Same RBAC |

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

### 3.1 Routes (all mock)

| File | Path | Data source | Live API? |
|---|---|---|---|
| `frontend/src/routes/client-intelligence.tsx` | `/client-intelligence` | `clients` from `@/lib/bsg/data` + hardcoded KPIs, draft queue, Q&A snippets | **No** |
| `frontend/src/routes/client.index.tsx` | `/client/` | Inline “Aurora Health”, 92%, static milestones/updates | **No** |
| `frontend/src/routes/client.status.tsx` | `/client/status` | Inline KPIs; `trend` via `Math.sin` | **No** |
| `frontend/src/routes/client.reports.tsx` | `/client/reports` | Inline “Approved” list; Download/View inert | **No** |
| `frontend/src/routes/client.ask.tsx` | `/client/ask` | Local state; fixed reply about batch 14 / 94% confidence | **No** |

Shared widgets used: `Card`, `SectionHeader`, `KpiCard`, `AiBadge`, `StatusPill` from `@/components/bsg/widgets`. `EvidenceBadge` is **not** used on CI routes.

### 3.2 `frontend/src/lib/bsg/data.ts`

`export const clients = [...]` — eight mock clients (Aurora Health, Helios Bank, …) with health/confidence/CSAT. Consumed by `client-intelligence.tsx` (and unrelated analytics mock).

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

`frontend/src/features/client-intelligence/` — **absent**. Roadmap §21.2 components (`ClientIntelligenceDashboard`, `ProjectHealthCard`, `ReadinessOverview`, `EvidenceDrawer`, etc.) — **all missing**.

### 3.6 Phase 7 leakage in mock UI

Internal KPI card shows “Avg CSAT … across 8 clients” — portfolio aggregate presentation. Core phases must treat client list as **navigator only**; such aggregates require Phase 7 approval.

---

## 4. Requirement traceability

Status legend: **Implemented** / **Partial** / **Missing** / **Mock only** / **Blocked**.

### 4.1 Functional — CI-F01–CI-F22

| ID | Status | Existing evidence | Exact missing behavior | Phase |
|---|---|---|---|---:|
| CI-F01 | Missing | Delivery/quality/risk source APIs exist; no CI health engine | Evidence-backed project health classification with drivers/limitations | 2 |
| CI-F02 | Partial | `DeliveryConfidenceScore` + GET delivery-confidence; Delivery analytics | CI explanation layer: band, drivers, limitations, next-milestone reliability narrative; no inventing scores | 2 |
| CI-F03 | Missing | `RiskAlert` + list endpoint | Client-safe business-language risk narratives from typed facts | 2 |
| CI-F04 | Missing | Mitigation recommendations / governance actions exist upstream | Quantified business impact + mitigation progress in client-safe form | 2 |
| CI-F05 | Partial | `ThroughputSnapshot.units_completed` / `units_forecast`; no `units_plan` column | Aligned actual vs plan vs forecast series with missing-value marking | 2 |
| CI-F06 | Missing | — | Change intelligence vs prior reporting cycle | 2 |
| CI-F07 | Partial | `Milestone` model + list API; frontend mock tables | Deterministic on-track counts, at-risk reasons, next key milestone selection for CI | 2 |
| CI-F08 | Partial | `generate_comms_draft_body` + LLM/placeholder | Executive narratives from full evidence pack + claim validation + deterministic fallback | 4 |
| CI-F09 | Partial | `CommunicationType` weekly/executive/ad_hoc + draft API | Readiness/go-live report types; full required content sections | 4 |
| CI-F10 | Missing | Knowledge `RetrievalReadinessAssessment` is unrelated | Overall readiness score + dimension breakdown | 3 |
| CI-F11 | Missing | Upstream workforce/governance/quality data | Resources, training, planning, tracking, risk-preparedness dimensions | 3 |
| CI-F12 | Missing | SME/training/quality/historical sources exist elsewhere | Cross-cutting readiness reasoning without identity leakage | 3 |
| CI-F13 | Missing | — | Gaps, confidence level, mitigation recommendations | 3 |
| CI-F14 | Missing | — | Go-live readiness report + human sign-off state | 4 |
| CI-F15 | Missing | Delivery `MitigationRecommendation` is different concept | Pre-go-live, training, resource, mitigation, pilot-validation recommendation types | 3 |
| CI-F16 | Mock only / Partial | POST `/agent-queries` + UI shell on `/client/ask` | Project-scoped CI conversational pipeline; UI is hardcoded | 5 |
| CI-F17 | Missing | Evidence links persist but answer ignores content | Answer only from authorized structured + approved unstructured evidence | 5 |
| CI-F18 | Mock only | Hardcoded “Delivery narrative” / “Today” style copy in UI | Deterministic recent changes + Today’s Insight fact set | 5 |
| CI-F19 | Partial | POST `/projects/{id}/csat` | Read aggregation, trend, sample disclosure, UI | 5 |
| CI-F20 | Partial | Communications review/approve/reject/send | Reject reason; stale approval; client-invisible drafts already partly enforced | 4 |
| CI-F21 | Missing | `NotificationType.COMMUNICATION_PENDING` exists | Scheduled weekly drafts, idempotency, notify PM, **never** auto-send | 6 |
| CI-F22 | Missing | Role filters on some routes | Role-tailored response shapes (client / PM / leadership) from same fact models | 5 |

### 4.2 Data inputs — CI-D01–CI-D15

| ID | Status | Existing evidence | Exact missing behavior | Phase |
|---|---|---|---|---:|
| CI-D01 | Partial | Throughput / delivery dashboard | CI adapter + freshness/sensitivity classification | 1 |
| CI-D02 | Partial | `milestones` table/API | CI milestone intelligence adapter | 1–2 |
| CI-D03 | Partial | `throughput_snapshots` | CI trend adapter; plan series gap | 1–2 |
| CI-D04 | Partial | Quality snapshots + sanitized summary | CI quality summary without reviewer detail | 1–2 |
| CI-D05 | Partial | Workforce allocation/utilization | **Client-safe** aggregated resource projection | 1–3 |
| CI-D06 | Partial | `Annotator.is_sme_certified`, SME allocation APIs | Aggregated SME coverage without identities | 1–3 |
| CI-D07 | Partial | Delivery workflow/bottleneck signals | CI workflow status in evidence pack | 1–2 |
| CI-D08 | Partial | Workforce capacity/demand surfaces | Aggregated capacity-vs-demand for readiness | 1–3 |
| CI-D09 | Partial | Delivery backlog/throughput context | Explicit backlog queue in CI pack | 1–2 |
| CI-D10 | Partial | `risk_alerts`, governance escalations, quality risks | Client-visible material risk selection + categorization | 1–2 |
| CI-D11 | Partial | Knowledge docs with `client_safe` | Approved project-scoped SOP retrieval adapter | 1, 5 |
| CI-D12 | Partial | Knowledge + workforce training docs/APIs | Training document retrieval for readiness | 1, 3 |
| CI-D13 | Partial | Governance charters + knowledge | Charter completeness signals for planning dimension | 1–3 |
| CI-D14 | Partial | `client_communications` as records | Unstructured communication notes as approved RAG context | 1, 5 |
| CI-D15 | Partial | Governance escalations / knowledge | Escalation notes in client-safe pack | 1–3 |

*Note: “Partial” here means upstream data exists; CI consumption adapters are Missing.*

### 4.3 Outputs — CI-O01–CI-O10

| ID | Status | Existing evidence | Exact missing behavior | Phase |
|---|---|---|---|---:|
| CI-O01 | Missing | — | Project health summary snapshot/API with evidence | 2–4 |
| CI-O02 | Partial | `ClientCommunication` executive_summary type | Full executive content contract + evidence versioning | 4 |
| CI-O03 | Partial | Delivery score rows | CI confidence narrative + explanation evidence | 2–4 |
| CI-O04 | Missing | — | Versioned readiness assessment + dimensions | 3–4 |
| CI-O05 | Missing | — | Risk narrative insight/report component | 2–4 |
| CI-O06 | Missing | — | Go-live readiness report with limitations | 4 |
| CI-O07 | Partial | Weekly communication lifecycle | Full weekly content + scheduling + stale protection | 4–6 |
| CI-O08 | Partial | Upstream mitigations/actions | Client-safe mitigation plan summary | 2–4 |
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
| CI-G06 | Partial | Send requires approval | Stale approval block; scheduled job must not approve/send | 4–6 |
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
| `client_intelligence_snapshots` | No equivalent | **Yes** | RLS on org/project; indexes on `(org_id, project_id, reporting_period_*)`; append-only / version fingerprint; evidence links |
| `client_readiness_assessments` | No (knowledge retrieval readiness ≠ this) | **Yes** | RLS; version/rules version; supersession pointer; audit |
| `client_readiness_dimensions` | No | **Yes** | FK to assessment; dimension key uniqueness; evidence completeness |
| `client_intelligence_insights` | No | **Yes** | Typed insights; confidence; status; prompt/model/rules version |
| `client_intelligence_recommendations` | Delivery mitigations insufficient | **Yes** (or extend platform recs **only if** client visibility + readiness linkage preserved) | Priority, type, visibility, evidence, status |
| `client_intelligence_evidence_links` | Comms/query evidence links are narrower | **Yes** (or generalized polymorphic evidence table) | Target type/id; visibility classification; claim key; source fingerprint; same-org/project constraint |

**Do not create migrations in this task.** Phase 1 migration review must resolve CI-DQ08 before locking readiness schema.

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
| `test_client_intelligence_evidence.py` | Missing |
| `test_client_intelligence_health.py` | Missing |
| `test_client_intelligence_confidence.py` | Missing |
| `test_client_intelligence_risk.py` | Missing |
| `test_client_intelligence_changes.py` | Missing |
| `test_client_intelligence_readiness.py` | Missing |
| `test_client_intelligence_recommendations.py` | Missing |
| `test_client_intelligence_narratives.py` | Missing |
| `test_client_intelligence_query.py` | Missing |
| `test_client_intelligence_communications.py` | Missing (lifecycle partially covered only via quality_comms) |
| `test_client_intelligence_rbac.py` | Missing |
| `test_client_intelligence_acceptance.py` | Missing |
| Phase 0 contract fixtures | Missing |
| Scheduler/idempotency/stale-draft tests | Missing |
| Frontend API/UI integration / a11y / no-mock gates | Missing |
| AI evaluation set (§12.3 / §18.5) | Missing |

Dedicated communications route tests and CSAT read tests are also absent.

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
| CI-DQ07 | Project-health formula and thresholds | Needed to shape snapshot fields even if engines land in Phase 2 |
| CI-DQ08 | Readiness dimensions, weights, blockers, approval owner | Roadmap: **before Phase 1 migration** |

### 9.2 Decisions that can wait until later phases

| ID | Decision | Earliest needed |
|---|---|---|
| CI-DQ09 | How business impact may be quantified | Before Phase 2 |
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
3. Schema migration review for Section 14 CI entities + evidence-link visibility/fingerprint fields (after CI-DQ08).
4. Implement source adapters for CI-D01–CI-D15 (explicit `unavailable` where blocked) + RBAC retrieval matrix tests.
5. Persist evidence links for future insights/readiness/recommendations; claim-to-evidence validator contract.
6. Project Health Engine (deterministic) + history comparison.
7. Delivery Confidence Intelligence (consume Delivery scores; explain only).
8. Risk Transparency + business-impact mapping (after CI-DQ09).
9. Delivery Trend Engine (actual/plan/forecast; mark missing plan).
10. Change Intelligence + Milestone Intelligence + Today’s Insight fact models.
11. Readiness scoring engine (five dimensions + cross-cutting factors) + versioned assessments.
12. Gap analysis + Recommendation/Guidance Engine (five recommendation types).
13. Harden communications lifecycle (reject reason, stale approval, report types, richer draft context).
14. Narrative generation with structured schema, claim validation, redaction, deterministic fallback.
15. Internal dashboard API + replace `/client-intelligence` mocks (navigator-only list).
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
