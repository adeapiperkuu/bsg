"""Knowledge Agent integration for Project Governance (charters and approved docs only)."""

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.governance.schemas.governance import GovernanceCharterReferenceRead
from app.core.security import CurrentUser
from app.db.models import AppRole, KnowledgeDocument
from app.db.models.entities import KnowledgeDocumentStatus, KnowledgeSourceType, KnowledgeVisibility
from app.services.knowledge import can_access_visibility


def _charter_visibility_filter(current_user: CurrentUser) -> list[KnowledgeVisibility]:
    if current_user.role == AppRole.CLIENT:
        return [KnowledgeVisibility.CLIENT_SAFE]
    if current_user.role == AppRole.BSG_LEADERSHIP:
        return [
            KnowledgeVisibility.INTERNAL_ONLY,
            KnowledgeVisibility.LEADERSHIP_ONLY,
            KnowledgeVisibility.CLIENT_SAFE,
        ]
    return [
        KnowledgeVisibility.INTERNAL_ONLY,
        KnowledgeVisibility.CLIENT_SAFE,
    ]


async def list_approved_charter_references(
    session: AsyncSession,
    current_user: CurrentUser,
    *,
    project_name: str | None = None,
) -> list[GovernanceCharterReferenceRead]:
    """Fetch approved project charter documents from the Operational Knowledge Agent store."""
    allowed_visibility = _charter_visibility_filter(current_user)
    filters = [
        KnowledgeDocument.org_id == current_user.org_id,
        KnowledgeDocument.deleted_at.is_(None),
        KnowledgeDocument.status == KnowledgeDocumentStatus.APPROVED,
        KnowledgeDocument.source_type == KnowledgeSourceType.PROJECT_CHARTER,
        KnowledgeDocument.visibility.in_(allowed_visibility),
    ]
    if project_name:
        filters.append(KnowledgeDocument.project == project_name)

    rows = (
        (
            await session.execute(
                select(KnowledgeDocument)
                .where(*filters)
                .order_by(KnowledgeDocument.updated_at.desc())
            )
        )
        .scalars()
        .all()
    )

    return [
        GovernanceCharterReferenceRead(
            document_id=doc.id,
            title=doc.title,
            project=doc.project,
            version=doc.version,
            status=doc.status.value,
            visibility=doc.visibility.value,
        )
        for doc in rows
        if can_access_visibility(current_user.role, doc.visibility)
    ]


async def get_charter_reference(
    session: AsyncSession,
    current_user: CurrentUser,
    document_id: UUID,
) -> GovernanceCharterReferenceRead | None:
    doc = (
        await session.execute(
            select(KnowledgeDocument).where(
                KnowledgeDocument.id == document_id,
                KnowledgeDocument.org_id == current_user.org_id,
                KnowledgeDocument.deleted_at.is_(None),
                KnowledgeDocument.status == KnowledgeDocumentStatus.APPROVED,
                KnowledgeDocument.source_type == KnowledgeSourceType.PROJECT_CHARTER,
            )
        )
    ).scalar_one_or_none()
    if doc is None or not can_access_visibility(current_user.role, doc.visibility):
        return None
    return GovernanceCharterReferenceRead(
        document_id=doc.id,
        title=doc.title,
        project=doc.project,
        version=doc.version,
        status=doc.status.value,
        visibility=doc.visibility.value,
    )
