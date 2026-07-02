"""Delivery Agent chat routes."""

from uuid import UUID

from fastapi import APIRouter
from fastapi.responses import StreamingResponse

from app.agents.delivery.schemas.chat_schema import (
    DeliveryChatConversationRead,
    DeliveryChatCreate,
    DeliveryChatRead,
)
from app.agents.delivery.services.chat_service import (
    answer_delivery_chat,
    load_delivery_chat_conversation,
    stream_delivery_chat,
)
from app.api.deps import SessionDep, UserDep
from app.core.config import get_settings
from app.core.exceptions import ApiError
from app.core.rate_limit import SlidingWindowRateLimiter
from app.core.security import CurrentUser
from app.schemas.common import DataResponse

router = APIRouter(tags=["delivery"])

# Module-level singleton: counters must persist across requests within this process.
_rate_limiter = SlidingWindowRateLimiter()


def _enforce_delivery_chat_rate_limit(current_user: CurrentUser) -> None:
    settings = get_settings()
    _rate_limiter.check(
        f"delivery_chat:user:{current_user.id}",
        limit=settings.delivery_chat_user_rate_limit_per_minute,
    )
    _rate_limiter.check(
        f"delivery_chat:org:{current_user.org_id}",
        limit=settings.delivery_chat_org_rate_limit_per_minute,
    )


@router.post("/delivery/chat", response_model=DataResponse[DeliveryChatRead])
async def delivery_chat(
    payload: DeliveryChatCreate,
    session: SessionDep,
    current_user: UserDep,
) -> DataResponse[DeliveryChatRead]:
    """Answer delivery operations questions using live performance data."""
    _enforce_delivery_chat_rate_limit(current_user)
    result = await answer_delivery_chat(
        session,
        current_user,
        message=payload.message,
        project_id=payload.project_id,
        conversation_id=payload.conversation_id,
    )
    await session.commit()
    return DataResponse(data=result)


@router.post("/delivery/chat/stream")
async def delivery_chat_stream(
    payload: DeliveryChatCreate,
    session: SessionDep,
    current_user: UserDep,
) -> StreamingResponse:
    """Streaming counterpart to /delivery/chat — emits SSE `delta` and `done` events."""
    _enforce_delivery_chat_rate_limit(current_user)

    async def _generate():
        async for chunk in stream_delivery_chat(
            session,
            current_user,
            message=payload.message,
            project_id=payload.project_id,
            conversation_id=payload.conversation_id,
        ):
            yield chunk
        await session.commit()

    return StreamingResponse(
        _generate(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


@router.get(
    "/delivery/chat/conversations/{conversation_id}",
    response_model=DataResponse[DeliveryChatConversationRead],
)
async def get_delivery_chat_conversation(
    conversation_id: UUID,
    session: SessionDep,
    current_user: UserDep,
) -> DataResponse[DeliveryChatConversationRead]:
    """Reload a previously persisted conversation thread, e.g. after a page refresh."""
    result = await load_delivery_chat_conversation(session, current_user, conversation_id)
    if result is None:
        raise ApiError(404, "NOT_FOUND", "Conversation was not found.")
    return DataResponse(data=result)
