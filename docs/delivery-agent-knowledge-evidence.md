# Delivery Performance Agent — Knowledge Evidence Integration

**Status:** Implemented in Phase 15.5  
**Scope:** Delivery retrieves unstructured project evidence from the Operational Knowledge library by **reusing** the existing Knowledge Agent hybrid RAG pipeline. No second embed/index/retrieve stack.

## Purpose

Ground Delivery briefing, chat, and PM context in approved project documents:

- PM notes  
- Project charters  
- Delivery SOPs  
- Escalation history  
- Retrospectives  
- Risk logs  
- Meeting notes  

## Architecture

```text
Delivery signals (risks, bottlenecks, root causes, milestones)
  → query shaping (delivery_knowledge_evidence_service)
  → Knowledge _retrieve_knowledge_context (existing hybrid RAG)
  → _build_context_chunks_from_matches (citations)
  → briefing / chat / API (fail-open)
```

Reuse (do **not** duplicate):

- `app.services.knowledge.retrieval._retrieve_knowledge_context`
- Embedding cache / ranking / visibility RBAC
- Knowledge ingestion, approval, and indexing jobs

Contrast with Governance Phase 14, which **publishes** charters into Knowledge. Phase 15.5 only **reads**.

## Source-type mapping

Knowledge `source_type` enum is reused. Labels that are not first-class enums map as:

| Delivery source | Knowledge `source_type` |
|---|---|
| Delivery SOPs | `sop` |
| Project charters | `project_charter` |
| Escalation history / risk logs | `escalation_note` |
| Retrospectives | `lesson_learned` |
| PM notes / meeting notes | `guide` |
| Training material | `training_document` |

Documents must be approved, indexed, and retrieval-ready. Project scope uses `knowledge_documents.project` matched to the Delivery project **name**.

## APIs

| Method | Path | Roles |
|---|---|---|
| GET | `/delivery/projects/{id}/knowledge-evidence` | DM, leadership, super_admin |

Also attached on:

- Operational briefing payload as `knowledge_evidence` (internal only)
- Delivery chat evidence catalog as `type=knowledge` (linked to `knowledge_documents`)

Clients are excluded.

## Config

| Setting | Default | Role |
|---|---|---|
| `DELIVERY_KNOWLEDGE_EVIDENCE_ENABLED` | `true` | Feature flag (fail-open when false) |
| `DELIVERY_KNOWLEDGE_EVIDENCE_MAX_SOURCES` | `5` | Citation cap |

## Frontend

Daily Operational Briefing panel shows a **Knowledge evidence** section with title, source type, excerpt, and deep link to `/knowledge?documentId=…`.

## Grounding rules

- AI may cite retrieved excerpts only; it must not invent SOP steps or charter clauses.
- Root-cause factors and PM action ranking remain deterministic.
- Retrieval failures return empty citations and never break Delivery endpoints.

## Deferred

- 15.6 Full Delivery dashboard redesign  
- Dedicated Knowledge source_type values for meeting notes / PM notes (optional enum expansion)  
- Automatic publish of Delivery risk logs / retros into Knowledge (write path)
