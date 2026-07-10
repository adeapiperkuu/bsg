from __future__ import annotations

from datetime import date
from types import SimpleNamespace
from uuid import uuid4

import pytest

from app.core.exceptions import ApiError
from app.db.models.entities import (
    AppRole,
    KnowledgeDocument,
    KnowledgeDocumentStatus,
    KnowledgeFolder,
    KnowledgeFolderKind,
    KnowledgeIndexingStatus,
    KnowledgeProcessingStatus,
    KnowledgeSourceType,
    KnowledgeVisibility,
)
from app.schemas.domain import KnowledgeDocumentLifecycleAction, KnowledgeDocumentUpdate
from app.services.knowledge.library import (
    APPROVE_STATUSES,
    SUBMIT_STATUSES,
    _require_transition,
    approve_document,
    reject_document,
    submit_document_for_review,
    update_document,
)
from app.services.knowledge.permissions import can_access_visibility
from app.services.knowledge.ingestion import create_document_from_upload
from tests.knowledge_fixtures import make_current_user


def _doc(
    *,
    org_id=None,
    status: KnowledgeDocumentStatus = KnowledgeDocumentStatus.DRAFT,
    visibility: KnowledgeVisibility = KnowledgeVisibility.INTERNAL_ONLY,
    submitted_by=None,
) -> KnowledgeDocument:
    return KnowledgeDocument(
        id=uuid4(),
        org_id=org_id or uuid4(),
        folder_id=uuid4(),
        title="Governance SOP",
        source_type=KnowledgeSourceType.SOP,
        version="v1.0",
        visibility=visibility,
        status=status,
        owner_approver="Ops Lead",
        effective_date=date(2026, 1, 1),
        file_name="governance.md",
        file_mime_type="text/markdown",
        processing_status=KnowledgeProcessingStatus.READY,
        indexing_status=KnowledgeIndexingStatus.INDEXED,
        submitted_by=submitted_by,
    )


def _folder(doc: KnowledgeDocument) -> KnowledgeFolder:
    return KnowledgeFolder(
        id=doc.folder_id,
        org_id=doc.org_id,
        name="SOPs",
        folder_kind=KnowledgeFolderKind.SOPS,
        display_order=0,
    )


class _ScalarResult:
    def __init__(self, value):
        self._value = value

    def scalar_one(self):
        return self._value

    def scalar_one_or_none(self):
        return self._value


class _LifecycleSession:
    def __init__(self, doc: KnowledgeDocument, folder: KnowledgeFolder):
        self.doc = doc
        self.folder = folder
        self.added = []
        self.flushed = False

    async def execute(self, stmt):
        return _ScalarResult(self.folder)

    def add(self, item):
        self.added.append(item)

    async def flush(self):
        self.flushed = True
        for item in self.added:
            if getattr(item, "id", None) is None:
                item.id = uuid4()


@pytest.mark.asyncio
async def test_submit_approve_logs_approval_events(monkeypatch: pytest.MonkeyPatch, knowledge_users) -> None:
    dm = knowledge_users["delivery_manager"]
    lead = knowledge_users["leadership"]
    doc = _doc(org_id=dm.org_id)
    folder = _folder(doc)
    session = _LifecycleSession(doc, folder)

    async def _get_doc(_session, org_id, document_id):
        assert org_id == dm.org_id
        assert document_id == doc.id
        return doc

    async def _to_read(_session, document, folder_row):
        return SimpleNamespace(
            id=document.id,
            status=document.status.value,
            folder_id=folder_row.id,
        )

    monkeypatch.setattr("app.services.knowledge.library._get_document_or_404", _get_doc)
    monkeypatch.setattr("app.services.knowledge.library._to_document_read", _to_read)

    submitted = await submit_document_for_review(session, dm, doc.id)
    assert submitted.status == "submitted_for_review"
    assert doc.status == KnowledgeDocumentStatus.SUBMITTED_FOR_REVIEW
    assert doc.submitted_by == dm.id
    assert len(session.added) == 1
    assert session.added[0].action == "submit"

    approved = await approve_document(session, lead, doc.id)
    assert approved.status == "approved"
    assert doc.status == KnowledgeDocumentStatus.APPROVED
    assert doc.reviewed_by == lead.id
    assert len(session.added) == 2
    assert session.added[1].action == "approve"


@pytest.mark.asyncio
async def test_reject_and_invalid_transition(monkeypatch: pytest.MonkeyPatch, knowledge_users) -> None:
    lead = knowledge_users["leadership"]
    doc = _doc(org_id=lead.org_id, status=KnowledgeDocumentStatus.SUBMITTED_FOR_REVIEW)
    folder = _folder(doc)
    session = _LifecycleSession(doc, folder)

    async def _get_doc(_session, org_id, document_id):
        return doc

    async def _to_read(_session, document, folder_row):
        return SimpleNamespace(id=document.id, status=document.status.value)

    monkeypatch.setattr("app.services.knowledge.library._get_document_or_404", _get_doc)
    monkeypatch.setattr("app.services.knowledge.library._to_document_read", _to_read)

    rejected = await reject_document(
        session,
        lead,
        doc.id,
        KnowledgeDocumentLifecycleAction(rejection_reason="Missing owner section"),
    )
    assert rejected.status == "rejected"
    assert doc.rejection_reason == "Missing owner section"

    with pytest.raises(ApiError) as exc:
        await approve_document(session, lead, doc.id)
    assert exc.value.status_code == 409
    assert exc.value.code == "INVALID_LIFECYCLE_TRANSITION"


@pytest.mark.asyncio
async def test_delivery_manager_cannot_approve(monkeypatch: pytest.MonkeyPatch, knowledge_users) -> None:
    dm = knowledge_users["delivery_manager"]
    doc = _doc(org_id=dm.org_id, status=KnowledgeDocumentStatus.SUBMITTED_FOR_REVIEW)
    session = _LifecycleSession(doc, _folder(doc))

    async def _get_doc(_session, org_id, document_id):
        return doc

    monkeypatch.setattr("app.services.knowledge.library._get_document_or_404", _get_doc)

    with pytest.raises(ApiError) as exc:
        await approve_document(session, dm, doc.id)
    assert exc.value.status_code == 403


@pytest.mark.asyncio
async def test_patch_cannot_set_approved_status(monkeypatch: pytest.MonkeyPatch, knowledge_users) -> None:
    dm = knowledge_users["delivery_manager"]
    doc = _doc(org_id=dm.org_id, status=KnowledgeDocumentStatus.DRAFT)
    folder = _folder(doc)
    session = _LifecycleSession(doc, folder)

    async def _get_doc(_session, org_id, document_id):
        return doc

    async def _to_read(_session, document, folder_row):
        return SimpleNamespace(id=document.id, status=document.status.value)

    async def _notify(*_args, **_kwargs):
        return None

    monkeypatch.setattr("app.services.knowledge.library._get_document_or_404", _get_doc)
    monkeypatch.setattr("app.services.knowledge.library._to_document_read", _to_read)
    monkeypatch.setattr("app.services.knowledge.library._notify_knowledge_stakeholders", _notify)
    monkeypatch.setattr("app.services.knowledge.library._invalidate_knowledge_answer_cache", lambda *_: None)

    # KnowledgeDocumentUpdate no longer accepts status; content-only patch keeps draft.
    updated = await update_document(
        session,
        dm,
        doc.id,
        KnowledgeDocumentUpdate(title="Renamed SOP"),
    )
    assert updated.status == "draft"
    assert doc.status == KnowledgeDocumentStatus.DRAFT
    assert "status" not in KnowledgeDocumentUpdate.model_fields


@pytest.mark.asyncio
async def test_upload_rejects_non_draft_status(monkeypatch: pytest.MonkeyPatch, knowledge_users) -> None:
    dm = knowledge_users["delivery_manager"]
    session = SimpleNamespace()

    with pytest.raises(ApiError) as exc:
        await create_document_from_upload(
            session,
            dm,
            folder_id=uuid4(),
            folder_kind=None,
            title="Upload SOP",
            source_type=KnowledgeSourceType.SOP,
            version="v1.0",
            visibility=KnowledgeVisibility.INTERNAL_ONLY,
            status=KnowledgeDocumentStatus.APPROVED,
            owner_approver="Ops Lead",
            description=None,
            approver=None,
            project=None,
            department=None,
            effective_date=date(2026, 1, 1),
            file_name="upload.md",
            file_mime_type="text/markdown",
            file_bytes=b"hello",
        )
    assert exc.value.status_code == 400
    assert "draft" in exc.value.message.lower()


def test_restricted_visibility_excludes_delivery_manager(knowledge_users) -> None:
    dm = knowledge_users["delivery_manager"]
    lead = knowledge_users["leadership"]
    assert can_access_visibility(dm.role, KnowledgeVisibility.RESTRICTED) is False
    assert can_access_visibility(lead.role, KnowledgeVisibility.RESTRICTED) is True
    assert can_access_visibility(AppRole.CLIENT, KnowledgeVisibility.RESTRICTED) is False


def test_require_transition_allows_submit_from_draft() -> None:
    doc = _doc(status=KnowledgeDocumentStatus.DRAFT)
    previous = _require_transition(doc, SUBMIT_STATUSES, action="submit")
    assert previous == KnowledgeDocumentStatus.DRAFT


def test_require_transition_blocks_approve_from_draft() -> None:
    doc = _doc(status=KnowledgeDocumentStatus.DRAFT)
    with pytest.raises(ApiError) as exc:
        _require_transition(doc, APPROVE_STATUSES, action="approve")
    assert exc.value.status_code == 409


@pytest.mark.asyncio
async def test_separation_of_duties_blocks_submitter_approve(
    monkeypatch: pytest.MonkeyPatch,
    knowledge_users,
) -> None:
    lead = knowledge_users["leadership"]
    doc = _doc(
        org_id=lead.org_id,
        status=KnowledgeDocumentStatus.SUBMITTED_FOR_REVIEW,
        submitted_by=lead.id,
    )
    session = _LifecycleSession(doc, _folder(doc))

    async def _get_doc(_session, org_id, document_id):
        return doc

    monkeypatch.setattr("app.services.knowledge.library._get_document_or_404", _get_doc)
    monkeypatch.setattr(
        "app.services.knowledge.library.get_settings",
        lambda: SimpleNamespace(knowledge_separation_of_duties=True),
    )

    with pytest.raises(ApiError) as exc:
        await approve_document(session, lead, doc.id)
    assert exc.value.status_code == 409
    assert exc.value.code == "SEPARATION_OF_DUTIES"
