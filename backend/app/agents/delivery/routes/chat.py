"""Delivery Agent chat routes."""

from uuid import UUID

from fastapi import APIRouter, Query
from fastapi.responses import StreamingResponse

from app.agents.delivery.schemas.chat_schema import (
    DeliveryChatConversationCreate,
    DeliveryChatConversationRead,
    DeliveryChatConversationRename,
    DeliveryChatConversationSummaryRead,
    DeliveryChatCreate,
    DeliveryChatRead,
)
from app.agents.delivery.services.chat_service import (
    answer_delivery_chat,
    load_delivery_chat_conversation,
    stream_delivery_chat,
)
from app.agents.delivery.services.conversation_service import (
    conversation_summary,
    create_delivery_conversation,
    delete_delivery_conversation,
    list_delivery_conversations,
    rename_delivery_conversation,
)
from app.api.deps import SessionDep, UserDep
from app.core.config import get_settings
from app.core.exceptions import ApiError
from app.core.rate_limit import SlidingWindowRateLimiter
from app.core.security import CurrentUser
from app.schemas.common import DataResponse, ListResponse, Pagination

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


@router.get("/delivery/chat/conversations", response_model=ListResponse[DeliveryChatConversationSummaryRead])
async def list_delivery_chat_conversations(
    session: SessionDep,
    current_user: UserDep,
    project_id: UUID | None = None,
    limit: int = Query(default=50, ge=1, le=100),
) -> ListResponse[DeliveryChatConversationSummaryRead]:
    """List the current user's delivery conversations, most recently updated first."""
    rows = await list_delivery_conversations(
        session,
        current_user,
        project_id=project_id,
        limit=limit,
    )
    return ListResponse(
        data=[DeliveryChatConversationSummaryRead.model_validate(row) for row in rows],
        pagination=Pagination(limit=limit),
    )


@router.post("/delivery/chat/conversations", response_model=DataResponse[DeliveryChatConversationSummaryRead])
async def create_delivery_chat_conversation(
    payload: DeliveryChatConversationCreate,
    session: SessionDep,
    current_user: UserDep,
) -> DataResponse[DeliveryChatConversationSummaryRead]:
    """Create an empty delivery conversation (e.g. before the first message is sent)."""
    conversation = await create_delivery_conversation(
        session,
        current_user,
        project_id=payload.project_id,
        title=payload.title,
    )
    summary = await conversation_summary(session, conversation)
    await session.commit()
    return DataResponse(data=DeliveryChatConversationSummaryRead.model_validate(summary))


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


@router.patch(
    "/delivery/chat/conversations/{conversation_id}",
    response_model=DataResponse[DeliveryChatConversationSummaryRead],
)
async def rename_delivery_chat_conversation(
    conversation_id: UUID,
    payload: DeliveryChatConversationRename,
    session: SessionDep,
    current_user: UserDep,
) -> DataResponse[DeliveryChatConversationSummaryRead]:
    """Rename a delivery conversation."""
    conversation = await rename_delivery_conversation(
        session,
        current_user,
        conversation_id,
        title=payload.title,
    )
    summary = await conversation_summary(session, conversation)
    await session.commit()
    return DataResponse(data=DeliveryChatConversationSummaryRead.model_validate(summary))


@router.delete("/delivery/chat/conversations/{conversation_id}", status_code=204)
async def delete_delivery_chat_conversation(
    conversation_id: UUID,
    session: SessionDep,
    current_user: UserDep,
) -> None:
    """Delete a delivery conversation and all of its messages."""
    await delete_delivery_conversation(session, current_user, conversation_id)
    await session.commit()


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


@router.post(
    "/delivery/chat/conversations/{conversation_id}/messages",
    response_model=DataResponse[DeliveryChatRead],
)
async def post_delivery_chat_message(
    conversation_id: UUID,
    payload: DeliveryChatCreate,
    session: SessionDep,
    current_user: UserDep,
) -> DataResponse[DeliveryChatRead]:
    """Post a message to an existing delivery conversation (non-streaming)."""
    _enforce_delivery_chat_rate_limit(current_user)
    result = await answer_delivery_chat(
        session,
        current_user,
        message=payload.message,
        project_id=payload.project_id,
        conversation_id=conversation_id,
    )
    await session.commit()
    return DataResponse(data=result)
