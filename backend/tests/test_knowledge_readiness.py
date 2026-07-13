from datetime import date, datetime, timedelta, timezone
from uuid import uuid4

from app.db.models.entities import (
    KnowledgeDocument,
    KnowledgeDocumentStatus,
    KnowledgeFolderKind,
    KnowledgeIndexingStatus,
    KnowledgeProcessingStatus,
    KnowledgeSourceType,
    KnowledgeVisibility,
)
from app.services.knowledge import (
    assess_retrieval_readiness,
    compute_library_readiness_counts,
    _filter_retrieval_ready_docs,
    _is_retrieval_ready,
)


def _doc(
    *,
    status: KnowledgeDocumentStatus = KnowledgeDocumentStatus.APPROVED,
    processing_status: KnowledgeProcessingStatus = KnowledgeProcessingStatus.READY,
    indexing_status: KnowledgeIndexingStatus = KnowledgeIndexingStatus.INDEXED,
    owner_approver: str = "Ops Lead",
    effective_date: date | None = date(2025, 1, 1),
    approved_at: datetime | None = None,
    source_type: KnowledgeSourceType = KnowledgeSourceType.GUIDE,
    org_id=None,
) -> KnowledgeDocument:
    org = org_id or uuid4()
    return KnowledgeDocument(
        id=uuid4(),
        org_id=org,
        folder_id=uuid4(),
        title="Escalation SOP",
        source_type=source_type,
        version="v1.0",
        visibility=KnowledgeVisibility.INTERNAL_ONLY,
        status=status,
        owner_approver=owner_approver,
        effective_date=effective_date,
        file_name="escalation.md",
        file_mime_type="text/markdown",
        processing_status=processing_status,
        indexing_status=indexing_status,
        approved_at=approved_at,
    )


def test_approved_ready_indexed_document_is_retrievable() -> None:
    doc = _doc()
    assessment = assess_retrieval_readiness(doc, org_id=doc.org_id)

    assert assessment.is_ready is True
    assert assessment.reason == "Ready"
    assert assessment.action is None
    assert _is_retrieval_ready(doc, org_id=doc.org_id) is True


def test_draft_document_is_excluded() -> None:
    doc = _doc(status=KnowledgeDocumentStatus.DRAFT)
    assessment = assess_retrieval_readiness(doc, org_id=doc.org_id)

    assert assessment.is_ready is False
    assert assessment.reason == "Needs approval"
    assert assessment.action == "approve"
    assert _filter_retrieval_ready_docs([doc], doc.org_id) == []


def test_needs_reindex_document_is_excluded() -> None:
    doc = _doc(indexing_status=KnowledgeIndexingStatus.NOT_INDEXED)
    assessment = assess_retrieval_readiness(doc, org_id=doc.org_id)

    assert assessment.is_ready is False
    assert assessment.reason == "Needs re-index"
    assert assessment.action == "reindex"


def test_failed_document_is_excluded() -> None:
    doc = _doc(
        processing_status=KnowledgeProcessingStatus.FAILED,
        indexing_status=KnowledgeIndexingStatus.FAILED,
    )
    assessment = assess_retrieval_readiness(doc, org_id=doc.org_id)

    assert assessment.is_ready is False
    assert assessment.reason == "Processing failed"
    assert assessment.action == "retry_processing"


def test_expired_document_is_excluded() -> None:
    doc = _doc(
        source_type=KnowledgeSourceType.SOP,
        effective_date=None,
        approved_at=datetime.now(timezone.utc) - timedelta(days=400),
    )
    assessment = assess_retrieval_readiness(doc, org_id=doc.org_id)

    assert assessment.is_ready is False
    assert assessment.reason == "Expired"
    assert assessment.action == "edit_metadata"


def test_missing_metadata_document_is_excluded() -> None:
    missing_owner = _doc(owner_approver="   ")
    missing_date = _doc(effective_date=None)

    assert assess_retrieval_readiness(missing_owner, org_id=missing_owner.org_id).reason == "Missing owner"
    assert assess_retrieval_readiness(missing_date, org_id=missing_date.org_id).reason == "Missing effective date"


def test_readiness_counts_are_correct() -> None:
    org_id = uuid4()
    docs = [
        _doc(org_id=org_id),
        _doc(org_id=org_id, status=KnowledgeDocumentStatus.DRAFT),
        _doc(org_id=org_id, indexing_status=KnowledgeIndexingStatus.NOT_INDEXED),
        _doc(
            org_id=org_id,
            processing_status=KnowledgeProcessingStatus.FAILED,
            indexing_status=KnowledgeIndexingStatus.FAILED,
        ),
        _doc(
            org_id=org_id,
            source_type=KnowledgeSourceType.SOP,
            effective_date=None,
            approved_at=datetime.now(timezone.utc) - timedelta(days=400),
        ),
        _doc(org_id=org_id, owner_approver="", effective_date=None),
    ]

    counts = compute_library_readiness_counts(docs, org_id=org_id)

    assert counts.ready_for_retrieval_count == 1
    assert counts.approved_and_indexed_count == 3
    assert counts.needs_review_count >= 1
    assert counts.needs_reindex_count >= 1
    assert counts.failed_processing_count == 1
    assert counts.expired_count == 1
    assert counts.missing_metadata_count >= 1
