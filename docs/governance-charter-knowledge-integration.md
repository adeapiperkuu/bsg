# Governance ↔ Knowledge Integration (Phase 14)

Additive feedback loop that publishes **approved** Project Charters into the Operational Knowledge Library as versioned, searchable documents.

Cross-links:

- Agent BRD: `docs/AI Agents/04. Project Governance.md`
- [AI Recommendations](governance-ai-recommendations.md)
- [Recommendation Optimization](governance-recommendation-optimization.md)
- Operational Knowledge Agent (library / ingestion / retrieval)

## Architecture

```
Knowledge Library ──► Charter Generation (evidence-first)
        │
        ▼
Generate Charter (draft)
        │
        ▼
Review / Edit
        │
        ▼
Approve (Governance HITL)
        │
        ▼
Publish to Knowledge ──► create/version document
        │                 enqueue existing ingestion
        │                 chunk → embed → index
        ▼
Future charter generation reuses approved Knowledge docs
```

Reuse (do **not** duplicate):

- `create_document_from_upload` / `reindex_document`
- Knowledge ingestion jobs, chunking, embeddings, ranking
- Knowledge approval events + document versions / supersede links
- Governance `log_governance_event` audit trail

## Publish workflow

1. Charter must be `approved`.
2. Service builds clean **markdown** (never raw DB JSON) with metadata + filled approval section.
3. Uploads into Knowledge as `source_type=project_charter` under Histories (same title → new version).
4. Marks Knowledge document **approved** (Governance approval is the HITL gate).
5. Enqueues the existing ingestion pipeline.
6. Links `knowledge_document_id` / `knowledge_version_id` on the charter.
7. Marks older published charters for the same project as `superseded` (never deleted).

If publication fails:

- Charter remains **approved**
- `publication_status=failed`
- Retry is allowed
- Approval is never rolled back

## Versioning & supersession

| Layer | Behavior |
|-------|----------|
| Governance charter | Each approve creates/keeps charter `vN` |
| Knowledge document | Stable title `{Project} — Project Charter` |
| Knowledge version | New version per publish; previous version superseded |
| Charter publish status | Older published charters → `superseded` |

Historical versions remain searchable; newest/active version ranks for retrieval.

## Duplicate detection

Publishing the same charter version again returns `409 ALREADY_PUBLISHED` and writes an immutable `already_published` timeline/audit event.

## Timeline & audit

Immutable tables:

- `governance_charter_publication_events`
- `governance_charter_publication_audits`

Plus governance audit events: `charter.published`, `charter.publication_failed`, `charter.republished`, etc.

Event types:

- Charter Published
- Knowledge Version Created
- Knowledge Publication Failed
- Knowledge Republished
- Knowledge Publication Retried
- Knowledge Version Superseded
- Already Published / Unpublished

## Configuration

| Env / setting | Default | Meaning |
|---------------|---------|---------|
| `GOVERNANCE_CHARTER_KNOWLEDGE_PUBLISH_ENABLED` | `true` | Master switch for publish APIs / auto-publish |
| `AUTO_PUBLISH_APPROVED_CHARTERS` | `true` | Publish immediately after successful approval |

When auto-publish is off, approval is unchanged; Leadership can publish manually.

## Permissions

| Action | Roles |
|--------|-------|
| Publish / Republish / Retry / Unpublish | Leadership, Super Admin |
| Read publication status / knowledge link / versions | Governance read roles |
| Approve charter | Delivery Manager, Super Admin (unchanged) |

Auto-publish after approval runs without requiring Leadership (system path after HITL approve).

## APIs

Follow existing `/governance/project-charters/...` conventions:

| Method | Path |
|--------|------|
| POST | `/governance/project-charters/{id}/publish` |
| POST | `/governance/project-charters/{id}/republish` |
| POST | `/governance/project-charters/{id}/retry-publication` |
| POST | `/governance/project-charters/{id}/unpublish` |
| GET | `/governance/project-charters/{id}/publication-status` |
| GET | `/governance/project-charters/{id}/knowledge` |
| GET | `/governance/project-charters/{id}/versions` |
| GET | `/governance/project-charters/{id}/publication-timeline` |

## Frontend

Project Charters panel Knowledge section shows:

- Publish status badge
- Knowledge version / published date / publisher
- View Knowledge (`/knowledge?documentId=...`)
- Publish / Retry / Republish (Leadership / Super Admin only)
- Version history

## Failure recovery

1. Approval succeeds and commits.
2. Auto or manual publish fails → `failed` + timeline event.
3. Leadership **Retry** publishes only missing versions (idempotent).
4. **Republish** reindexes an already-published version (corruption / embedding refresh).

## Charter generation retrieval

Generation now prefers:

1. Same-project approved Knowledge docs
2. Other `project_charter` documents
3. Department / vertical matches
4. Previous approved charters for the project (`previous_approved_charters` in prompt context)

Prompt remains evidence-first and cites Knowledge evidence refs.

## Migration

`supabase/migrations/20260713190000_governance_charter_knowledge_phase14.sql`

Adds publication columns on `project_charters` plus immutable event/audit tables with RLS.
