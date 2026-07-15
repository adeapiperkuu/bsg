"""Knowledge Agent integration for Project Governance (charters and approved docs only)."""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.governance.schemas.governance import (
    GovernanceKnowledgeDocumentRef,
)
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
            KnowledgeVisibility.RESTRICTED,
            KnowledgeVisibility.CLIENT_SAFE,
        ]
    if current_user.role == AppRole.SUPER_ADMIN:
        return [
            KnowledgeVisibility.INTERNAL_ONLY,
            KnowledgeVisibility.LEADERSHIP_ONLY,
            KnowledgeVisibility.RESTRICTED,
            KnowledgeVisibility.CLIENT_SAFE,
        ]
    return [
        KnowledgeVisibility.INTERNAL_ONLY,
        KnowledgeVisibility.CLIENT_SAFE,
    ]


_GOVERNANCE_DOC_SOURCE_TYPES = (
    KnowledgeSourceType.PROJECT_CHARTER,
    KnowledgeSourceType.ESCALATION_NOTE,
    KnowledgeSourceType.GUIDE,
    KnowledgeSourceType.SOP,
    KnowledgeSourceType.TRAINING_DOCUMENT,
)


async def list_approved_governance_document_refs(
    session: AsyncSession,
    current_user: CurrentUser,
) -> list[GovernanceKnowledgeDocumentRef]:
    """Approved governance-related knowledge documents (read-only from Knowledge Agent)."""
    allowed_visibility = _charter_visibility_filter(current_user)
    rows = (
        (
            await session.execute(
                select(KnowledgeDocument)
                .where(
                    KnowledgeDocument.org_id == current_user.org_id,
                    KnowledgeDocument.deleted_at.is_(None),
                    KnowledgeDocument.status == KnowledgeDocumentStatus.APPROVED,
                    KnowledgeDocument.source_type.in_(_GOVERNANCE_DOC_SOURCE_TYPES),
                    KnowledgeDocument.visibility.in_(allowed_visibility),
                )
                .order_by(KnowledgeDocument.updated_at.desc())
            )
        )
        .scalars()
        .all()
    )
    return [
        GovernanceKnowledgeDocumentRef(
            document_id=doc.id,
            title=doc.title,
            project=doc.project,
            department=doc.department,
            version=doc.version,
            status=doc.status.value,
            visibility=doc.visibility.value,
            source_type=doc.source_type.value,
        )
        for doc in rows
        if can_access_visibility(current_user.role, doc.visibility)
    ]
