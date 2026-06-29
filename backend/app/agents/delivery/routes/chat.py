"""Delivery Agent chat route."""

from fastapi import APIRouter

from app.agents.delivery.schemas.chat_schema import DeliveryChatCreate, DeliveryChatRead
from app.agents.delivery.services.chat_service import answer_delivery_chat
from app.api.deps import SessionDep, UserDep
from app.schemas.common import DataResponse

router = APIRouter(tags=["delivery"])


@router.post("/delivery/chat", response_model=DataResponse[DeliveryChatRead])
async def delivery_chat(
    payload: DeliveryChatCreate,
    session: SessionDep,
    current_user: UserDep,
) -> DataResponse[DeliveryChatRead]:
    """Answer delivery operations questions using live performance data."""
    result = await answer_delivery_chat(
        session,
        current_user,
        message=payload.message,
        project_id=payload.project_id,
        conversation_id=payload.conversation_id,
    )
    await session.commit()
    return DataResponse(data=result)
