from fastapi import APIRouter, Depends, Query

from app.api.deps import SessionDep
from app.core.security import require_role
from app.db.models import AppRole
from app.schemas.common import DataResponse, ListResponse, Pagination
from app.schemas.domain import KnowledgeLessonCreate, KnowledgeLessonRead, KnowledgeSearchResult
from app.services.knowledge import create_lesson, list_lessons, search_knowledge

router = APIRouter(tags=["knowledge"])


@router.get("/knowledge/lessons", response_model=ListResponse[KnowledgeLessonRead])
async def get_lessons(
    session: SessionDep,
    current_user=Depends(require_role(AppRole.DELIVERY_MANAGER, AppRole.BSG_LEADERSHIP, AppRole.SUPER_ADMIN)),
) -> ListResponse[KnowledgeLessonRead]:
    rows = await list_lessons(session, current_user.org_id)
    return ListResponse(
        data=[KnowledgeLessonRead.model_validate(row) for row in rows],
        pagination=Pagination(limit=50),
    )


@router.post("/knowledge/lessons", response_model=DataResponse[KnowledgeLessonRead])
async def post_lesson(
    payload: KnowledgeLessonCreate,
    session: SessionDep,
    current_user=Depends(require_role(AppRole.DELIVERY_MANAGER, AppRole.SUPER_ADMIN)),
) -> DataResponse[KnowledgeLessonRead]:
    lesson = await create_lesson(session, current_user.org_id, payload, current_user.id)
    await session.commit()
    await session.refresh(lesson)
    return DataResponse(data=KnowledgeLessonRead.model_validate(lesson))


@router.get("/knowledge/search", response_model=ListResponse[KnowledgeSearchResult])
async def search_knowledge_route(
    session: SessionDep,
    current_user=Depends(require_role(AppRole.DELIVERY_MANAGER, AppRole.BSG_LEADERSHIP, AppRole.SUPER_ADMIN)),
    q: str = Query(default="", min_length=0),
) -> ListResponse[KnowledgeSearchResult]:
    results = await search_knowledge(session, current_user.org_id, q)
    return ListResponse(data=results, pagination=Pagination(limit=20))
