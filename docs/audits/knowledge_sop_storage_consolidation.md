# Knowledge SOP Storage Consolidation Audit

Date: 2026-07-10

## Current Findings

- Governed knowledge content lives in `knowledge_documents`, `knowledge_document_versions`, `knowledge_document_chunks`, and related extraction/indexing tables.
- Legacy SOP-oriented storage still exists through `SopDocument`/SOP-specific integrations and should be treated as compatibility storage until every caller is migrated.
- Retrieval, citations, lifecycle approval, freshness, and client-safe filtering should use the governed knowledge tables as the source of truth.
- No destructive migration was performed in Phase 10.

## Phase 10 status (governance)

Done in Phase 10:

- Formal lifecycle endpoints: submit → approve/reject → return-to-draft / archive / restore
- Approval event audit trail (`knowledge_document_approval_events`)
- Status bypass closed: uploads start as draft only; PATCH cannot set governance status
- Approval-history UI + leadership-gated Approve/Reject
- `restricted` visibility treated as leadership/super-admin only (same access set as `leadership_only` for now)

## Consolidation Direction

- Keep `knowledge_documents` as the canonical store for approved SOP, guide, training, charter, escalation, and lesson-learned documents.
- Preserve legacy SOP rows for historical screens or imports until a verified mapping exists for owner, effective date, version, visibility, and approval state.
- Future migration should run as an additive backfill first, compare counts/checksums/citations, then only retire legacy writes after parity tests pass.

## Phase A next (deferred)

1. Inventory quality SOP callers (`sop_documents`, `sop_version_history`, `QualitySopLink`, `POST /projects/{id}/sop-versions`).
2. Additive backfill from legacy SOP rows into `knowledge_documents` with parity checks.
3. Stop new writes to legacy SOP tables after parity.
4. Only then consider dropping legacy tables (not in Phase 10).

## Guardrails

- Client-safe retrieval must filter by `visibility = client_safe` before prompts or final answers are built.
- Restricted SOP content must remain inaccessible to client and delivery-manager client-facing flows.
- Archived, draft, rejected, submitted, expired, and needs-reindex documents must not be retrieval-ready.
