"""Operational Knowledge unstructured evidence adapter for Client Intelligence.

Projects approved, project-scoped, visibility-authorized, retrieval-ready
document metadata and chunks into ClientEvidencePack facts.

Does not import private Knowledge retrieval/ranking/prompt internals.
Does not call Q&A, ranking, semantic search, summarization, or LLM APIs.
"""

from __future__ import annotations

import hashlib
from collections import defaultdict
from dataclasses import dataclass
from datetime import UTC, date, datetime, time
from uuid import UUID

from sqlalchemy import and_, func, or_, select, tuple_
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.client_intelligence.contracts import (
    ClientEvidenceReference,
    DataQualityIssue,
    DataQualityState,
    EvidenceVisibility,
    KnowledgeChunkFacts,
    KnowledgeDocumentFacts,
    KnowledgeEvidenceFacts,
    KnowledgeSourceAvailabilityFacts,
    ReportingPeriod,
    SourceAgent,
    VisibilityLimitation,
)
from app.db.models import (
    AppRole,
    KnowledgeDocument,
    KnowledgeDocumentChunk,
    KnowledgeDocumentStatus,
    KnowledgeDocumentVersion,
    KnowledgeIndexingStatus,
    KnowledgeProcessingStatus,
    KnowledgeSourceType,
    KnowledgeVisibility,
)
from app.services.knowledge.permissions import can_access_visibility

_MAX_DOCUMENTS = 50
_MAX_VERSIONS = 50
_MAX_CHUNKS = 200
_MAX_CHUNKS_PER_DOCUMENT = 20
_MAX_CHARS_PER_CHUNK = 4_000
_MAX_TOTAL_UNTRUSTED_CHARS = 50_000

_GENERIC_DESCRIPTION = "Operational Knowledge aggregate evidence for an authorized project."

_PROJECT_LINKAGE_LIMITATION = (
    "Knowledge project linkage currently relies on exact normalized project-name "
    "text matching against KnowledgeDocument.project; UUID project scoping is not "
    "available on knowledge documents."
)

_CI_D14_LIMITATION = (
    "CLIENT_COMMUNICATION_NOTES_UNAVAILABLE: CI-D14 Client Communication Notes are "
    "unavailable because KnowledgeSourceType has no CLIENT_COMMUNICATION_NOTE value "
    "(Phase 1 blocker). LESSON_LEARNED is not treated as communication notes, and "
    "ClientCommunication records are not queried."
)

_VERSION_EXCLUSION_LIMITATION = (
    "One or more approved Knowledge documents were excluded because their referenced "
    "active version could not be validated for the reporting period."
)

_EMPTY_CHUNK_LIMITATION = (
    "One or more Knowledge chunks were excluded because normalized source text was empty."
)

_VISIBILITY_OMISSION_LIMITATION = (
    "Additional Operational Knowledge evidence was omitted by visibility policy."
)

_VISIBILITY_SOURCE_UNAVAILABLE_LIMITATION = (
    "Approved Operational Knowledge evidence exists for this source but was omitted "
    "by visibility policy."
)

_VISIBILITY_SOURCE_PARTIAL_LIMITATION = (
    "Additional Operational Knowledge evidence for this source was omitted by "
    "visibility policy."
)

_DQ_PRECEDENCE: dict[DataQualityState, int] = {
    DataQualityState.COMPLETE: 0,
    DataQualityState.PARTIAL: 1,
    DataQualityState.STALE: 2,
    DataQualityState.UNAVAILABLE: 3,
    DataQualityState.CONFLICTING: 4,
}

_SOURCE_REQUIREMENTS: tuple[tuple[str, KnowledgeSourceType | None], ...] = (
    ("CI-D11", KnowledgeSourceType.SOP),
    ("CI-D12", KnowledgeSourceType.TRAINING_DOCUMENT),
    ("CI-D13", KnowledgeSourceType.PROJECT_CHARTER),
    ("CI-D14", None),
    ("CI-D15", KnowledgeSourceType.ESCALATION_NOTE),
)

_MAPPED_SOURCE_TYPES: tuple[KnowledgeSourceType, ...] = tuple(
    source_type for _, source_type in _SOURCE_REQUIREMENTS if source_type is not None
)

_DOCUMENT_CLAIM_KEYS = [
    "source_type",
    "document_type",
    "version",
    "visibility",
    "effective_date",
    "approved_at",
    "indexed_at",
    "active_version_id",
]
_CHUNK_CLAIM_KEYS = [
    "source_type",
    "document_version",
    "chunk_index",
    "page_number",
    "content_sha256",
]


@dataclass(frozen=True, slots=True)
class _DocumentRow:
    id: UUID
    source_type: object
    document_type: str | None
    version: str
    visibility: object
    effective_date: date
    approved_at: datetime
    indexed_at: datetime
    active_version_id: UUID
    title: str
    created_at: datetime | None
    updated_at: datetime | None


@dataclass(frozen=True, slots=True)
class _VersionRow:
    id: UUID
    document_id: UUID
    version: str


@dataclass(frozen=True, slots=True)
class _ChunkRow:
    id: UUID
    document_id: UUID
    version_id: UUID
    chunk_index: int
    page_number: int | None
    section_title: str | None
    heading: str | None
    display_text: str
    content_sha256: str
    visibility: object | None
    created_at: datetime | None


@dataclass(slots=True)
class _BoundFlags:
    documents: bool = False
    versions: bool = False
    versions_incomplete: bool = False
    chunks: bool = False
    chunks_per_document: bool = False
    chars_per_chunk: bool = False
    total_chars: bool = False
    empty_chunks: bool = False

    @property
    def any_bound(self) -> bool:
        return any(
            (
                self.documents,
                self.versions,
                self.versions_incomplete,
                self.chunks,
                self.chunks_per_document,
                self.chars_per_chunk,
                self.total_chars,
                self.empty_chunks,
            )
        )


def _as_of_end_utc(as_of: date) -> datetime:
    return datetime.combine(as_of, time.max, tzinfo=UTC)


def _enum_str(value: object) -> str:
    return value.value if hasattr(value, "value") else str(value)


def _evidence_visibility(client_safe: bool) -> EvidenceVisibility:
    return EvidenceVisibility.CLIENT_SAFE if client_safe else EvidenceVisibility.INTERNAL


def _issue(source: str, state: DataQualityState, detail: str) -> DataQualityIssue:
    return DataQualityIssue(source=source, state=state, detail=detail, observed_at=None)


def _set_source_issue(
    issues_by_source: dict[str, DataQualityIssue],
    source: str,
    state: DataQualityState,
    detail: str,
) -> None:
    existing = issues_by_source.get(source)
    if existing is None or _DQ_PRECEDENCE[state] > _DQ_PRECEDENCE[existing.state]:
        issues_by_source[source] = _issue(source, state, detail)


def _finalize_issues(issues_by_source: dict[str, DataQualityIssue]) -> list[DataQualityIssue]:
    return [issues_by_source[key] for key in sorted(issues_by_source)]


def _trim_limit_plus_one(rows: list, max_rows: int) -> tuple[list, bool]:
    if len(rows) > max_rows:
        return rows[:max_rows], True
    return rows, False


def _normalize_project_name(project_name: str) -> str:
    return project_name.strip().lower()


def _project_scope_key(project_name: str) -> str:
    normalized = _normalize_project_name(project_name)
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def _content_sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _normalize_source_text(text: str | None) -> str:
    if text is None:
        return ""
    normalized = text.replace("\r\n", "\n").replace("\r", "\n")
    return normalized.strip()


def _sql_has_normalized_text(column) -> object:
    """True when column has non-whitespace content after CRLF/CR→LF and trim.

    Matches ``_normalize_source_text`` for spaces, tabs, CR, LF, and CRLF.
    """
    replaced = func.replace(
        func.replace(func.coalesce(column, ""), "\r\n", "\n"),
        "\r",
        "\n",
    )
    trimmed = func.trim(replaced, " \t\n\r")
    return func.length(trimmed) > 0


def _sql_chunk_has_source_text() -> object:
    return or_(
        _sql_has_normalized_text(KnowledgeDocumentChunk.chunk_text),
        _sql_has_normalized_text(KnowledgeDocumentChunk.content),
    )


def _select_source_text(chunk_text: str | None, content: str | None) -> str:
    primary = _normalize_source_text(chunk_text)
    if primary:
        return primary
    return _normalize_source_text(content)


def _resolve_client_safe(role: AppRole, visibility_mode: EvidenceVisibility) -> bool:
    """CLIENT role always fail-closes to CLIENT_SAFE projection semantics."""
    return role == AppRole.CLIENT or visibility_mode == EvidenceVisibility.CLIENT_SAFE


def _allowed_visibilities(
    role: AppRole,
    *,
    client_safe: bool,
) -> list[KnowledgeVisibility]:
    if client_safe:
        return [KnowledgeVisibility.CLIENT_SAFE]
    return [
        visibility for visibility in KnowledgeVisibility if can_access_visibility(role, visibility)
    ]


def _status_enum(value: object, enum_cls: type) -> object:
    if isinstance(value, enum_cls):
        return value
    return enum_cls(value)


def _document_base_filters(
    *,
    org_id: UUID,
    normalized_project: str,
    as_of: date,
    as_of_end: datetime,
):
    return (
        KnowledgeDocument.org_id == org_id,
        KnowledgeDocument.deleted_at.is_(None),
        KnowledgeDocument.status == KnowledgeDocumentStatus.APPROVED,
        KnowledgeDocument.indexing_status == KnowledgeIndexingStatus.INDEXED,
        KnowledgeDocument.processing_status == KnowledgeProcessingStatus.READY,
        KnowledgeDocument.source_type.in_(_MAPPED_SOURCE_TYPES),
        KnowledgeDocument.project.isnot(None),
        func.lower(func.trim(KnowledgeDocument.project)) == normalized_project,
        KnowledgeDocument.approved_at.isnot(None),
        KnowledgeDocument.approved_at <= as_of_end,
        KnowledgeDocument.indexed_at.isnot(None),
        KnowledgeDocument.indexed_at <= as_of_end,
        KnowledgeDocument.upload_date <= as_of_end,
        KnowledgeDocument.active_version_id.isnot(None),
        KnowledgeDocument.effective_date.isnot(None),
        KnowledgeDocument.effective_date <= as_of,
        KnowledgeDocument.owner_approver.isnot(None),
        func.length(func.trim(KnowledgeDocument.owner_approver)) > 0,
        or_(
            KnowledgeDocument.expiry_date.is_(None),
            KnowledgeDocument.expiry_date >= as_of,
        ),
        KnowledgeDocument.created_at <= as_of_end,
    )


async def load_knowledge_evidence(
    session: AsyncSession,
    project_id: UUID,
    org_id: UUID,
    project_name: str,
    reporting_period: ReportingPeriod,
    *,
    visibility_mode: EvidenceVisibility,
    role: AppRole,
) -> tuple[
    KnowledgeEvidenceFacts,
    list[ClientEvidenceReference],
    list[DataQualityIssue],
    list[VisibilityLimitation],
    list[str],
]:
    """Load bounded Operational Knowledge facts for an already-authorized project.

    ``project_id`` is retained for the authorized contract and fingerprint context.
    Document scoping uses exact normalized ``KnowledgeDocument.project`` ↔ project name.
    ``AppRole.CLIENT`` always uses CLIENT_SAFE projection semantics.
    """
    _ = project_id
    client_safe = _resolve_client_safe(role, visibility_mode)
    as_of = reporting_period.as_of
    as_of_end = _as_of_end_utc(as_of)
    scope_key = _project_scope_key(project_name)
    normalized_project = _normalize_project_name(project_name)
    allowed = _allowed_visibilities(role, client_safe=client_safe)

    evidence: list[ClientEvidenceReference] = []
    issues_by_source: dict[str, DataQualityIssue] = {}
    visibility_limitations: list[VisibilityLimitation] = []
    limitations: list[str] = [_PROJECT_LINKAGE_LIMITATION]
    bounds = _BoundFlags()

    candidates, docs_truncated = await _load_retrieval_ready_documents(
        session,
        org_id=org_id,
        normalized_project=normalized_project,
        as_of=as_of,
        as_of_end=as_of_end,
        allowed_visibilities=allowed,
    )
    bounds.documents = docs_truncated

    documents, version_flags = await _validate_active_versions(
        session,
        org_id=org_id,
        as_of_end=as_of_end,
        candidates=candidates,
    )
    bounds.versions = version_flags.versions
    bounds.versions_incomplete = version_flags.versions_incomplete
    if version_flags.versions_incomplete:
        limitations.append(_VERSION_EXCLUSION_LIMITATION)
        _set_source_issue(
            issues_by_source,
            "knowledge_versions",
            DataQualityState.PARTIAL,
            "Referenced active Knowledge document versions could not all be validated.",
        )

    chunks, chunk_flags, hidden_chunk_source_types = await _load_document_chunks(
        session,
        org_id=org_id,
        as_of_end=as_of_end,
        documents=documents,
        allowed_visibilities=allowed,
        role=role,
        client_safe=client_safe,
    )
    bounds.chunks = chunk_flags.chunks
    bounds.chunks_per_document = chunk_flags.chunks_per_document

    prepared_chunks, empty_skipped = _prepare_chunk_rows(chunks)
    bounds.empty_chunks = empty_skipped
    if empty_skipped:
        limitations.append(_EMPTY_CHUNK_LIMITATION)
        _set_source_issue(
            issues_by_source,
            "knowledge_chunks",
            DataQualityState.PARTIAL,
            "One or more Knowledge chunks had empty normalized source text.",
        )

    prepared_chunks, char_flags = _apply_character_bounds(prepared_chunks)
    bounds.chars_per_chunk = char_flags.chars_per_chunk
    bounds.total_chars = char_flags.total_chars

    hidden_document_source_types = await _probe_hidden_document_source_types(
        session,
        org_id=org_id,
        normalized_project=normalized_project,
        as_of=as_of,
        as_of_end=as_of_end,
        allowed_visibilities=allowed,
    )
    hidden_source_types = set(hidden_document_source_types) | set(hidden_chunk_source_types)
    if hidden_source_types:
        visibility_limitations.append(
            VisibilityLimitation(
                source="knowledge_visibility",
                reason="visibility_policy",
                detail=_VISIBILITY_OMISSION_LIMITATION,
            )
        )
        if _VISIBILITY_OMISSION_LIMITATION not in limitations:
            limitations.append(_VISIBILITY_OMISSION_LIMITATION)

    _record_bound_limitations(bounds, issues_by_source, limitations)

    document_facts, chunk_facts = _project_facts(
        documents,
        prepared_chunks,
        client_safe=client_safe,
        evidence=evidence,
    )

    source_availability = _build_source_availability(
        document_facts,
        chunk_facts,
        bounds=bounds,
        issues_by_source=issues_by_source,
        limitations=limitations,
        visibility_limitations=visibility_limitations,
        hidden_source_types=hidden_source_types,
    )

    if documents or prepared_chunks:
        _set_source_issue(
            issues_by_source,
            "knowledge_documents",
            DataQualityState.COMPLETE,
            f"Knowledge document query succeeded with {len(documents)} row(s).",
        )
        _set_source_issue(
            issues_by_source,
            "knowledge_chunks",
            DataQualityState.COMPLETE,
            f"Knowledge chunk query succeeded with {len(prepared_chunks)} row(s).",
        )

    if client_safe:
        evidence = [item for item in evidence if item.visibility == EvidenceVisibility.CLIENT_SAFE]

    facts = KnowledgeEvidenceFacts(
        documents=document_facts,
        chunks=chunk_facts,
        source_availability=source_availability,
        as_of=as_of,
        project_scope_key=scope_key,
    )
    return (
        facts,
        evidence,
        _finalize_issues(issues_by_source),
        visibility_limitations,
        limitations,
    )


def _record_bound_limitations(
    bounds: _BoundFlags,
    issues_by_source: dict[str, DataQualityIssue],
    limitations: list[str],
) -> None:
    if bounds.documents:
        limitations.append(
            "Knowledge document query reached the configured row bound; results may be incomplete."
        )
        _set_source_issue(
            issues_by_source,
            "knowledge_documents",
            DataQualityState.PARTIAL,
            "Knowledge document query reached the configured row bound.",
        )
    if bounds.versions:
        limitations.append(
            "Knowledge version validation query reached the configured row bound; "
            "results may be incomplete."
        )
        _set_source_issue(
            issues_by_source,
            "knowledge_versions",
            DataQualityState.PARTIAL,
            "Knowledge version validation query reached the configured row bound.",
        )
    if bounds.chunks:
        limitations.append(
            "Knowledge chunk query reached the configured row bound; results may be incomplete."
        )
        _set_source_issue(
            issues_by_source,
            "knowledge_chunks",
            DataQualityState.PARTIAL,
            "Knowledge chunk query reached the configured row bound.",
        )
    if bounds.chunks_per_document:
        limitations.append(
            "Knowledge per-document chunk bound was reached; later chunks were omitted."
        )
        _set_source_issue(
            issues_by_source,
            "knowledge_chunks",
            DataQualityState.PARTIAL,
            "Knowledge per-document chunk bound was reached.",
        )
    if bounds.chars_per_chunk:
        limitations.append(
            "One or more Knowledge chunks exceeded the per-chunk character "
            "bound and were truncated."
        )
        _set_source_issue(
            issues_by_source,
            "knowledge_chunks",
            DataQualityState.PARTIAL,
            "Knowledge per-chunk character bound was reached.",
        )
    if bounds.total_chars:
        limitations.append(
            "Knowledge total untrusted-text character bound was reached; later chunks were omitted."
        )
        _set_source_issue(
            issues_by_source,
            "knowledge_chunks",
            DataQualityState.PARTIAL,
            "Knowledge total untrusted-text character bound was reached.",
        )


def _prepare_chunk_rows(raw_chunks: list[tuple]) -> tuple[list[_ChunkRow], bool]:
    """Normalize source text, hash full content, drop empty chunks."""
    prepared: list[_ChunkRow] = []
    empty_skipped = False
    for row in raw_chunks:
        full_text = _select_source_text(row.chunk_text, row.content)
        if not full_text:
            empty_skipped = True
            continue
        prepared.append(
            _ChunkRow(
                id=row.id,
                document_id=row.document_id,
                version_id=row.version_id,
                chunk_index=row.chunk_index,
                page_number=row.page_number,
                section_title=row.section_title,
                heading=row.heading,
                display_text=full_text,
                content_sha256=_content_sha256(full_text),
                visibility=row.visibility,
                created_at=row.created_at,
            )
        )
    return prepared, empty_skipped


def _apply_character_bounds(chunks: list[_ChunkRow]) -> tuple[list[_ChunkRow], _BoundFlags]:
    per_chunk_truncated = False
    total_truncated = False
    total_chars = 0
    bounded: list[_ChunkRow] = []
    for row in chunks:
        display = row.display_text
        if len(display) > _MAX_CHARS_PER_CHUNK:
            display = display[:_MAX_CHARS_PER_CHUNK]
            per_chunk_truncated = True
        if total_chars + len(display) > _MAX_TOTAL_UNTRUSTED_CHARS:
            remaining = _MAX_TOTAL_UNTRUSTED_CHARS - total_chars
            if remaining <= 0:
                total_truncated = True
                break
            display = display[:remaining]
            total_truncated = True
            per_chunk_truncated = True
        bounded.append(
            _ChunkRow(
                id=row.id,
                document_id=row.document_id,
                version_id=row.version_id,
                chunk_index=row.chunk_index,
                page_number=row.page_number,
                section_title=row.section_title,
                heading=row.heading,
                display_text=display,
                content_sha256=row.content_sha256,
                visibility=row.visibility,
                created_at=row.created_at,
            )
        )
        total_chars += len(display)
        if total_truncated:
            break
    return bounded, _BoundFlags(
        chars_per_chunk=per_chunk_truncated,
        total_chars=total_truncated,
    )


def _project_facts(
    documents: list[_DocumentRow],
    chunks: list[_ChunkRow],
    *,
    client_safe: bool,
    evidence: list[ClientEvidenceReference],
) -> tuple[list[KnowledgeDocumentFacts], list[KnowledgeChunkFacts]]:
    visibility = _evidence_visibility(client_safe)
    document_facts: list[KnowledgeDocumentFacts] = []
    version_by_doc: dict[UUID, str] = {}

    for row in documents:
        version_by_doc[row.id] = row.version
        facts = KnowledgeDocumentFacts(
            document_id=row.id,
            source_type=_enum_str(row.source_type),
            document_type=row.document_type,
            version=row.version,
            visibility=_enum_str(row.visibility),
            effective_date=row.effective_date,
            approved_at=row.approved_at,
            indexed_at=row.indexed_at,
            active_version_id=row.active_version_id,
            document_title=None if client_safe else row.title,
            observed_at=row.updated_at or row.created_at or row.approved_at,
        )
        document_facts.append(facts)
        claim_keys = list(_DOCUMENT_CLAIM_KEYS)
        if not client_safe:
            claim_keys.append("document_title")
        evidence.append(
            ClientEvidenceReference(
                source_agent=SourceAgent.OPERATIONAL_KNOWLEDGE,
                source_table="knowledge_documents",
                source_row_id=row.id,
                description=_GENERIC_DESCRIPTION,
                visibility=visibility,
                observed_at=facts.observed_at,
                claim_keys=claim_keys,
            )
        )

    chunk_facts: list[KnowledgeChunkFacts] = []
    for row in chunks:
        parent = next((doc for doc in documents if doc.id == row.document_id), None)
        if parent is None:
            continue
        section_label = None
        if not client_safe:
            section_label = row.section_title or row.heading
        facts = KnowledgeChunkFacts(
            chunk_id=row.id,
            document_id=row.document_id,
            source_type=_enum_str(parent.source_type),
            document_version=version_by_doc.get(row.document_id, parent.version),
            chunk_index=row.chunk_index,
            page_number=row.page_number,
            section_label=section_label,
            untrusted_text=row.display_text,
            content_sha256=row.content_sha256,
            observed_at=row.created_at,
        )
        chunk_facts.append(facts)
        claim_keys = list(_CHUNK_CLAIM_KEYS)
        if not client_safe:
            claim_keys.append("section_label")
        evidence.append(
            ClientEvidenceReference(
                source_agent=SourceAgent.OPERATIONAL_KNOWLEDGE,
                source_table="knowledge_document_chunks",
                source_row_id=row.id,
                description=_GENERIC_DESCRIPTION,
                visibility=visibility,
                observed_at=row.created_at,
                claim_keys=claim_keys,
            )
        )

    document_facts.sort(
        key=lambda item: (item.source_type, item.approved_at, str(item.document_id))
    )
    chunk_facts.sort(key=lambda item: (str(item.document_id), item.chunk_index, str(item.chunk_id)))
    return document_facts, chunk_facts


def _build_source_availability(
    documents: list[KnowledgeDocumentFacts],
    chunks: list[KnowledgeChunkFacts],
    *,
    bounds: _BoundFlags,
    issues_by_source: dict[str, DataQualityIssue],
    limitations: list[str],
    visibility_limitations: list[VisibilityLimitation],
    hidden_source_types: set[str],
) -> list[KnowledgeSourceAvailabilityFacts]:
    docs_by_type: dict[str, list[KnowledgeDocumentFacts]] = {}
    for doc in documents:
        docs_by_type.setdefault(doc.source_type, []).append(doc)
    chunks_by_type: dict[str, list[KnowledgeChunkFacts]] = {}
    for chunk in chunks:
        chunks_by_type.setdefault(chunk.source_type, []).append(chunk)

    availability: list[KnowledgeSourceAvailabilityFacts] = []
    for requirement_id, source_type in _SOURCE_REQUIREMENTS:
        if source_type is None:
            availability.append(
                KnowledgeSourceAvailabilityFacts(
                    requirement_id=requirement_id,
                    source_type="client_communication_note",
                    document_count=0,
                    chunk_count=0,
                    state=DataQualityState.UNAVAILABLE,
                    limitation=_CI_D14_LIMITATION,
                )
            )
            _set_source_issue(
                issues_by_source,
                f"knowledge_{requirement_id.lower()}",
                DataQualityState.UNAVAILABLE,
                _CI_D14_LIMITATION,
            )
            limitations.append(_CI_D14_LIMITATION)
            visibility_limitations.append(
                VisibilityLimitation(
                    source="knowledge_ci_d14",
                    reason="missing_source_type",
                    detail=_CI_D14_LIMITATION,
                )
            )
            continue

        type_key = source_type.value
        type_docs = docs_by_type.get(type_key, [])
        type_chunks = chunks_by_type.get(type_key, [])
        source_key = f"knowledge_{requirement_id.lower()}"
        has_hidden = type_key in hidden_source_types

        if not type_docs:
            if has_hidden:
                state = DataQualityState.UNAVAILABLE
                limitation = _VISIBILITY_SOURCE_UNAVAILABLE_LIMITATION
            else:
                state = DataQualityState.UNAVAILABLE
                limitation = (
                    f"No approved retrieval-ready {type_key} documents found for the "
                    "authorized project scope at or before as_of."
                )
            _set_source_issue(issues_by_source, source_key, state, limitation)
        elif has_hidden:
            state = DataQualityState.PARTIAL
            limitation = _VISIBILITY_SOURCE_PARTIAL_LIMITATION
            _set_source_issue(issues_by_source, source_key, state, limitation)
        elif bounds.any_bound:
            state = DataQualityState.PARTIAL
            limitation = (
                f"{requirement_id} evidence may be incomplete because a Knowledge "
                "query or projection bound was reached."
            )
            _set_source_issue(issues_by_source, source_key, state, limitation)
        elif type_docs and not type_chunks:
            state = DataQualityState.PARTIAL
            limitation = (
                f"{requirement_id} documents were found but no active-version chunks "
                "were available."
            )
            _set_source_issue(issues_by_source, source_key, state, limitation)
        else:
            state = DataQualityState.COMPLETE
            limitation = None
            _set_source_issue(
                issues_by_source,
                source_key,
                state,
                f"{requirement_id} approved retrieval-ready evidence was loaded.",
            )

        availability.append(
            KnowledgeSourceAvailabilityFacts(
                requirement_id=requirement_id,
                source_type=type_key,
                document_count=len(type_docs),
                chunk_count=len(type_chunks),
                state=state,
                limitation=limitation,
            )
        )

    return availability


async def _load_retrieval_ready_documents(
    session: AsyncSession,
    *,
    org_id: UUID,
    normalized_project: str,
    as_of: date,
    as_of_end: datetime,
    allowed_visibilities: list[KnowledgeVisibility],
) -> tuple[list[_DocumentRow], bool]:
    if not allowed_visibilities or not normalized_project:
        return [], False

    result = await session.execute(
        select(
            KnowledgeDocument.id,
            KnowledgeDocument.source_type,
            KnowledgeDocument.document_type,
            KnowledgeDocument.version,
            KnowledgeDocument.visibility,
            KnowledgeDocument.effective_date,
            KnowledgeDocument.approved_at,
            KnowledgeDocument.indexed_at,
            KnowledgeDocument.active_version_id,
            KnowledgeDocument.title,
            KnowledgeDocument.created_at,
            KnowledgeDocument.updated_at,
        )
        .where(
            *_document_base_filters(
                org_id=org_id,
                normalized_project=normalized_project,
                as_of=as_of,
                as_of_end=as_of_end,
            ),
            KnowledgeDocument.visibility.in_(allowed_visibilities),
        )
        .order_by(
            KnowledgeDocument.approved_at.desc(),
            KnowledgeDocument.indexed_at.desc(),
            KnowledgeDocument.id.desc(),
        )
        .limit(_MAX_DOCUMENTS + 1)
    )
    rows = [
        _DocumentRow(
            id=row.id,
            source_type=row.source_type,
            document_type=row.document_type,
            version=row.version,
            visibility=row.visibility,
            effective_date=row.effective_date,
            approved_at=row.approved_at,
            indexed_at=row.indexed_at,
            active_version_id=row.active_version_id,
            title=row.title,
            created_at=row.created_at,
            updated_at=row.updated_at,
        )
        for row in result.all()
    ]
    return _trim_limit_plus_one(rows, _MAX_DOCUMENTS)


async def _probe_hidden_document_source_types(
    session: AsyncSession,
    *,
    org_id: UUID,
    normalized_project: str,
    as_of: date,
    as_of_end: datetime,
    allowed_visibilities: list[KnowledgeVisibility],
) -> set[str]:
    """Metadata-only probe: which mapped source types have visibility-hidden docs.

    Selects only ``source_type`` — never IDs, titles, or sensitive metadata.
    """
    if not normalized_project:
        return set()
    denied = [
        visibility for visibility in KnowledgeVisibility if visibility not in allowed_visibilities
    ]
    if not denied:
        return set()

    result = await session.execute(
        select(KnowledgeDocument.source_type)
        .join(
            KnowledgeDocumentVersion,
            and_(
                KnowledgeDocumentVersion.id == KnowledgeDocument.active_version_id,
                KnowledgeDocumentVersion.document_id == KnowledgeDocument.id,
                KnowledgeDocumentVersion.org_id == org_id,
                KnowledgeDocumentVersion.is_active.is_(True),
                KnowledgeDocumentVersion.created_at <= as_of_end,
                KnowledgeDocumentVersion.uploaded_at <= as_of_end,
                KnowledgeDocumentVersion.version.isnot(None),
                func.length(func.trim(KnowledgeDocumentVersion.version)) > 0,
            ),
        )
        .where(
            *_document_base_filters(
                org_id=org_id,
                normalized_project=normalized_project,
                as_of=as_of,
                as_of_end=as_of_end,
            ),
            KnowledgeDocument.visibility.in_(denied),
        )
        .distinct()
        .limit(len(_MAPPED_SOURCE_TYPES))
    )
    return {_enum_str(row[0]) for row in result.all()}


async def _validate_active_versions(
    session: AsyncSession,
    *,
    org_id: UUID,
    as_of_end: datetime,
    candidates: list[_DocumentRow],
) -> tuple[list[_DocumentRow], _BoundFlags]:
    if not candidates:
        return [], _BoundFlags()

    version_ids = [row.active_version_id for row in candidates]
    result = await session.execute(
        select(
            KnowledgeDocumentVersion.id,
            KnowledgeDocumentVersion.document_id,
            KnowledgeDocumentVersion.version,
        )
        .where(
            KnowledgeDocumentVersion.id.in_(version_ids),
            KnowledgeDocumentVersion.org_id == org_id,
            KnowledgeDocumentVersion.is_active.is_(True),
            KnowledgeDocumentVersion.created_at <= as_of_end,
            KnowledgeDocumentVersion.uploaded_at <= as_of_end,
            KnowledgeDocumentVersion.version.isnot(None),
            func.length(func.trim(KnowledgeDocumentVersion.version)) > 0,
        )
        .order_by(
            KnowledgeDocumentVersion.uploaded_at.desc(),
            KnowledgeDocumentVersion.id.desc(),
        )
        .limit(_MAX_VERSIONS + 1)
    )
    version_rows, versions_truncated = _trim_limit_plus_one(list(result.all()), _MAX_VERSIONS)
    by_id = {
        row.id: _VersionRow(id=row.id, document_id=row.document_id, version=row.version.strip())
        for row in version_rows
    }

    validated: list[_DocumentRow] = []
    excluded = 0
    for candidate in candidates:
        version = by_id.get(candidate.active_version_id)
        if version is None or version.document_id != candidate.id:
            excluded += 1
            continue
        validated.append(
            _DocumentRow(
                id=candidate.id,
                source_type=candidate.source_type,
                document_type=candidate.document_type,
                version=version.version,
                visibility=candidate.visibility,
                effective_date=candidate.effective_date,
                approved_at=candidate.approved_at,
                indexed_at=candidate.indexed_at,
                active_version_id=candidate.active_version_id,
                title=candidate.title,
                created_at=candidate.created_at,
                updated_at=candidate.updated_at,
            )
        )

    return validated, _BoundFlags(
        versions=versions_truncated,
        versions_incomplete=excluded > 0 or versions_truncated,
    )


async def _load_document_chunks(
    session: AsyncSession,
    *,
    org_id: UUID,
    as_of_end: datetime,
    documents: list[_DocumentRow],
    allowed_visibilities: list[KnowledgeVisibility],
    role: AppRole,
    client_safe: bool,
) -> tuple[list, _BoundFlags, set[str]]:
    if not documents:
        return [], _BoundFlags(), set()

    pairs = [(row.id, row.active_version_id) for row in documents]
    parent_by_id = {row.id: row for row in documents}
    parent_visibility = {
        row.id: _status_enum(row.visibility, KnowledgeVisibility) for row in documents
    }
    parent_source_type = {row.id: _enum_str(row.source_type) for row in documents}

    # Effective visibility before windowing: null inherits authorized parent;
    # explicit values must be in the authorized set.
    visibility_predicate = or_(
        KnowledgeDocumentChunk.visibility.is_(None),
        KnowledgeDocumentChunk.visibility.in_(allowed_visibilities),
    )

    row_number = (
        func.row_number()
        .over(
            partition_by=KnowledgeDocumentChunk.document_id,
            order_by=(
                KnowledgeDocumentChunk.chunk_index.asc(),
                KnowledgeDocumentChunk.id.asc(),
            ),
        )
        .label("rn")
    )
    ranked = (
        select(
            KnowledgeDocumentChunk.id,
            KnowledgeDocumentChunk.document_id,
            KnowledgeDocumentChunk.version_id,
            KnowledgeDocumentChunk.chunk_index,
            KnowledgeDocumentChunk.page_number,
            KnowledgeDocumentChunk.section_title,
            KnowledgeDocumentChunk.heading,
            KnowledgeDocumentChunk.chunk_text,
            KnowledgeDocumentChunk.content,
            KnowledgeDocumentChunk.visibility,
            KnowledgeDocumentChunk.created_at,
            row_number,
        )
        .where(
            KnowledgeDocumentChunk.org_id == org_id,
            tuple_(
                KnowledgeDocumentChunk.document_id,
                KnowledgeDocumentChunk.version_id,
            ).in_(pairs),
            KnowledgeDocumentChunk.created_at <= as_of_end,
            visibility_predicate,
            _sql_chunk_has_source_text(),
        )
        .subquery()
    )
    result = await session.execute(
        select(ranked)
        .where(ranked.c.rn <= _MAX_CHUNKS_PER_DOCUMENT + 1)
        .order_by(
            ranked.c.document_id.asc(),
            ranked.c.chunk_index.asc(),
            ranked.c.id.asc(),
        )
        .limit(_MAX_CHUNKS + len(documents) + 1)
    )
    raw_rows = list(result.all())
    per_doc_truncated = any(int(row.rn) > _MAX_CHUNKS_PER_DOCUMENT for row in raw_rows)

    # Defense in depth: re-check effective visibility in Python.
    hidden_source_types: set[str] = set()
    visible_raw: list = []
    for row in raw_rows:
        if int(row.rn) > _MAX_CHUNKS_PER_DOCUMENT:
            continue
        parent = parent_by_id.get(row.document_id)
        parent_vis = parent_visibility.get(row.document_id)
        if parent is None or parent_vis is None:
            continue
        effective = (
            _status_enum(row.visibility, KnowledgeVisibility)
            if row.visibility is not None
            else parent_vis
        )
        if not can_access_visibility(role, effective):
            hidden_source_types.add(parent_source_type[row.document_id])
            continue
        if client_safe and effective != KnowledgeVisibility.CLIENT_SAFE:
            hidden_source_types.add(parent_source_type[row.document_id])
            continue
        visible_raw.append(row)

    # Detect hidden siblings filtered before the window. Derive source type from
    # already-authorized parent documents only — never load hidden content.
    hidden_doc_ids = await _probe_hidden_chunk_document_ids(
        session,
        org_id=org_id,
        as_of_end=as_of_end,
        pairs=pairs,
        allowed_visibilities=allowed_visibilities,
    )
    for doc_id in hidden_doc_ids:
        source_type = parent_source_type.get(doc_id)
        if source_type is not None:
            hidden_source_types.add(source_type)

    per_doc: dict[UUID, list] = defaultdict(list)
    for row in visible_raw:
        per_doc[row.document_id].append(row)

    ordered_docs = sorted(documents, key=lambda row: (str(row.id),))
    projected: list = []
    global_truncated = False
    for doc in ordered_docs:
        for chunk in per_doc.get(doc.id, []):
            if len(projected) >= _MAX_CHUNKS:
                global_truncated = True
                break
            projected.append(chunk)
        if global_truncated:
            break

    return (
        projected,
        _BoundFlags(chunks=global_truncated, chunks_per_document=per_doc_truncated),
        hidden_source_types,
    )


async def _probe_hidden_chunk_document_ids(
    session: AsyncSession,
    *,
    org_id: UUID,
    as_of_end: datetime,
    pairs: list[tuple[UUID, UUID]],
    allowed_visibilities: list[KnowledgeVisibility],
) -> set[UUID]:
    denied = [
        visibility for visibility in KnowledgeVisibility if visibility not in allowed_visibilities
    ]
    if not denied or not pairs:
        return set()
    result = await session.execute(
        select(KnowledgeDocumentChunk.document_id)
        .where(
            KnowledgeDocumentChunk.org_id == org_id,
            tuple_(
                KnowledgeDocumentChunk.document_id,
                KnowledgeDocumentChunk.version_id,
            ).in_(pairs),
            KnowledgeDocumentChunk.created_at <= as_of_end,
            KnowledgeDocumentChunk.visibility.in_(denied),
        )
        .distinct()
        .limit(len(pairs))
    )
    return {row[0] for row in result.all()}
