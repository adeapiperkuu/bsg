"""Client Intelligence Operational Knowledge evidence adapter tests."""

from __future__ import annotations

import hashlib
import re
from datetime import UTC, date, datetime, time
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
from uuid import UUID, uuid4

import pytest

from app.agents.client_intelligence import (
    DataQualityState,
    EvidenceVisibility,
    build_client_evidence_pack,
    load_knowledge_evidence,
    resolve_reporting_period,
)
from app.agents.client_intelligence import knowledge_adapter as knowledge_mod
from app.agents.client_intelligence.evidence_pack import (
    _fingerprint,
    _knowledge_fingerprint_projection,
)
from app.core.exceptions import ApiError
from app.core.security import CurrentUser
from app.db.models import (
    AppRole,
    KnowledgeDocumentStatus,
    KnowledgeIndexingStatus,
    KnowledgeProcessingStatus,
    KnowledgeSourceType,
    KnowledgeVisibility,
    ProjectStatus,
)

_PAST = datetime(2026, 1, 1, tzinfo=UTC)
_AS_OF = date(2026, 6, 18)
_PROJECT_NAME = "Aurora Labeling"


class FakeScalars:
    def __init__(self, items: list[object] | None = None) -> None:
        self._items = items or []

    def all(self) -> list[object]:
        return list(self._items)

    def __iter__(self):
        return iter(self._items)


class FakeResult:
    def __init__(self, value: object = None, items: list[object] | None = None) -> None:
        self._value = value
        self._items = items or []

    def scalar_one_or_none(self) -> object:
        return self._value if self._value is not None else (self._items[0] if self._items else None)

    def scalars(self) -> FakeScalars:
        return FakeScalars(self._items)

    def all(self) -> list[object]:
        return list(self._items)


class FakeSession:
    def __init__(
        self,
        *,
        as_of: date | None = None,
        project_name: str = _PROJECT_NAME,
        org_id=None,
        documents: list[object] | None = None,
        versions: list[object] | None = None,
        chunks: list[object] | None = None,
        milestones: list[object] | None = None,
    ) -> None:
        self.as_of = as_of or _AS_OF
        self.as_of_end = datetime.combine(self.as_of, time.max, tzinfo=UTC)
        self.project_name = project_name
        self.org_id = org_id
        self.documents = documents or []
        self.versions = versions or []
        self.chunks = chunks or []
        self.milestones = milestones or []
        self.statements: list[str] = []

    def _project_match(self, row: object) -> bool:
        project = getattr(row, "project", None)
        if project is None:
            return False
        return project.strip().lower() == self.project_name.strip().lower()

    def _retrieval_ready(self, row: object) -> bool:
        if getattr(row, "status", None) != KnowledgeDocumentStatus.APPROVED:
            return False
        if getattr(row, "indexing_status", None) != KnowledgeIndexingStatus.INDEXED:
            return False
        if getattr(row, "processing_status", None) != KnowledgeProcessingStatus.READY:
            return False
        if getattr(row, "approved_at", None) is None:
            return False
        if getattr(row, "indexed_at", None) is None:
            return False
        if getattr(row, "active_version_id", None) is None:
            return False
        effective = getattr(row, "effective_date", None)
        if effective is None or effective > self.as_of:
            return False
        owner = getattr(row, "owner_approver", None)
        if owner is None or not str(owner).strip():
            return False
        expiry = getattr(row, "expiry_date", None)
        if expiry is not None and expiry < self.as_of:
            return False
        for attr in ("created_at", "approved_at", "indexed_at", "upload_date"):
            value = getattr(row, attr, None)
            if value is not None and value > self.as_of_end:
                return False
        return True

    def _version_valid(self, row: object) -> bool:
        if not getattr(row, "is_active", False):
            return False
        version = getattr(row, "version", None)
        if version is None or not str(version).strip():
            return False
        for attr in ("created_at", "uploaded_at"):
            value = getattr(row, attr, None)
            if value is not None and value > self.as_of_end:
                return False
        if self.org_id is None:
            return True
        return getattr(row, "org_id", None) in {None, self.org_id}

    async def execute(self, stmt) -> FakeResult:
        compiled = str(stmt.compile(compile_kwargs={"literal_binds": True}))
        self.statements.append(compiled)
        assert "LIMIT" in compiled.upper() or "limit" in compiled
        lower = compiled.lower()

        if "FROM knowledge_documents" in compiled:
            assert "extracted_text" not in lower
            assert "executive_summary" not in lower
            assert "key_procedures" not in lower
            assert "important_warnings" not in lower
            assert "rejection_reason" not in lower
            assert "file_url" not in lower
            assert "storage_path" not in lower
            assert "checksum_sha256" not in lower
            assert "approved_by" not in lower
            assert "uploaded_by" not in lower
            assert "department" not in lower
            rows = [
                r
                for r in self.documents
                if self._project_match(r)
                and self._retrieval_ready(r)
                and getattr(r, "source_type", None)
                in {
                    KnowledgeSourceType.SOP,
                    KnowledgeSourceType.TRAINING_DOCUMENT,
                    KnowledgeSourceType.PROJECT_CHARTER,
                    KnowledgeSourceType.ESCALATION_NOTE,
                }
            ]
            if "client_safe" in lower and "internal_only" not in lower:
                rows = [
                    r
                    for r in rows
                    if getattr(r, "visibility", None) == KnowledgeVisibility.CLIENT_SAFE
                ]
            rows.sort(
                key=lambda r: (
                    -(r.approved_at.timestamp() if r.approved_at else 0),
                    -(r.indexed_at.timestamp() if r.indexed_at else 0),
                    str(r.id),
                )
            )
            limit_match = re.search(r"LIMIT\s+(\d+)", compiled, re.IGNORECASE)
            if limit_match:
                rows = rows[: int(limit_match.group(1))]
            return FakeResult(None, rows)

        if "FROM knowledge_document_versions" in compiled:
            assert "file_name" not in lower
            assert "file_url" not in lower
            assert "storage_path" not in lower
            assert "approved_by" not in lower
            assert "uploaded_by" not in lower
            rows = [r for r in self.versions if self._version_valid(r)]
            rows.sort(
                key=lambda r: (
                    -(r.uploaded_at.timestamp() if getattr(r, "uploaded_at", None) else 0),
                    str(r.id),
                )
            )
            limit_match = re.search(r"LIMIT\s+(\d+)", compiled, re.IGNORECASE)
            if limit_match:
                rows = rows[: int(limit_match.group(1))]
            return FakeResult(None, rows)

        if "knowledge_document_chunks" in compiled:
            assert "embedding" not in lower
            assert "token_count" not in lower
            assert "folder_id" not in lower
            assert "document_id" in lower and "version_id" in lower
            valid_pairs = {(r.document_id, r.id) for r in self.versions if self._version_valid(r)}
            rows = [
                r
                for r in self.chunks
                if (getattr(r, "document_id", None), getattr(r, "version_id", None)) in valid_pairs
                and (r.created_at is None or r.created_at <= self.as_of_end)
            ]
            by_doc: dict = {}
            for row in rows:
                by_doc.setdefault(row.document_id, []).append(row)
            augmented: list[object] = []
            for doc_id in sorted(by_doc, key=str):
                ordered = sorted(
                    by_doc[doc_id],
                    key=lambda item: (getattr(item, "chunk_index", 0), str(item.id)),
                )
                for index, row in enumerate(ordered, start=1):
                    augmented.append(SimpleNamespace(**vars(row), rn=index))
            rn_match = re.search(r"\brn\s*<=\s*(\d+)", compiled, re.IGNORECASE)
            if rn_match:
                max_rn = int(rn_match.group(1))
                augmented = [row for row in augmented if row.rn <= max_rn]
            augmented.sort(
                key=lambda r: (
                    str(r.document_id),
                    getattr(r, "chunk_index", 0),
                    str(r.id),
                )
            )
            limit_match = re.search(r"LIMIT\s+(\d+)", compiled, re.IGNORECASE)
            if limit_match:
                augmented = augmented[: int(limit_match.group(1))]
            return FakeResult(None, augmented)

        if "FROM knowledge_document_embeddings" in compiled:
            raise AssertionError("Knowledge embeddings must not be queried")
        if "FROM client_communications" in compiled:
            raise AssertionError("ClientCommunication must not be queried")
        if "FROM milestones" in compiled:
            return FakeResult(None, self.milestones)
        if "FROM teams" in compiled:
            return FakeResult(None, [])
        if "FROM annotators" in compiled:
            return FakeResult(None, [])
        if "FROM utilization_snapshots" in compiled:
            return FakeResult(None, [])
        if "FROM project_skill_requirements" in compiled:
            return FakeResult(None, [])
        if "FROM skills" in compiled:
            return FakeResult(None, [])
        if "FROM annotator_skills" in compiled:
            return FakeResult(None, [])
        if "FROM training_programs" in compiled:
            return FakeResult(None, [])
        if "FROM training_records" in compiled:
            return FakeResult(None, [])
        if "FROM capability_gaps" in compiled:
            return FakeResult(None, [])
        if "FROM project_scope_states" in compiled:
            return FakeResult(None, [])
        if "FROM project_charters" in compiled:
            return FakeResult(None, [])
        if "FROM project_dependencies" in compiled:
            return FakeResult(None, [])
        if "FROM governance_actions" in compiled:
            return FakeResult(None, [])
        if "FROM governance_escalations" in compiled:
            return FakeResult(None, [])
        if "FROM quality_snapshots" in compiled:
            return FakeResult(None, [])
        if "FROM throughput_snapshots" in compiled:
            return FakeResult(None)
        if "FROM delivery_confidence_scores" in compiled:
            return FakeResult(None)
        if "FROM risk_alerts" in compiled:
            return FakeResult(None, [])
        if "FROM bottlenecks" in compiled:
            return FakeResult(None, [])
        if "FROM metric_configurations" in compiled:
            return FakeResult(None, [])
        return FakeResult(None, [])


def _user(role: AppRole, org_id=None) -> CurrentUser:
    return CurrentUser(
        id=uuid4(),
        org_id=org_id or uuid4(),
        email="ci-knowledge@example.com",
        role=role,
        is_active=True,
    )


def _project(org_id=None, name: str = _PROJECT_NAME) -> SimpleNamespace:
    return SimpleNamespace(
        id=uuid4(),
        org_id=org_id or uuid4(),
        name=name,
        status=ProjectStatus.ACTIVE,
    )


def _version(**kwargs) -> SimpleNamespace:
    defaults = {
        "id": uuid4(),
        "document_id": uuid4(),
        "org_id": None,
        "version": "1.0",
        "is_active": True,
        "created_at": _PAST,
        "uploaded_at": _PAST,
        "file_name": "secret.pdf",
    }
    defaults.update(kwargs)
    return SimpleNamespace(**defaults)


def _document(**kwargs) -> SimpleNamespace:
    version_id = kwargs.pop("active_version_id", uuid4())
    defaults = {
        "id": uuid4(),
        "source_type": KnowledgeSourceType.SOP,
        "document_type": "sop",
        "version": "doc-meta-1.0",
        "visibility": KnowledgeVisibility.CLIENT_SAFE,
        "status": KnowledgeDocumentStatus.APPROVED,
        "indexing_status": KnowledgeIndexingStatus.INDEXED,
        "processing_status": KnowledgeProcessingStatus.READY,
        "project": _PROJECT_NAME,
        "effective_date": date(2026, 1, 1),
        "approved_at": datetime(2026, 2, 1, tzinfo=UTC),
        "indexed_at": datetime(2026, 2, 2, tzinfo=UTC),
        "upload_date": datetime(2026, 1, 15, tzinfo=UTC),
        "active_version_id": version_id,
        "title": "Client Labeling SOP",
        "owner_approver": "Delivery Manager",
        "expiry_date": None,
        "created_at": _PAST,
        "updated_at": datetime(2026, 2, 3, tzinfo=UTC),
        "deleted_at": None,
        "description": "SECRET DESCRIPTION",
        "extracted_text": "SECRET EXTRACTED",
        "executive_summary": "SECRET SUMMARY",
        "department": "SECRET DEPT",
        "file_url": "https://secret.example/file",
    }
    defaults.update(kwargs)
    return SimpleNamespace(**defaults)


def _chunk(**kwargs) -> SimpleNamespace:
    defaults = {
        "id": uuid4(),
        "document_id": uuid4(),
        "version_id": uuid4(),
        "chunk_index": 0,
        "page_number": 1,
        "section_title": "Escalation Path",
        "heading": "Heading",
        "chunk_text": "Escalate blockers within one business day.",
        "visibility": None,
        "created_at": _PAST,
        "embedding": [0.1, 0.2],
        "token_count": 12,
        "department": "SECRET",
        "project": "SECRET PROJECT",
    }
    defaults.update(kwargs)
    return SimpleNamespace(**defaults)


def _eligible_bundle(**doc_kwargs):
    """Return document + matching active version + one chunk."""
    version_label = doc_kwargs.pop("version_label", "1.0")
    doc = _document(**doc_kwargs)
    version = _version(
        id=doc.active_version_id,
        document_id=doc.id,
        version=version_label,
    )
    chunk = _chunk(document_id=doc.id, version_id=doc.active_version_id)
    return doc, version, chunk


@pytest.mark.asyncio
async def test_ci_d14_is_unavailable_phase1_blocker() -> None:
    org_id = uuid4()
    period = resolve_reporting_period(_AS_OF)
    facts, _, issues, vis, limitations = await load_knowledge_evidence(
        FakeSession(),
        uuid4(),
        org_id,
        _PROJECT_NAME,
        period,
        visibility_mode=EvidenceVisibility.CLIENT_SAFE,
        role=AppRole.CLIENT,
    )
    d14 = next(item for item in facts.source_availability if item.requirement_id == "CI-D14")
    assert d14.state == DataQualityState.UNAVAILABLE
    assert d14.document_count == 0
    assert d14.chunk_count == 0
    assert "CLIENT_COMMUNICATION_NOTE" in (d14.limitation or "")
    assert any("Phase 1 blocker" in item for item in limitations)
    assert any(item.reason == "missing_source_type" for item in vis)
    assert any(i.state == DataQualityState.UNAVAILABLE for i in issues if "d14" in i.source)


@pytest.mark.asyncio
async def test_lesson_learned_is_not_treated_as_communication_notes() -> None:
    org_id = uuid4()
    period = resolve_reporting_period(_AS_OF)
    lesson = _document(source_type=KnowledgeSourceType.LESSON_LEARNED, title="Lesson")
    chunk = _chunk(
        document_id=lesson.id,
        version_id=lesson.active_version_id,
        chunk_text="Do not treat as communication notes.",
    )
    facts, _, _, _, _ = await load_knowledge_evidence(
        FakeSession(documents=[lesson], chunks=[chunk]),
        uuid4(),
        org_id,
        _PROJECT_NAME,
        period,
        visibility_mode=EvidenceVisibility.INTERNAL,
        role=AppRole.DELIVERY_MANAGER,
    )
    assert all(
        doc.source_type != KnowledgeSourceType.LESSON_LEARNED.value for doc in facts.documents
    )
    d14 = next(item for item in facts.source_availability if item.requirement_id == "CI-D14")
    assert d14.state == DataQualityState.UNAVAILABLE
    assert d14.document_count == 0


@pytest.mark.asyncio
async def test_client_safe_projects_sop_chunks_without_title_or_section() -> None:
    org_id = uuid4()
    period = resolve_reporting_period(_AS_OF)
    doc, version, chunk = _eligible_bundle()
    facts, evidence, _, _, limitations = await load_knowledge_evidence(
        FakeSession(documents=[doc], versions=[version], chunks=[chunk], org_id=org_id),
        uuid4(),
        org_id,
        _PROJECT_NAME,
        period,
        visibility_mode=EvidenceVisibility.CLIENT_SAFE,
        role=AppRole.CLIENT,
    )
    assert len(facts.documents) == 1
    assert facts.documents[0].document_title is None
    assert facts.documents[0].version == "1.0"
    assert facts.documents[0].document_id == doc.id
    assert len(facts.chunks) == 1
    assert facts.chunks[0].section_label is None
    assert facts.chunks[0].page_number == 1
    assert facts.chunks[0].document_version == "1.0"
    assert facts.chunks[0].untrusted_text == chunk.chunk_text
    assert (
        facts.chunks[0].content_sha256
        == hashlib.sha256(chunk.chunk_text.encode("utf-8")).hexdigest()
    )
    blob = str(facts.model_dump(mode="json")).lower()
    assert "client labeling sop" not in blob
    assert "escalation path" not in blob
    assert "secret" not in blob
    assert any("exact normalized project-name" in item.lower() for item in limitations)
    d11 = next(item for item in facts.source_availability if item.requirement_id == "CI-D11")
    assert d11.state == DataQualityState.COMPLETE
    assert d11.document_count == 1
    assert d11.chunk_count == 1
    assert all(item.visibility == EvidenceVisibility.CLIENT_SAFE for item in evidence)


@pytest.mark.asyncio
async def test_internal_mode_retains_title_and_section_label() -> None:
    org_id = uuid4()
    period = resolve_reporting_period(_AS_OF)
    doc, version, chunk = _eligible_bundle(visibility=KnowledgeVisibility.INTERNAL_ONLY)
    facts, _, _, _, _ = await load_knowledge_evidence(
        FakeSession(documents=[doc], versions=[version], chunks=[chunk], org_id=org_id),
        uuid4(),
        org_id,
        _PROJECT_NAME,
        period,
        visibility_mode=EvidenceVisibility.INTERNAL,
        role=AppRole.DELIVERY_MANAGER,
    )
    assert facts.documents[0].document_title == "Client Labeling SOP"
    assert facts.chunks[0].section_label == "Escalation Path"


@pytest.mark.asyncio
async def test_project_scope_is_exact_normalized_match_only() -> None:
    org_id = uuid4()
    period = resolve_reporting_period(_AS_OF)
    exact, exact_version, exact_chunk = _eligible_bundle(project="  Aurora Labeling ")
    substring, substring_version, _ = _eligible_bundle(project="Aurora Labeling Extra", title="No")
    other, other_version, _ = _eligible_bundle(project="Other Project", title="No")
    none_project = _document(project=None, title="No")
    facts, _, _, _, _ = await load_knowledge_evidence(
        FakeSession(
            documents=[exact, substring, other, none_project],
            versions=[exact_version, substring_version, other_version],
            chunks=[exact_chunk],
            org_id=org_id,
        ),
        uuid4(),
        org_id,
        _PROJECT_NAME,
        period,
        visibility_mode=EvidenceVisibility.CLIENT_SAFE,
        role=AppRole.CLIENT,
    )
    assert [doc.document_id for doc in facts.documents] == [exact.id]
    assert (
        facts.project_scope_key
        == hashlib.sha256(_PROJECT_NAME.strip().lower().encode("utf-8")).hexdigest()
    )
    assert _PROJECT_NAME.lower() not in facts.project_scope_key


@pytest.mark.asyncio
async def test_client_safe_excludes_internal_documents() -> None:
    org_id = uuid4()
    period = resolve_reporting_period(_AS_OF)
    internal, version, chunk = _eligible_bundle(
        visibility=KnowledgeVisibility.INTERNAL_ONLY, title="Internal"
    )
    facts, evidence, _, _, _ = await load_knowledge_evidence(
        FakeSession(
            documents=[internal],
            versions=[version],
            chunks=[chunk],
            org_id=org_id,
        ),
        uuid4(),
        org_id,
        _PROJECT_NAME,
        period,
        visibility_mode=EvidenceVisibility.CLIENT_SAFE,
        role=AppRole.CLIENT,
    )
    assert facts.documents == []
    assert facts.chunks == []
    assert all(item.source_table != "knowledge_documents" for item in evidence)


@pytest.mark.asyncio
async def test_non_retrieval_ready_documents_are_excluded() -> None:
    org_id = uuid4()
    period = resolve_reporting_period(_AS_OF)
    draft = _document(status=KnowledgeDocumentStatus.DRAFT)
    not_indexed = _document(indexing_status=KnowledgeIndexingStatus.NOT_INDEXED)
    not_ready = _document(processing_status=KnowledgeProcessingStatus.CHUNKED)
    missing_owner = _document(owner_approver="  ")
    missing_effective = _document(effective_date=None)
    expired = _document(expiry_date=date(2026, 1, 1))
    facts, _, _, _, _ = await load_knowledge_evidence(
        FakeSession(
            documents=[draft, not_indexed, not_ready, missing_owner, missing_effective, expired],
            org_id=org_id,
        ),
        uuid4(),
        org_id,
        _PROJECT_NAME,
        period,
        visibility_mode=EvidenceVisibility.CLIENT_SAFE,
        role=AppRole.CLIENT,
    )
    assert facts.documents == []
    assert facts.chunks == []


@pytest.mark.asyncio
async def test_training_charter_escalation_source_mapping() -> None:
    org_id = uuid4()
    period = resolve_reporting_period(_AS_OF)
    training, training_v, training_c = _eligible_bundle(
        source_type=KnowledgeSourceType.TRAINING_DOCUMENT, title="Training"
    )
    charter, charter_v, charter_c = _eligible_bundle(
        source_type=KnowledgeSourceType.PROJECT_CHARTER, title="Charter"
    )
    escalation, escalation_v, escalation_c = _eligible_bundle(
        source_type=KnowledgeSourceType.ESCALATION_NOTE, title="Escalation"
    )
    facts, _, _, _, _ = await load_knowledge_evidence(
        FakeSession(
            documents=[training, charter, escalation],
            versions=[training_v, charter_v, escalation_v],
            chunks=[training_c, charter_c, escalation_c],
            org_id=org_id,
        ),
        uuid4(),
        org_id,
        _PROJECT_NAME,
        period,
        visibility_mode=EvidenceVisibility.CLIENT_SAFE,
        role=AppRole.CLIENT,
    )
    by_req = {item.requirement_id: item for item in facts.source_availability}
    assert by_req["CI-D12"].state == DataQualityState.COMPLETE
    assert by_req["CI-D13"].state == DataQualityState.COMPLETE
    assert by_req["CI-D15"].state == DataQualityState.COMPLETE
    assert by_req["CI-D11"].state == DataQualityState.UNAVAILABLE


@pytest.mark.asyncio
async def test_document_bound_truncation_is_partial() -> None:
    org_id = uuid4()
    period = resolve_reporting_period(_AS_OF)
    bundles = [_eligible_bundle(approved_at=datetime(2026, 3, i + 1, tzinfo=UTC)) for i in range(3)]
    docs = [b[0] for b in bundles]
    versions = [b[1] for b in bundles]
    chunks = [b[2] for b in bundles]
    with patch.object(knowledge_mod, "_MAX_DOCUMENTS", 2):
        facts, _, issues, _, limitations = await load_knowledge_evidence(
            FakeSession(documents=docs, versions=versions, chunks=chunks, org_id=org_id),
            uuid4(),
            org_id,
            _PROJECT_NAME,
            period,
            visibility_mode=EvidenceVisibility.CLIENT_SAFE,
            role=AppRole.CLIENT,
        )
    assert len(facts.documents) == 2
    assert any(i.state == DataQualityState.PARTIAL for i in issues if "document" in i.source)
    assert any("bound" in item.lower() for item in limitations)
    d11 = next(item for item in facts.source_availability if item.requirement_id == "CI-D11")
    assert d11.state == DataQualityState.PARTIAL


@pytest.mark.asyncio
async def test_inactive_or_mismatched_active_version_excludes_document() -> None:
    org_id = uuid4()
    period = resolve_reporting_period(_AS_OF)
    good, good_v, good_c = _eligible_bundle(version_label="good")
    missing_version_doc = _document(title="Missing Version")
    inactive_doc = _document(title="Inactive")
    inactive_v = _version(
        id=inactive_doc.active_version_id,
        document_id=inactive_doc.id,
        is_active=False,
    )
    wrong_doc = _document(title="Wrong Doc Link")
    wrong_v = _version(
        id=wrong_doc.active_version_id,
        document_id=uuid4(),  # attached to another document
        version="wrong",
    )
    future_doc = _document(title="Future Version")
    future_v = _version(
        id=future_doc.active_version_id,
        document_id=future_doc.id,
        uploaded_at=datetime(2026, 7, 1, tzinfo=UTC),
        created_at=datetime(2026, 7, 1, tzinfo=UTC),
    )
    empty_doc = _document(title="Empty Version")
    empty_v = _version(
        id=empty_doc.active_version_id,
        document_id=empty_doc.id,
        version="   ",
    )
    facts, evidence, issues, _, limitations = await load_knowledge_evidence(
        FakeSession(
            documents=[good, missing_version_doc, inactive_doc, wrong_doc, future_doc, empty_doc],
            versions=[good_v, inactive_v, wrong_v, future_v, empty_v],
            chunks=[
                good_c,
                _chunk(
                    document_id=missing_version_doc.id,
                    version_id=missing_version_doc.active_version_id,
                ),
                _chunk(document_id=inactive_doc.id, version_id=inactive_doc.active_version_id),
                _chunk(document_id=wrong_doc.id, version_id=wrong_doc.active_version_id),
                _chunk(document_id=future_doc.id, version_id=future_doc.active_version_id),
                _chunk(document_id=empty_doc.id, version_id=empty_doc.active_version_id),
            ],
            org_id=org_id,
        ),
        uuid4(),
        org_id,
        _PROJECT_NAME,
        period,
        visibility_mode=EvidenceVisibility.CLIENT_SAFE,
        role=AppRole.CLIENT,
    )
    assert [d.document_id for d in facts.documents] == [good.id]
    assert facts.documents[0].version == "good"
    assert all(c.document_id == good.id for c in facts.chunks)
    assert any("active version could not be validated" in item for item in limitations)
    assert any(
        i.source == "knowledge_versions" and i.state == DataQualityState.PARTIAL for i in issues
    )
    blob = str(facts.model_dump(mode="json")).lower()
    assert "missing version" not in blob
    assert "inactive" not in blob
    assert "secret.pdf" not in blob
    assert all(item.source_row_id != missing_version_doc.id for item in evidence)


@pytest.mark.asyncio
async def test_future_effective_and_upload_date_are_excluded() -> None:
    org_id = uuid4()
    period = resolve_reporting_period(_AS_OF)
    future_effective, fe_v, fe_c = _eligible_bundle(effective_date=date(2026, 7, 1))
    future_upload, fu_v, fu_c = _eligible_bundle(
        upload_date=datetime(2026, 7, 1, tzinfo=UTC), title="Future Upload"
    )
    good, good_v, good_c = _eligible_bundle()
    facts, _, _, _, _ = await load_knowledge_evidence(
        FakeSession(
            documents=[future_effective, future_upload, good],
            versions=[fe_v, fu_v, good_v],
            chunks=[fe_c, fu_c, good_c],
            org_id=org_id,
        ),
        uuid4(),
        org_id,
        _PROJECT_NAME,
        period,
        visibility_mode=EvidenceVisibility.CLIENT_SAFE,
        role=AppRole.CLIENT,
    )
    assert [d.document_id for d in facts.documents] == [good.id]
    assert all(c.document_id == good.id for c in facts.chunks)


@pytest.mark.asyncio
async def test_cross_pair_chunks_do_not_consume_bound_or_project() -> None:
    org_id = uuid4()
    period = resolve_reporting_period(_AS_OF)
    doc_a, ver_a, _ = _eligible_bundle(version_label="A")
    doc_b, ver_b, chunk_b = _eligible_bundle(version_label="B")
    # Cross-pair: document A with version B must never project.
    cross = _chunk(
        document_id=doc_a.id,
        version_id=doc_b.active_version_id,
        chunk_text="cross-pair leak",
        chunk_index=0,
    )
    valid = _chunk(
        document_id=doc_a.id,
        version_id=doc_a.active_version_id,
        chunk_text="valid-a",
        chunk_index=1,
    )
    facts, _, _, _, _ = await load_knowledge_evidence(
        FakeSession(
            documents=[doc_a, doc_b],
            versions=[ver_a, ver_b],
            chunks=[cross, chunk_b, valid],
            org_id=org_id,
        ),
        uuid4(),
        org_id,
        _PROJECT_NAME,
        period,
        visibility_mode=EvidenceVisibility.CLIENT_SAFE,
        role=AppRole.CLIENT,
    )
    texts = {c.untrusted_text for c in facts.chunks}
    assert "cross-pair leak" not in texts
    assert "valid-a" in texts
    assert chunk_b.chunk_text in texts
    by_id = {d.document_id: d.version for d in facts.documents}
    assert by_id[doc_a.id] == "A"
    assert by_id[doc_b.id] == "B"


@pytest.mark.asyncio
async def test_future_created_chunks_are_excluded() -> None:
    org_id = uuid4()
    period = resolve_reporting_period(_AS_OF)
    doc, version, past_chunk = _eligible_bundle()
    future_chunk = _chunk(
        document_id=doc.id,
        version_id=doc.active_version_id,
        chunk_text="future chunk",
        chunk_index=1,
        created_at=datetime(2026, 7, 1, tzinfo=UTC),
    )
    facts, _, _, _, _ = await load_knowledge_evidence(
        FakeSession(
            documents=[doc],
            versions=[version],
            chunks=[past_chunk, future_chunk],
            org_id=org_id,
        ),
        uuid4(),
        org_id,
        _PROJECT_NAME,
        period,
        visibility_mode=EvidenceVisibility.CLIENT_SAFE,
        role=AppRole.CLIENT,
    )
    assert [c.untrusted_text for c in facts.chunks] == [past_chunk.chunk_text]
    assert "future chunk" not in str(facts.model_dump(mode="json"))


@pytest.mark.asyncio
async def test_per_document_chunk_bound_before_global_projection() -> None:
    org_id = uuid4()
    period = resolve_reporting_period(_AS_OF)
    # Fixed IDs so document order is deterministic across runs.
    id_a = UUID("00000000-0000-4000-8000-00000000000a")
    id_b = UUID("00000000-0000-4000-8000-00000000000b")
    ver_a_id = UUID("00000000-0000-4000-8000-0000000000aa")
    ver_b_id = UUID("00000000-0000-4000-8000-0000000000bb")
    doc_a = _document(id=id_a, active_version_id=ver_a_id)
    doc_b = _document(id=id_b, active_version_id=ver_b_id)
    ver_a = _version(id=ver_a_id, document_id=id_a, version="A")
    ver_b = _version(id=ver_b_id, document_id=id_b, version="B")
    chunks_a = [
        _chunk(
            document_id=id_a,
            version_id=ver_a_id,
            chunk_index=i,
            chunk_text=f"a-{i}",
        )
        for i in range(5)
    ]
    chunks_b = [
        _chunk(
            document_id=id_b,
            version_id=ver_b_id,
            chunk_index=i,
            chunk_text=f"b-{i}",
        )
        for i in range(3)
    ]
    with (
        patch.object(knowledge_mod, "_MAX_CHUNKS_PER_DOCUMENT", 2),
        patch.object(knowledge_mod, "_MAX_CHUNKS", 10),
    ):
        facts, _, issues, _, limitations = await load_knowledge_evidence(
            FakeSession(
                documents=[doc_a, doc_b],
                versions=[ver_a, ver_b],
                chunks=[*chunks_a, *chunks_b],
                org_id=org_id,
            ),
            uuid4(),
            org_id,
            _PROJECT_NAME,
            period,
            visibility_mode=EvidenceVisibility.CLIENT_SAFE,
            role=AppRole.CLIENT,
        )
    by_doc = {}
    for chunk in facts.chunks:
        by_doc.setdefault(chunk.document_id, []).append(chunk.untrusted_text)
    assert by_doc[id_a] == ["a-0", "a-1"]
    assert by_doc[id_b] == ["b-0", "b-1"]
    assert any("per-document chunk bound" in item for item in limitations)
    assert any(i.state == DataQualityState.PARTIAL for i in issues if "chunk" in i.source)


@pytest.mark.asyncio
async def test_character_bounds_truncate_and_mark_partial() -> None:
    org_id = uuid4()
    period = resolve_reporting_period(_AS_OF)
    doc, version, _ = _eligible_bundle()
    long_chunk = _chunk(
        document_id=doc.id,
        version_id=doc.active_version_id,
        chunk_text="ABCDEFGHIJ",
        chunk_index=0,
    )
    next_chunk = _chunk(
        document_id=doc.id,
        version_id=doc.active_version_id,
        chunk_text="SECOND",
        chunk_index=1,
    )
    with (
        patch.object(knowledge_mod, "_MAX_CHARS_PER_CHUNK", 4),
        patch.object(knowledge_mod, "_MAX_TOTAL_UNTRUSTED_CHARS", 6),
    ):
        facts, _, issues, _, limitations = await load_knowledge_evidence(
            FakeSession(
                documents=[doc],
                versions=[version],
                chunks=[long_chunk, next_chunk],
                org_id=org_id,
            ),
            uuid4(),
            org_id,
            _PROJECT_NAME,
            period,
            visibility_mode=EvidenceVisibility.CLIENT_SAFE,
            role=AppRole.CLIENT,
        )
    assert len(facts.chunks) >= 1
    assert facts.chunks[0].untrusted_text == "ABCD"
    assert facts.chunks[0].content_sha256 == hashlib.sha256(b"ABCD").hexdigest()
    total = sum(len(c.untrusted_text) for c in facts.chunks)
    assert total <= 6
    assert any("character bound" in item.lower() for item in limitations)
    assert any(i.state == DataQualityState.PARTIAL for i in issues if "chunk" in i.source)


@pytest.mark.asyncio
async def test_inactive_version_chunks_are_excluded() -> None:
    org_id = uuid4()
    period = resolve_reporting_period(_AS_OF)
    doc, version, active = _eligible_bundle()
    stale = _chunk(document_id=doc.id, version_id=uuid4(), chunk_text="stale version")
    facts, _, _, _, _ = await load_knowledge_evidence(
        FakeSession(
            documents=[doc],
            versions=[version],
            chunks=[active, stale],
            org_id=org_id,
        ),
        uuid4(),
        org_id,
        _PROJECT_NAME,
        period,
        visibility_mode=EvidenceVisibility.CLIENT_SAFE,
        role=AppRole.CLIENT,
    )
    assert [c.untrusted_text for c in facts.chunks] == [active.chunk_text]
    assert "stale version" not in str(facts.model_dump(mode="json"))


@pytest.mark.asyncio
async def test_fingerprint_excludes_untrusted_text_and_titles() -> None:
    org_id = uuid4()
    period = resolve_reporting_period(_AS_OF)
    doc, version, chunk = _eligible_bundle()
    facts, evidence, _, _, _ = await load_knowledge_evidence(
        FakeSession(
            documents=[doc],
            versions=[version],
            chunks=[chunk],
            org_id=org_id,
        ),
        uuid4(),
        org_id,
        _PROJECT_NAME,
        period,
        visibility_mode=EvidenceVisibility.INTERNAL,
        role=AppRole.DELIVERY_MANAGER,
    )
    projection = _knowledge_fingerprint_projection(facts)
    assert "untrusted_text" not in str(projection)
    assert "document_title" not in str(projection)
    assert projection["chunks"][0]["content_sha256"] == facts.chunks[0].content_sha256
    project_id = uuid4()
    left = _fingerprint(
        project_id=project_id,
        reporting_period_start=period.start_date,
        reporting_period_end=period.end_date,
        visibility_mode=EvidenceVisibility.INTERNAL,
        evidence=evidence,
        knowledge_projection=projection,
    )
    mutated_sha = facts.model_copy(
        update={
            "chunks": [
                facts.chunks[0].model_copy(
                    update={
                        "untrusted_text": "other",
                        "content_sha256": hashlib.sha256(b"other").hexdigest(),
                    }
                )
            ]
        }
    )
    right = _fingerprint(
        project_id=project_id,
        reporting_period_start=period.start_date,
        reporting_period_end=period.end_date,
        visibility_mode=EvidenceVisibility.INTERNAL,
        evidence=evidence,
        knowledge_projection=_knowledge_fingerprint_projection(mutated_sha),
    )
    assert left != right


@pytest.mark.asyncio
async def test_auth_runs_before_knowledge_queries() -> None:
    project = _project()
    user = _user(AppRole.CLIENT, project.org_id)
    session = FakeSession()
    with (
        patch(
            "app.agents.client_intelligence.evidence_pack.get_visible_project",
            new=AsyncMock(side_effect=ApiError(404, "NOT_FOUND", "Project not found")),
        ),
        pytest.raises(ApiError),
    ):
        await build_client_evidence_pack(session, user, project.id, as_of=_AS_OF)
    assert session.statements == []


@pytest.mark.asyncio
async def test_pack_includes_knowledge_section() -> None:
    project = _project()
    user = _user(AppRole.CLIENT, project.org_id)
    doc, version, chunk = _eligible_bundle()
    session = FakeSession(
        documents=[doc],
        versions=[version],
        chunks=[chunk],
        org_id=project.org_id,
    )
    with patch(
        "app.agents.client_intelligence.evidence_pack.get_visible_project",
        new=AsyncMock(return_value=project),
    ):
        pack = await build_client_evidence_pack(
            session,
            user,
            project.id,
            as_of=_AS_OF,
            visibility_mode=EvidenceVisibility.CLIENT_SAFE,
        )
    assert pack.knowledge.documents
    assert pack.knowledge.chunks
    assert any(item.requirement_id == "CI-D14" for item in pack.knowledge.source_availability)
    assert pack.knowledge.documents[0].document_title is None
