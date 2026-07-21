"""DEVELOPMENT_PLAN.md Workstream F (closes F6): audit-export endpoints for
regulated-domain clients (13. Security & Compliance.md §11.4). Distinct from
the general-purpose /agent-queries and /projects/{id}/communications routes:
those serve the app UI (scoped to what a user should see day-to-day); these
serve a compliance export request (delivery_manager's own org, or
super_admin across all orgs), with no status filtering -- the whole
lifecycle, drafts included.
"""

from sqlalchemy import func, select

from fastapi import APIRouter, Depends, Query

from app.api.deps import SessionDep
from app.core.security import CurrentUser, require_role
from app.db.models import AgentQuery, AppRole, ClientCommunication
from app.schemas.common import ListResponse, Pagination
from app.schemas.domain import AgentQueryRead, CommunicationRead

router = APIRouter(tags=["admin audit export"])

EXPORT_ROLES = (AppRole.DELIVERY_MANAGER, AppRole.SUPER_ADMIN)


def _pagination(*, total: int, limit: int, offset: int, item_count: int) -> Pagination:
    return Pagination(limit=limit, offset=offset, total=total, items=item_count, has_more=offset + item_count < total)


@router.get("/admin/audit/agent-queries", response_model=ListResponse[AgentQueryRead])
async def export_agent_queries(
    session: SessionDep,
    current_user: CurrentUser = Depends(require_role(*EXPORT_ROLES)),
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
) -> ListResponse[AgentQueryRead]:
    stmt = select(AgentQuery)
    count_stmt = select(func.count()).select_from(AgentQuery)
    if current_user.role != AppRole.SUPER_ADMIN:
        stmt = stmt.where(AgentQuery.org_id == current_user.org_id)
        count_stmt = count_stmt.where(AgentQuery.org_id == current_user.org_id)
    stmt = stmt.order_by(AgentQuery.created_at.desc()).limit(limit).offset(offset)

    rows = list((await session.execute(stmt)).scalars())
    total = (await session.execute(count_stmt)).scalar_one_or_none() or 0
    return ListResponse(
        data=[AgentQueryRead.model_validate(row) for row in rows],
        pagination=_pagination(total=total, limit=limit, offset=offset, item_count=len(rows)),
    )


@router.get("/admin/audit/communications", response_model=ListResponse[CommunicationRead])
async def export_communications(
    session: SessionDep,
    current_user: CurrentUser = Depends(require_role(*EXPORT_ROLES)),
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
) -> ListResponse[CommunicationRead]:
    """Full lifecycle export -- unlike the client-facing and project-scoped
    /projects/{id}/communications route, this deliberately does not filter by
    status: drafts, approvals, and rejections are all part of the audit
    trail per 13. Security & Compliance.md §11.4."""
    stmt = select(ClientCommunication)
    count_stmt = select(func.count()).select_from(ClientCommunication)
    if current_user.role != AppRole.SUPER_ADMIN:
        stmt = stmt.where(ClientCommunication.org_id == current_user.org_id)
        count_stmt = count_stmt.where(ClientCommunication.org_id == current_user.org_id)
    stmt = stmt.order_by(ClientCommunication.created_at.desc()).limit(limit).offset(offset)

    rows = list((await session.execute(stmt)).scalars())
    total = (await session.execute(count_stmt)).scalar_one_or_none() or 0
    return ListResponse(
        data=[CommunicationRead.model_validate(row) for row in rows],
        pagination=_pagination(total=total, limit=limit, offset=offset, item_count=len(rows)),
    )
