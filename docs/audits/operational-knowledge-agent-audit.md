# Operational Knowledge Agent - Detailed Audit

> **Audit date:** 14-07-2026  
> **Scope:** Full repository audit of the Operational Knowledge Agent (OKA), including backend services, API routes, database migrations, frontend surface, cross-agent integrations, tests, and known gaps.  
> **Canonical identifiers:** `operational_knowledge_agent` in `agent_queries`, `/knowledge/*` in the API and UI.  
> **Important naming note:** There is no agent named `knowle` or `knowledge_agent` in the database contract. The product name is **Operational Knowledge Agent** and the common shorthand is **OKA**.

---

## 1. Executive Summary

The Operational Knowledge Agent is no longer only a future Phase 2 concept. In the current repository it is a substantially implemented, live knowledge-management and RAG assistant inside Operations Tower.

It provides:

- Governed document library management.
- Upload, extraction, chunking, embedding, indexing, and re-indexing.
- Approval workflow for knowledge documents.
- Hybrid vector and keyword retrieval.
- Non-streaming and streaming Q&A.
- Evidence links and query audit persistence.
- Feedback capture.
- Conversation history.
- Retrieval settings.
- Library health, document summaries, and related-knowledge helpers.
- Cross-agent hooks for Quality, Governance, and Workforce workflows.

The implementation is strongest in backend service logic and API contract coverage. The main remaining risks are frontend test coverage, true end-to-end ingestion coverage, phase-gating ambiguity, stale schema/API artifacts from removed continuous-learning features, and continued coexistence of old and new knowledge storage concepts.

| Dimension | Current assessment |
|---|---|
| Product status | Implemented and visible in the app at `/knowledge` |
| Spec status | Original spec says Phase 2+ and hidden from MVP UI |
| Main backend package | `backend/app/services/knowledge/` |
| Main API router | `backend/app/api/routes/knowledge.py` |
| Main frontend route | `frontend/src/routes/knowledge.tsx` |
| Agent audit table | `agent_queries` with `agent_name='operational_knowledge_agent'` |
| Evidence table | `knowledge_evidence_links` |
| Vector store | PostgreSQL with pgvector on `knowledge_document_chunks.embedding` |
| Embedding model | OpenAI `text-embedding-3-small` by default |
| Answer model | OpenAI model from settings, defaulting in code paths to `gpt-4o-mini` |
| Streaming | Implemented through `/knowledge/ask/stream` SSE |
| Client access | Backend has client-safe answer mode, but `/knowledge` routes exclude `CLIENT` role |
| Biggest gap | High-value frontend and ingestion E2E tests are still missing |

---

## 2. Product Identity and Scope

### 2.1 What OKA owns

The Operational Knowledge Agent owns operational process knowledge. It should answer questions such as:

- Which SOP applies to this project, issue, or operational scenario?
- What process should the team follow?
- What did we learn from similar historical issues?
- Which approved guide or escalation process supports this decision?
- What is the safest next step based on approved knowledge sources?

Its source material includes:

- SOPs.
- Guides.
- Training documents.
- Project charters.
- Escalation notes.
- Lessons learned.
- Historical issue records represented today mainly through knowledge documents and `knowledge_lessons`.

### 2.2 What OKA does not own

OKA should not become the owner for every operational question. It supports other agents by supplying governed knowledge and historical context.

| Domain | Primary owner | OKA role |
|---|---|---|
| Quality drift, root cause, reviewer consistency | Quality Intelligence Agent | Retrieve SOPs, lessons, corrective-action guidance |
| Milestone risk, throughput, delivery confidence | Delivery Performance Agent | Retrieve escalation paths and historical mitigation patterns |
| Client-ready status narratives | Client Interaction Agent | Supply approved client-safe guidance only when allowed |
| Skills, utilization, training gaps | Workforce and Capability Agent | Redirect SOP/policy questions to OKA |
| Project charters, scope, dependencies, governance | Project Governance Agent | Publish approved charters into knowledge and cite approved docs |

### 2.3 Phase mismatch

The original agent documentation in `docs/AI Agents/06. Operational Knowledge Agent.md` says OKA is Phase 2+ and must not appear in the MVP UI unless disabled as a future placeholder.

The implementation is different:

- The `/knowledge` route exists.
- The Operations Tower shell exposes **Knowledge Agent** navigation.
- Backend routes are registered and protected by role checks.
- Tests treat the API as an implemented contract.

This is not a code defect by itself, but it is a product governance mismatch. The team should either update the product docs to say OKA is now in scope or put the nav/API behind an explicit feature flag for MVP environments.

---

## 3. Implementation Map

### 3.1 Backend API

Primary file:

- `backend/app/api/routes/knowledge.py`

The router owns these groups:

- Bootstrap and health:
  - `GET /knowledge/bootstrap`
  - `GET /knowledge/library-health`
  - `GET /knowledge/health-score`
- Folders:
  - `GET /knowledge/folders`
  - `POST /knowledge/folders`
- Documents:
  - `GET /knowledge/documents`
  - `GET /knowledge/documents/{document_id}`
  - `GET /knowledge/documents/{document_id}/download`
  - `POST /knowledge/documents`
  - `PATCH /knowledge/documents/{document_id}`
  - `DELETE /knowledge/documents/{document_id}`
- Ingestion and indexing:
  - `POST /knowledge/documents/{document_id}/index`
  - `POST /knowledge/documents/{document_id}/reindex`
  - `GET /knowledge/documents/{document_id}/progress`
- Governance workflow:
  - `GET /knowledge/documents/{document_id}/approval-history`
  - `POST /knowledge/documents/{document_id}/submit`
  - `POST /knowledge/documents/{document_id}/approve`
  - `POST /knowledge/documents/{document_id}/reject`
  - `POST /knowledge/documents/{document_id}/return-to-draft`
  - `POST /knowledge/documents/{document_id}/archive`
  - `POST /knowledge/documents/{document_id}/restore`
- Q&A:
  - `POST /knowledge/ask`
  - `POST /knowledge/ask/stream`
  - `GET /knowledge/queries/{query_id}`
  - `GET /knowledge/conversations`
  - `GET /knowledge/conversations/{conversation_id}`
- Feedback:
  - `POST /knowledge/feedback`
- Versions:
  - `GET /knowledge/documents/{document_id}/versions`
  - `GET /knowledge/documents/{document_id}/versions/compare`
- Settings:
  - `GET /knowledge/retrieval-settings`
  - `PATCH /knowledge/retrieval-settings`
- AI helpers retained after continuous-learning cleanup:
  - `POST /knowledge/documents/{document_id}/summary`
  - `GET /knowledge/documents/{document_id}/related`

### 3.2 Backend service package

Primary package:

- `backend/app/services/knowledge/`

Current modules and responsibilities:

| Module | Responsibility |
|---|---|
| `__init__.py` | Public compatibility re-exports for routes, jobs, governance, and tests |
| `utils.py` | Constants, caches, normalization, prompt diagnostics, retrieval result data structures |
| `permissions.py` | Visibility checks and role-to-visibility mapping |
| `settings.py` | Org-level retrieval setting read/update |
| `ranking.py` | Hybrid reranking, boosts, version preference, diversification |
| `grounding.py` | Citation/source labels, grounding validation, confidence scoring, client-safe validation |
| `ingestion.py` | Storage, extraction, chunking, embedding, indexing, quality diagnostics |
| `retrieval.py` | Query classification, query rewrite, vector/keyword retrieval, structured operational context |
| `qa.py` | Non-streaming ask flow, conversation handling, persistence, evidence links |
| `streaming.py` | Prepared ask state and SSE lifecycle for streaming |
| `library.py` | Folder/document CRUD, approval lifecycle, bootstrap, health counts, version compare, downloads |
| `gaps.py` | Empty-answer persistence and knowledge gap related workflow remnants |
| `feedback.py` | Feedback create/update and query validation |
| `analytics.py` | Retrieval readiness and library health helpers |
| `learning.py` | Retained helpers: health score, document AI summary payloads, related knowledge |
| `evaluation.py` | Static golden evaluation helpers |

### 3.3 Thin agent package

The package `backend/app/agents/knowledge/` is not the main OKA implementation. It contains cross-agent utilities:

| File | Purpose |
|---|---|
| `retrieval.py` | Simple keyword search over `knowledge_lessons` |
| `lesson_log.py` | Writes `KnowledgeLesson` and `QualityLessonLink` when a quality alert is resolved |
| `__init__.py` | Re-exports the two helpers above |

This distinction matters: the product-grade RAG implementation is in `services/knowledge/`, while `agents/knowledge/` exists so other agents can import lightweight OKA helpers.

### 3.4 Frontend

Primary route:

- `frontend/src/routes/knowledge.tsx`

Supporting files:

| File | Purpose |
|---|---|
| `frontend/src/lib/api.ts` | Raw API client functions for knowledge endpoints |
| `frontend/src/lib/queries/knowledge.ts` | TanStack Query hooks |
| `frontend/src/lib/queries/knowledge-prefetch.ts` | Route prefetch support |
| `frontend/src/lib/knowledge-mappers.ts` | API-to-UI mapping and readiness helpers |
| `frontend/src/types/knowledge.ts` | Knowledge API and UI types |
| `frontend/src/components/knowledge/*` | Reusable knowledge UI, document tabs, history popover, streaming text |
| `frontend/src/components/bsg/Shell.tsx` | Navigation entry for Knowledge Agent |

The frontend is feature-rich, but very large. The main route is a broad page that combines library management, chat, document details, workflow actions, settings, summaries, related knowledge, upload, and health views.

---

## 4. Data Model

### 4.1 Core knowledge tables

| Table | Purpose |
|---|---|
| `knowledge_folders` | Per-organisation folders such as SOPs, Guides, Histories, and custom folders |
| `knowledge_documents` | Document metadata, visibility, workflow status, processing status, active version, summaries |
| `knowledge_document_versions` | Versioned uploads for each knowledge document |
| `knowledge_document_extractions` | Extraction results, diagnostics, quality score, chunk intelligence |
| `knowledge_document_chunks` | Chunk text and pgvector embeddings used for retrieval |
| `knowledge_document_embeddings` | Legacy/alternate JSONB embedding table; still present |
| `knowledge_evidence_links` | Links an `agent_queries` answer to cited documents/chunks |
| `knowledge_query_feedback` | User feedback for OKA answers |
| `knowledge_retrieval_settings` | Org-level retrieval defaults and tuning controls |
| `knowledge_ingestion_jobs` | DB-backed ingestion queue state and progress |
| `knowledge_document_approval_events` | Audit trail for submit/approve/reject/archive/restore lifecycle |
| `knowledge_lessons` | Structured lessons, mainly from quality alert resolution |
| `quality_lesson_links` | Links resolved quality alerts to created lessons |
| `knowledge_suggestions` | Migration-created table from Phase 11; service surface has been mostly removed |

### 4.2 Shared platform tables

| Table | OKA usage |
|---|---|
| `agent_queries` | Stores every OKA ask turn, answer text, latency, model, retrieval params, and conversation id |
| `users` | Created/submitted/reviewed/approved display names and RBAC checks |
| `organisations` | Tenant boundary |
| `projects`, `milestones`, `risk_alerts`, `bottlenecks`, `throughput_snapshots`, `quality_snapshots` | Structured operational context when a question needs project context |
| `notifications` | Knowledge workflow notifications to owners/managers/reviewers |

### 4.3 Important enums

| Enum | Values used by OKA |
|---|---|
| Folder kind | `sops`, `guides`, `histories`, `custom` |
| Source type | `sop`, `guide`, `training_document`, `project_charter`, `escalation_note`, `lesson_learned` |
| Visibility | `internal_only`, `leadership_only` or `restricted`, `client_safe` depending on migration/model naming |
| Document status | `draft`, `submitted_for_review`, `approved`, `rejected`, `expired`, `needs_reindex`, `archived` |
| Processing status | `uploaded`, `extracting`, `extracted`, `chunking`, `chunked`, `embedding`, `ready`, `failed` |
| Indexing status | `not_indexed`, `indexing`, `indexed`, `failed` |
| Feedback rating | `up`, `down` |
| Ingestion job status | `pending`, `running`, `succeeded`, `failed`, retry-oriented states in the model |

### 4.4 Retrieval eligibility

A document is eligible for production retrieval when all of the following are true:

1. It belongs to the current user's organisation.
2. It is not soft-deleted.
3. It is approved.
4. It is indexed.
5. Its processing status is ready.
6. It has owner/approver metadata.
7. It has an effective date.
8. Its visibility is allowed for the user's role.
9. If client-safe mode is requested, its visibility is `client_safe`.
10. Optional project, department, folder, source type, and effective-date filters pass.
11. It is the latest valid approved version when competing versions exist.

This is a strong governance posture. The agent is deliberately biased toward refusing or returning a low-confidence empty answer rather than relying on unapproved or weakly indexed content.

---

## 5. Ingestion Pipeline

### 5.1 Upload path

The upload route accepts PDF, DOCX, TXT, MD, and CSV files. It requires:

- File content.
- Title.
- Folder or folder kind.
- Source type.
- Version.
- Visibility.
- Owner/approver.
- Optional approver, project, department, description, and effective date.

After upload:

1. `create_document_from_upload` stores metadata and the file.
2. A document row and active version are created.
3. A `knowledge_ingestion_jobs` row is enqueued.
4. The route returns HTTP 202 with the document and job id.
5. `dispatch_knowledge_ingestion_job` starts processing.

### 5.2 Processing path

The processing job performs:

1. File read from Supabase Storage or local fallback.
2. Text extraction:
   - PDF extraction.
   - DOCX paragraph extraction.
   - TXT/MD direct text extraction.
   - CSV row conversion.
3. Quality diagnostics:
   - Extraction quality score.
   - Warnings for low text density.
   - OCR-needed signal.
   - Duplicate warnings.
   - Chunk intelligence.
4. Chunking:
   - Semantic/section-aware chunking when available.
   - Target size and overlap constants from `utils.py`.
5. Embedding:
   - Batched calls to OpenAI embedding model.
   - Per-text max character trimming.
6. Database write:
   - Chunks and embeddings.
   - Extraction diagnostics.
   - Processing/indexing status transitions.
7. Cache invalidation.

### 5.3 Storage

OKA can use:

- Supabase Storage bucket from settings.
- Local fallback under `backend/data/knowledge/{org_id}/{document_id}/`.

The repo contains at least one local knowledge PDF under `backend/data/knowledge/...`, which confirms the fallback path is used in development.

### 5.4 Re-indexing

Re-indexing uses:

- `POST /knowledge/documents/{document_id}/index`
- `POST /knowledge/documents/{document_id}/reindex`

Both require explicit user action through the dependency used by `ExplicitUserActionDep`. Re-indexing returns HTTP 202 and creates an ingestion job. This prevents accidental expensive reprocessing from passive UI fetches.

---

## 6. Retrieval and RAG Pipeline

### 6.1 High-level flow

The non-streaming ask path in `qa.py` does the following:

1. Validate or resolve conversation id.
2. Normalize conversation history.
3. Clamp retrieval settings such as max sources, candidates, and relevance threshold.
4. Retrieve context through `_retrieve_knowledge_context`.
5. Persist an empty answer if there are no accessible/filtered/relevant sources.
6. Build prompt context chunks.
7. Optionally add structured project context.
8. Call `LLMClient.generate_rag_answer`.
9. Validate grounding.
10. Validate client-safe output when requested.
11. Compute confidence.
12. Persist `AgentQuery`.
13. Persist `KnowledgeEvidenceLink` rows for selected chunks.
14. Return `KnowledgeAskRead`.

### 6.2 Query classification

`classify_knowledge_query` assigns retrieval intent:

- `factual`
- `procedural`
- `broad_summary`
- `troubleshooting`
- `historical`
- `comparative`
- `project_specific`
- `policy_or_compliance`

The classifier is deterministic and controls source count, ranking behavior, diversification, and neighbor expansion.

### 6.3 Query rewriting

Follow-up query rewriting is guarded by explicit diagnostics:

- First-turn questions skip rewrite.
- Pronoun-heavy follow-ups can be rewritten.
- Very short ambiguous follow-ups can be rewritten.
- Self-contained questions use a fast path.
- Conversation history is neutralized before any LLM rewrite prompt.

If no OpenAI key is configured or the rewrite fails, the system falls back to deterministic concatenation or the original question.

### 6.4 Hybrid retrieval

Retrieval combines:

- Vector search over `knowledge_document_chunks.embedding`.
- Keyword/term ranking.
- Exact-term and phrase boosts.
- Metadata boosts.
- Recency boosts.
- Source-type boosts.
- Query-type boosts.
- Entity-match boosts.
- Version preference.
- Duplicate penalties.
- Diversification by document/section/fingerprint for broader queries.
- Optional neighbor expansion for procedural and troubleshooting queries.

This is more advanced than a simple top-k vector search. The implementation is tuned for operational guidance, where a slightly lower vector match may be more useful if it is newer, approved, exact-term matched, or part of a procedure.

### 6.5 Structured operational context

For project-specific questions, OKA can include structured context from:

- `projects`
- `milestones`
- `risk_alerts`
- `bottlenecks`
- `throughput_snapshots`
- `quality_snapshots`

Client-safe mode redacts or summarizes internal details in this structured context.

### 6.6 Grounding and confidence

The answer path rejects or downgrades output when:

- The generated answer equals the no-approved-answer sentinel.
- Grounding support is too low.
- Client-safe validation fails.
- The evidence set is weak.

Confidence includes:

- Raw LLM confidence.
- Retrieval quality.
- Grounding support.
- Source readiness.
- Source diversity.
- Query type.
- Structured context presence.
- Client-safe validation.
- Fallback level penalties.

Confidence bands:

| Band | Meaning |
|---|---|
| `high` | Strong retrieval and grounding |
| `medium` | Usable answer with some limitations |
| `low` | Likely incomplete |
| `very_low` | Not reliable enough for confident action |

---

## 7. Streaming Q&A

`POST /knowledge/ask/stream` uses a two-stage design:

1. `prepare_stream_knowledge_ask` does auth-sensitive setup, retrieval, settings, cache checks, and early lifecycle events.
2. `stream_prepared_knowledge_ask` streams the LLM answer and final validation events.

The SSE lifecycle includes:

- `accepted`
- `searching_sources`
- `sources_found`
- `generating_answer`
- `answer_delta`
- `validating_grounding`
- `final`
- legacy-compatible `done`

This design avoids doing all work inside a single opaque generator and makes the early failure/empty-source path clearer.

---

## 8. Governance, RBAC, and Security

### 8.1 Route roles

Knowledge routes currently allow:

- `DELIVERY_MANAGER`
- `BSG_LEADERSHIP`
- `SUPER_ADMIN`

They do not allow:

- `CLIENT`

This is consistent with the current UI being internal-only, despite the existence of client-safe retrieval behavior.

### 8.2 Visibility rules

Role-to-document visibility is enforced in both listing and retrieval:

| Role | Internal | Leadership/restricted | Client-safe |
|---|---:|---:|---:|
| Delivery Manager | Yes | No | Yes |
| BSG Leadership | Yes | Yes | Yes |
| Super Admin | Yes | Yes | Yes |
| Client | No UI/API route today | No | Conceptually yes if route is added later |

### 8.3 Approval workflow

Phase 10 added a proper lifecycle:

1. Draft.
2. Submitted for review.
3. Approved or rejected.
4. Returned to draft when needed.
5. Marked needs re-index when approved content metadata changes.
6. Archived/restored.

Review actions create `knowledge_document_approval_events`. Approval is limited to leadership and super admin roles. Tests also cover separation-of-duties behavior when configured.

### 8.4 Prompt and injection hardening

The implementation includes:

- Neutralization of rewrite-context prompt injection.
- Prompt security tests.
- Structured source blocks rather than raw unlabelled context.
- Client-safe validation for restricted answer mode.
- Refusal behavior when approved sources are absent.
- No model-memory-only process guidance in intended behavior.

### 8.5 Auditability

Each successful answer writes:

- `agent_queries` row.
- `retrieval_params` JSON containing diagnostics, sources, citations, confidence, prompt diagnostics, timing, rewrite diagnostics, and grounding information.
- `knowledge_evidence_links` rows for cited chunks.

Empty/failed knowledge answers are also persisted through the gap/empty-response path so the unanswered demand is visible.

---

## 9. API Behavior Details

### 9.1 Dedicated API instead of generic agent router

The original docs describe `POST /agent-queries` as a possible future endpoint. The implementation does not route OKA through that generic endpoint.

Actual behavior:

- Ask: `POST /knowledge/ask`
- Stream: `POST /knowledge/ask/stream`
- History: `GET /knowledge/queries/{query_id}` and `GET /knowledge/conversations/*`
- Evidence: persisted through `knowledge_evidence_links`

This API divergence should be explicitly documented in the agent spec, because `operational_knowledge_agent` may appear supported in shared agent documentation while the actual ask path is knowledge-specific.

### 9.2 Explicit user action requirements

Expensive or user-intent-sensitive operations require explicit action:

- Re-indexing requires `ExplicitUserActionDep`.
- AI document ranking requires `X-BSG-User-Action: true`.
- Ask endpoints also require explicit user action in the route signature.

### 9.3 Settings

Retrieval settings can control:

- `include_histories`
- `max_sources`
- `max_candidates`
- `min_relevance`
- `min_confidence`
- Project/department defaults.
- Folder/source-type scopes.
- Recency and exact-term preferences.
- Approved-only behavior, which production routes force to true.

Only leadership and super admin can patch retrieval settings.

---

## 10. Frontend Assessment

### 10.1 Main capabilities

The `/knowledge` page supports:

- Knowledge library overview.
- Folder tree.
- Document filtering and sorting.
- Upload.
- Document details and chunks.
- Retrieval readiness state.
- Approval workflow actions.
- Version history and comparison.
- Ask panel.
- Streaming answers.
- Conversation history.
- Feedback.
- Retrieval settings.
- Health metrics.
- AI document summary generation.
- Related knowledge display.

### 10.2 Strengths

- The page exposes most backend capabilities.
- It includes readiness labels, health states, and workflow states.
- It maps API document states into user-facing labels.
- It has streaming UI support through `TypewriterText` and loading indicators.
- It uses TanStack Query caching and invalidation.

### 10.3 Risks

- The route is large and carries many responsibilities.
- There are no dedicated frontend tests for the knowledge route.
- Some type/schema remnants still reference broader continuous-learning capabilities that no longer have full API support.
- The live nav item conflicts with original MVP/Phase 2 gating.

---

## 11. Cross-Agent Integrations

### 11.1 Quality Intelligence

Quality integration exists in two directions:

- Read path: Quality can use `keyword_search` over `knowledge_lessons`.
- Write path: resolving a quality alert can create a `KnowledgeLesson` and `QualityLessonLink`.

Relevant files:

- `backend/app/agents/knowledge/retrieval.py`
- `backend/app/agents/knowledge/lesson_log.py`
- `backend/app/services/quality.py`
- `backend/app/agents/quality_intelligence/oka_client.py`
- `backend/app/agents/quality_intelligence/query_handler.py`
- `backend/app/agents/quality_intelligence/what_if.py`

The external `OKAClient` remains optional. If `OKA_BASE_URL` is unset, it no-ops or falls back to in-process/database paths.

### 11.2 Governance

Governance uses knowledge in several ways:

- Approved governance-related knowledge docs can be listed.
- Charter generation can cite knowledge documents.
- Governance Q&A can include knowledge evidence.
- Phase 14 can publish approved project charters into OKA as versioned knowledge documents when enabled.

Relevant files:

- `backend/app/agents/governance/services/knowledge_link_service.py`
- `backend/app/agents/governance/services/charter_service.py`
- `backend/app/agents/governance/services/governance_charter_publish_service.py`
- `backend/app/agents/governance/query_handler.py`
- `supabase/migrations/20260713190000_governance_charter_knowledge_phase14.sql`

### 11.3 Workforce

The Workforce Agent classifies SOP/document/policy-style questions and redirects them to OKA rather than answering from workforce logic.

Relevant file:

- `backend/app/services/workforce_agent.py`

This is a good ownership boundary.

---

## 12. Configuration and Runtime Dependencies

Important settings and constants include:

| Setting/constant | Purpose |
|---|---|
| `OPENAI_API_KEY` or equivalent LLM key | Required for live embeddings/answers/rewrite |
| `openai_model` / `llm_model` | Answer/rewrite model selection |
| `text-embedding-3-small` | Default embedding model by code/config convention |
| `knowledge_storage_bucket` | Supabase Storage bucket |
| `knowledge_upload_dir` | Local fallback storage |
| `oka_base_url` | Optional external OKA HTTP service |
| `knowledge_separation_of_duties` | Optional approval governance guard |
| `governance_charter_knowledge_publish_enabled` | Enables charter publication to knowledge |

Operationally, the system also depends on:

- PostgreSQL.
- pgvector extension and indexes.
- Supabase-style RLS context.
- APScheduler or the app's background job poller for ingestion jobs.
- OpenAI-compatible client availability for live embedding and LLM paths.

---

## 13. Migration Timeline

Important OKA migrations:

| Migration | Purpose |
|---|---|
| `20260623110000_knowledge_agent_schema.sql` | Initial knowledge schema |
| `20260623120000_knowledge_upload_processing.sql` | Upload processing status |
| `20260624100000_knowledge_ingestion_pipeline.sql` | Ingestion pipeline support |
| `20260624120000_knowledge_retrieval_settings.sql` | Org retrieval settings |
| `20260624130000_knowledge_custom_folders.sql` | Custom folders |
| `20260625120000_knowledge_lessons.sql` | Lessons learned |
| `20260626100000_knowledge_query_feedback.sql` | Query feedback |
| `20260626110000_knowledge_eval_observability.sql` | Older eval observability, later removed |
| `20260701100000_knowledge_agent_performance_indexes.sql` | Performance indexes |
| `20260701120000_drop_knowledge_eval.sql` | Drops older eval feature |
| `20260702120000_knowledge_extraction_metadata.sql` | Extraction metadata |
| `20260702140000_knowledge_conversations.sql` | Conversation grouping |
| `20260710110000_knowledge_retrieval_phase4_settings.sql` | Retrieval tuning settings |
| `20260710120000_knowledge_feedback_phase5.sql` | Feedback diagnostics |
| `20260710130000_knowledge_ingestion_jobs.sql` | DB-backed ingestion jobs |
| `20260710140000_drop_knowledge_gaps.sql` | Removes older knowledge gaps table/type |
| `20260710150000_knowledge_governance_phase10_enums.sql` | Adds workflow statuses |
| `20260710151000_knowledge_governance_phase10.sql` | Approval lifecycle columns/events |
| `20260710160000_knowledge_learning_phase11.sql` | Summaries, related docs, and suggestions table |
| `20260713190000_governance_charter_knowledge_phase14.sql` | Governance charter publication to OKA |

Phase 11 deserves special note: the migration still creates `knowledge_suggestions`, and schemas still contain several suggestion/evaluation shapes, but the current service and route surface mostly retains only health score, AI summaries, related knowledge, and static evaluation helpers.

---

## 14. Test Coverage

### 14.1 Strong coverage areas

Knowledge-specific tests cover:

- Retrieval query classification.
- Query rewrite fast path and LLM rewrite behavior.
- Ranking and recency behavior.
- Grounding and client-safe validation.
- Prompt security.
- Conversation history normalization.
- Bootstrap payload shape and recent-document limit.
- Feedback create/update/reject behavior.
- API contracts for document list/detail, ask, stream, feedback, settings, and error shaping.
- Governance workflow transitions and approval events.
- Upload status restrictions.
- Separation-of-duties behavior.
- Ingestion job helpers.
- Learning helpers retained after continuous-learning cleanup.
- Static golden evaluation helpers.

Representative files:

- `backend/tests/test_knowledge_retrieval.py`
- `backend/tests/test_knowledge_api_contract.py`
- `backend/tests/test_knowledge_feedback.py`
- `backend/tests/test_knowledge_workflow_phase6.py`
- `backend/tests/test_knowledge_ingestion_jobs.py`
- `backend/tests/test_knowledge_governance_phase10.py`
- `backend/tests/test_knowledge_learning_phase11.py`
- `backend/tests/test_knowledge_prompt_security.py`
- `backend/tests/test_knowledge_chunking.py`
- `backend/tests/test_knowledge_bootstrap.py`

### 14.2 Cross-agent tests

Relevant cross-agent coverage includes:

- Quality lesson write-back.
- Optional OKA client behavior.
- Workforce SOP redirect classification.
- Governance charter evidence.
- Governance charter publication to knowledge.

Representative files:

- `backend/tests/test_lesson_writeback.py`
- `backend/tests/test_oka_client.py`
- `backend/tests/test_workforce_agent.py`
- `backend/tests/test_governance_charter.py`
- `backend/tests/test_governance_charter_knowledge_phase14.py`

### 14.3 Coverage gaps

| Gap | Why it matters |
|---|---|
| No full ingestion E2E test with a real file through upload, job, chunks, embeddings, and retrieval | This is the highest-risk operational path |
| No browser/UI tests for `/knowledge` | The page is large and user-facing |
| Limited streaming validation beyond API contract mocks | SSE ordering and client behavior can regress |
| No production-like pgvector retrieval integration test | Ranking SQL and vector extension behavior can differ from mocks |
| No accessibility/regression tests for document workflow UI | Approval actions are governance-sensitive |
| Continuous-learning remnants are not fully reconciled | Schemas/migrations/types may imply more than routes provide |

---

## 15. Spec vs Implementation

| Spec statement | Implementation reality | Assessment |
|---|---|---|
| OKA is Phase 2+ and hidden from MVP UI | OKA is live at `/knowledge` and appears in nav | Product decision mismatch |
| Q&A may use `POST /agent-queries` | Q&A uses `/knowledge/ask` and `/knowledge/ask/stream` | Needs doc update |
| Knowledge schema needed in future | Schema is implemented across many migrations | Spec is stale |
| Approved-source-only answers | Implemented and forced in ask routes | Good |
| Client users may eventually get client-safe access | Backend has client-safe mode but routes block `CLIENT` | Partial and conservative |
| Historical issue records may need dedicated table | Current implementation uses documents and `knowledge_lessons` | Partial |
| Evaluation observability | Older eval removed; static golden evaluation helper remains | Mixed/stale |
| SOP approval workflow | Implemented through Phase 10 lifecycle | Good |
| Vector/RAG decision unresolved | Resolved as PostgreSQL + pgvector | Spec is stale |

---

## 16. Detailed Risks and Technical Debt

### 16.1 High priority

| Risk | Detail | Recommended action |
|---|---|---|
| Phase gating mismatch | Product docs say hidden Phase 2+, app exposes a live Knowledge Agent | Decide whether OKA is in MVP; update docs or feature-flag nav/routes |
| Missing frontend tests | `/knowledge` is a complex workflow surface with no dedicated UI tests | Add tests for upload, ask, approval lifecycle, settings, and document details |
| Missing ingestion E2E | The most complex backend path is not tested end-to-end | Add a test using small TXT/MD fixture and mocked embeddings |
| Continuous-learning remnants | `knowledge_suggestions` and schema types remain while route/service support is mostly removed | Either restore feature routes or remove/mark as dormant |

### 16.2 Medium priority

| Risk | Detail | Recommended action |
|---|---|---|
| Legacy embedding table | `knowledge_document_embeddings` coexists with chunk embeddings | Document deprecation or migrate away |
| Large frontend route | `knowledge.tsx` has many responsibilities | Split into feature components once behavior stabilizes |
| Process-local caches | Embed and answer caches are not shared across workers | Use Redis/shared cache if deployed with multiple workers |
| External OKA client ambiguity | `OKAClient` exists but primary implementation is in-process/database | Document when `OKA_BASE_URL` should be used |
| Generic agent router divergence | `operational_knowledge_agent` may be listed in shared docs but not served by generic endpoint | Update API docs and agent docs |
| Visibility naming drift | Some docs/tests mention `leadership_only`, while newer tests use `restricted` | Normalize terminology across docs and UI |

### 16.3 Low priority

| Risk | Detail | Recommended action |
|---|---|---|
| Stale eval/suggestion frontend or schema fields | Types expose more concepts than the API currently routes | Prune or annotate |
| Duplicate SOP storage concepts | `sop_documents` can exist separately from knowledge docs | Consolidate ownership |
| Audit file drift | OKA evolves quickly across migrations | Update this audit after each major phase |

---

## 17. Recommendations

### 17.1 Immediate

1. Resolve the product decision: live MVP feature or Phase 2 feature flag.
2. Update `docs/AI Agents/06. Operational Knowledge Agent.md` so it reflects the implemented `/knowledge/*` API and current schema.
3. Add a minimal ingestion E2E test with mocked embedding output.
4. Add frontend smoke tests for `/knowledge` load, document selection, ask, and approval actions.
5. Reconcile Phase 11 remnants: either restore suggestion endpoints or mark `knowledge_suggestions` as dormant.

### 17.2 Near term

1. Split `frontend/src/routes/knowledge.tsx` into smaller workflow components.
2. Add streaming SSE ordering tests that validate final event content and evidence metadata.
3. Add a pgvector-backed integration test profile for retrieval SQL.
4. Document `OKA_BASE_URL` and when external OKA service mode is expected.
5. Decide whether clients will ever hit `/knowledge`; if yes, build a separate client-safe route and UI with strict visibility enforcement.

### 17.3 Later

1. Consolidate `sop_documents` and `knowledge_documents` or document the boundary.
2. Replace process-local answer cache with shared cache if multi-worker deployment is used.
3. Add operational telemetry dashboards for:
   - Retrieval latency.
   - Empty-answer rate.
   - Grounding rejection rate.
   - Low-confidence answers.
   - Re-index backlog.
   - Approval queue age.
4. Add a formal golden dataset runner that exercises the real retrieval stack, not only static fixture scoring.

---

## 18. Key Constants and Defaults

| Constant | Meaning |
|---|---|
| `KNOWLEDGE_AGENT_NAME` | `operational_knowledge_agent` |
| `DEFAULT_MAX_SOURCES` | Default answer citation/source count |
| `DEFAULT_MAX_CANDIDATES` | Default retrieval candidate count |
| `HYBRID_VECTOR_WEIGHT` | Vector component of hybrid rank |
| `HYBRID_KEYWORD_WEIGHT` | Keyword component of hybrid rank |
| `RERANK_CANDIDATE_LIMIT` | Minimum rerank pool |
| `LOW_CONFIDENCE_THRESHOLD` | Threshold for incomplete-answer warning |
| `FAST_PATH_THRESHOLD` | High retrieval score threshold for fast answer path |
| `CHUNK_TARGET_TOKENS` | Target chunk size |
| `CHUNK_OVERLAP_TOKENS` | Chunk overlap |
| `EMBEDDING_INPUT_MAX_CHARS` | Max embedding text length |
| `RAG_CONTEXT_CHUNK_CHARS` | Max text included per context chunk |
| `RAG_MAX_OUTPUT_TOKENS` | Answer token cap in LLM client |
| `NO_APPROVED_ANSWER` | Safe fallback when evidence is unavailable |
| `BOOTSTRAP_RECENT_DOCUMENT_LIMIT` | Recent document limit in bootstrap |

---

## 19. Current Overall Assessment

OKA is a credible, nearly production-grade internal knowledge agent. Its backend design is thoughtful: retrieval is permission-aware, evidence-backed, grounded, version-aware, and instrumented. The approval lifecycle closes an important governance gap, and the cross-agent boundaries are mostly clean.

The main issue is not that OKA is underbuilt. The main issue is that it is more built than the product documentation says. That creates rollout risk, not just documentation debt. The safest next step is to align product phase documentation, API documentation, and the visible navigation decision.

Once that decision is settled, the engineering priority should be verification depth: ingestion E2E, frontend workflow tests, and a production-like retrieval integration test. Those tests would cover the places where this agent could fail in ways that matter to users.

---

## 20. File References

Primary files:

- `docs/AI Agents/06. Operational Knowledge Agent.md`
- `backend/app/api/routes/knowledge.py`
- `backend/app/services/knowledge/`
- `backend/app/agents/knowledge/`
- `backend/app/services/knowledge_ingestion_jobs.py`
- `backend/app/services/llm/client.py`
- `backend/app/db/models/entities.py`
- `backend/app/schemas/domain.py`
- `frontend/src/routes/knowledge.tsx`
- `frontend/src/lib/api.ts`
- `frontend/src/types/knowledge.ts`
- `supabase/migrations/*knowledge*.sql`

Primary test files:

- `backend/tests/test_knowledge_api_contract.py`
- `backend/tests/test_knowledge_retrieval.py`
- `backend/tests/test_knowledge_governance_phase10.py`
- `backend/tests/test_knowledge_ingestion_jobs.py`
- `backend/tests/test_knowledge_learning_phase11.py`
- `backend/tests/test_knowledge_prompt_security.py`
- `backend/tests/test_knowledge_workflow_phase6.py`
- `backend/tests/test_lesson_writeback.py`
- `backend/tests/test_oka_client.py`
- `backend/tests/test_workforce_agent.py`
- `backend/tests/test_governance_charter_knowledge_phase14.py`

*End of audit.*
