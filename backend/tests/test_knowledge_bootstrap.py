import json
from datetime import UTC, datetime
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest

from app.core.security import CurrentUser
from app.db.models import AppRole
from app.db.models.entities import (
    KnowledgeDocument,
    KnowledgeDocumentStatus,
    KnowledgeFolder,
    KnowledgeFolderKind,
    KnowledgeIndexingStatus,
    KnowledgeProcessingStatus,
    KnowledgeSourceType,
    KnowledgeVisibility,
)
from app.schemas.domain import (
    KnowledgeBootstrapRead,
    KnowledgeDocumentCountsRead,
    KnowledgeDocumentSummaryRead,
    KnowledgeFolderRead,
    KnowledgeFolderTreeNodeRead,
    KnowledgeLibraryHealthCountsRead,
    KnowledgePermissionsRead,
)
from app.services.knowledge import BOOTSTRAP_RECENT_DOCUMENT_LIMIT, get_knowledge_bootstrap


@pytest.mark.asyncio
async def test_bootstrap_returns_lightweight_payload_only() -> None:
    org_id = uuid4()
    folder_id = uuid4()
    doc_id = uuid4()
    folder = KnowledgeFolder(
        id=folder_id,
        org_id=org_id,
        name="SOPs",
        folder_kind=KnowledgeFolderKind.SOPS,
        display_order=0,
    )
    summary = KnowledgeDocumentSummaryRead(
        id=doc_id,
        folder_id=folder_id,
        folder_name="SOPs",
        folder_kind="sops",
        title="Escalation SOP",
        source_type="sop",
        version="v1.0",
        visibility="internal_only",
        status="approved",
        owner_approver="Ops Lead",
        effective_date=None,
        file_name="escalation.pdf",
        processing_status="ready",
        processing_error=None,
        indexing_status="indexed",
        workflow_state="approved",
        updated_at=datetime.now(UTC),
    )
    bootstrap = KnowledgeBootstrapRead(
        folders=[
            KnowledgeFolderRead(
                id=folder_id,
                name="SOPs",
                folder_kind="sops",
                display_order=0,
            )
        ],
        folder_tree=[
            KnowledgeFolderTreeNodeRead(
                id=folder_id,
                name="SOPs",
                folder_kind="sops",
                display_order=0,
                document_count=1,
            )
        ],
        recent_documents=[summary],
        document_counts=KnowledgeDocumentCountsRead(total=1, by_folder_id={str(folder_id): 1}),
        permissions=KnowledgePermissionsRead(
            can_upload=True,
            can_manage_eval=False,
            can_adjust_retrieval_scope=False,
            can_resolve_gaps=True,
        ),
        library_health=KnowledgeLibraryHealthCountsRead(ready_count=1),
    )

    payload = json.loads(bootstrap.model_dump_json())
    assert "documents" not in payload
    assert payload["recent_documents"][0]["title"] == "Escalation SOP"
    assert "chunks" not in payload["recent_documents"][0]
    assert "preview" not in payload["recent_documents"][0]
    assert "quality_score" not in payload["recent_documents"][0]
    assert "open_gaps" not in payload["library_health"]
    assert payload["permissions"]["can_upload"] is True
    assert payload["folder_tree"][0]["document_count"] == 1


@pytest.mark.asyncio
async def test_get_knowledge_bootstrap_limits_recent_documents() -> None:
    from datetime import timedelta

    org_id = uuid4()
    folder_id = uuid4()
    folder = KnowledgeFolder(
        id=folder_id,
        org_id=org_id,
        name="Guides",
        folder_kind=KnowledgeFolderKind.GUIDES,
        display_order=1,
    )
    now = datetime.now(UTC)
    docs = [
        KnowledgeDocument(
            id=uuid4(),
            org_id=org_id,
            folder_id=folder_id,
            title=f"Doc {index}",
            source_type=KnowledgeSourceType.GUIDE,
            version="v1.0",
            visibility=KnowledgeVisibility.INTERNAL_ONLY,
            status=KnowledgeDocumentStatus.APPROVED,
            owner_approver="Owner",
            file_name=f"doc-{index}.md",
            file_mime_type="text/markdown",
            processing_status=KnowledgeProcessingStatus.READY,
            indexing_status=KnowledgeIndexingStatus.INDEXED,
            created_at=now - timedelta(days=index),
            updated_at=now - timedelta(days=index),
        )
        for index in range(40)
    ]
    current_user = CurrentUser(
        id=uuid4(),
        org_id=org_id,
        role=AppRole.DELIVERY_MANAGER,
        email="pm@example.com",
        is_active=True,
    )
    session = AsyncMock()

    with (
        patch("app.services.knowledge.ensure_knowledge_folders", new_callable=AsyncMock),
        patch("app.services.knowledge.list_knowledge_folders", new_callable=AsyncMock, return_value=[folder]),
        patch(
            "app.services.knowledge._list_visible_documents_with_folders",
            new_callable=AsyncMock,
            return_value=(docs, {folder_id: folder}),
        ),
    ):
        result = await get_knowledge_bootstrap(session, current_user)

    assert len(result.recent_documents) == BOOTSTRAP_RECENT_DOCUMENT_LIMIT
    assert result.document_counts.total == 40
    assert result.library_health.ready_count == 40
    assert all("chunk" not in doc.model_dump() for doc in result.recent_documents)
