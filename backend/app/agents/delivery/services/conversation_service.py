"""Delivery Agent conversation persistence and history management."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.delivery.schemas.chat_schema import (
    DeliveryChatConversationRead,
    DeliveryChatSource,
    DeliveryChatTurnRead,
)
from app.core.exceptions import ApiError
from app.core.security import CurrentUser
from app.db.models import (
    AgentQuery,
    AgentQueryEvidenceLink,
    AppRole,
    DeliveryConversation,
    DeliveryMessage,
)
from app.services.scoping import get_visible_project

AGENT_NAME = "delivery_performance_agent"
DEFAULT_CONVERSATION_TITLE = "New conversation"
TITLE_MAX_LENGTH = 120
MAX_HISTORY_TURNS = 3
MAX_HISTORY_ANSWER_CHARS = 450
MAX_CONVERSATION_TURNS_RETURNED = 50

EVIDENCE_TYPE_BY_SOURCE_TABLE = {
    "risk_alerts": "risk",
    "bottlenecks": "bottleneck",
    "milestones": "milestone",
}


def title_from_message(message: str) -> str:
    text = message.strip()
    if not text:
        return DEFAULT_CONVERSATION_TITLE
    return text[:TITLE_MAX_LENGTH]


def _sources_from_metadata(metadata: dict[str, Any] | None) -> list[DeliveryChatSource]:
    if not metadata:
        return []
    raw_sources = metadata.get("sources")
    if not isinstance(raw_sources, list):
        return []
    sources: list[DeliveryChatSource] = []
    for item in raw_sources:
        if not isinstance(item, dict):
            continue
        sources.append(
            DeliveryChatSource(
                title=str(item.get("title") or ""),
                type=str(item.get("type") or ""),
                id=item.get("id"),
                description=item.get("description"),
            )
        )
    return sources


def _messages_to_turns(messages: list[DeliveryMessage]) -> list[DeliveryChatTurnRead]:
    turns: list[DeliveryChatTurnRead] = []
    index = 0
    while index < len(messages):
        message = messages[index]
        if message.role != "user":
            index += 1
            continue
        assistant: DeliveryMessage | None = None
        if index + 1 < len(messages) and messages[index + 1].role == "assistant":
            assistant = messages[index + 1]
        if assistant is None:
            index += 1
            continue
        turns.append(
            DeliveryChatTurnRead(
                id=assistant.agent_query_id or assistant.id,
                query_text=message.content,
                answer_text=assistant.content,
                created_at=assistant.created_at,
                sources=_sources_from_metadata(assistant.metadata_),
            )
        )
        index += 2
    return turns


async def _assert_project_visible(
    session: AsyncSession,
    project_id: UUID | None,
    current_user: CurrentUser,
) -> None:
    if project_id is None:
        return
    await get_visible_project(session, project_id, current_user)


async def get_owned_conversation(
    session: AsyncSession,
    current_user: CurrentUser,
    conversation_id: UUID,
) -> DeliveryConversation | None:
    conversation = await session.get(DeliveryConversation, conversation_id)
    if not isinstance(conversation, DeliveryConversation):
        return None
    is_super_admin = current_user.role == AppRole.SUPER_ADMIN
    if not is_super_admin and conversation.user_id != current_user.id:
        return None
    if conversation.org_id != current_user.org_id and not is_super_admin:
        return None
    try:
        await _assert_project_visible(session, conversation.project_id, current_user)
    except ApiError:
        return None
    return conversation


async def list_delivery_conversations(
    session: AsyncSession,
    current_user: CurrentUser,
    *,
    project_id: UUID | None = None,
    limit: int = 50,
) -> list[dict[str, Any]]:
    filters = [DeliveryConversation.org_id == current_user.org_id]
    if current_user.role != AppRole.SUPER_ADMIN:
        filters.append(DeliveryConversation.user_id == current_user.id)
    if project_id is not None:
        filters.append(DeliveryConversation.project_id == project_id)
    else:
        filters.append(DeliveryConversation.project_id.is_(None))

    conversations = list(
        (
            await session.execute(
                select(DeliveryConversation)
                .where(*filters)
                .order_by(DeliveryConversation.updated_at.desc())
                .limit(limit)
            )
        ).scalars()
    )
    if not conversations:
        return []

    conversation_ids = [conversation.id for conversation in conversations]
    turn_counts = {
        row.conversation_id: int(row.turn_count)
        for row in (
            await session.execute(
                select(
                    DeliveryMessage.conversation_id,
                    func.count().label("turn_count"),
                )
                .where(
                    DeliveryMessage.conversation_id.in_(conversation_ids),
                    DeliveryMessage.role == "user",
                )
                .group_by(DeliveryMessage.conversation_id)
            )
        )
    }

    return [
        {
            "id": conversation.id,
            "title": conversation.title,
            "project_id": conversation.project_id,
            "turn_count": turn_counts.get(conversation.id, 0),
            "created_at": conversation.created_at,
            "updated_at": conversation.updated_at,
        }
        for conversation in conversations
    ]


async def create_delivery_conversation(
    session: AsyncSession,
    current_user: CurrentUser,
    *,
    project_id: UUID | None = None,
    title: str | None = None,
) -> DeliveryConversation:
    await _assert_project_visible(session, project_id, current_user)
    conversation = DeliveryConversation(
        org_id=current_user.org_id,
        user_id=current_user.id,
        project_id=project_id,
        title=(title or DEFAULT_CONVERSATION_TITLE).strip()[:TITLE_MAX_LENGTH] or DEFAULT_CONVERSATION_TITLE,
    )
    session.add(conversation)
    await session.flush()
    return conversation


async def conversation_summary(
    session: AsyncSession,
    conversation: DeliveryConversation,
) -> dict[str, Any]:
    turn_count = int(
        (
            await session.execute(
                select(func.count())
                .select_from(DeliveryMessage)
                .where(
                    DeliveryMessage.conversation_id == conversation.id,
                    DeliveryMessage.role == "user",
                )
            )
        ).scalar_one()
    )
    return {
        "id": conversation.id,
        "title": conversation.title,
        "project_id": conversation.project_id,
        "turn_count": turn_count,
        "created_at": conversation.created_at,
        "updated_at": conversation.updated_at,
    }


async def rename_delivery_conversation(
    session: AsyncSession,
    current_user: CurrentUser,
    conversation_id: UUID,
    *,
    title: str,
) -> DeliveryConversation:
    conversation = await get_owned_conversation(session, current_user, conversation_id)
    if conversation is None:
        raise ApiError(404, "NOT_FOUND", "Conversation was not found.")
    cleaned = title.strip()
    if not cleaned:
        raise ApiError(400, "VALIDATION_ERROR", "Title cannot be empty.")
    conversation.title = cleaned[:TITLE_MAX_LENGTH]
    conversation.updated_at = datetime.now(UTC)
    await session.flush()
    return conversation


async def delete_delivery_conversation(
    session: AsyncSession,
    current_user: CurrentUser,
    conversation_id: UUID,
) -> None:
    conversation = await get_owned_conversation(session, current_user, conversation_id)
    if conversation is None:
        raise ApiError(404, "NOT_FOUND", "Conversation was not found.")
    await session.execute(
        delete(DeliveryMessage).where(DeliveryMessage.conversation_id == conversation.id)
    )
    await session.delete(conversation)
    await session.flush()


async def load_delivery_conversation_messages(
    session: AsyncSession,
    conversation_id: UUID,
    *,
    limit: int = MAX_CONVERSATION_TURNS_RETURNED,
) -> list[DeliveryMessage]:
    return list(
        (
            await session.execute(
                select(DeliveryMessage)
                .where(DeliveryMessage.conversation_id == conversation_id)
                .order_by(DeliveryMessage.created_at.asc())
                .limit(limit * 2)
            )
        ).scalars()
    )


async def get_delivery_conversation_read(
    session: AsyncSession,
    current_user: CurrentUser,
    conversation_id: UUID,
) -> DeliveryChatConversationRead | None:
    conversation = await get_owned_conversation(session, current_user, conversation_id)
    if conversation is None:
        return None
    messages = await load_delivery_conversation_messages(session, conversation.id)
    return DeliveryChatConversationRead(
        conversation_id=conversation.id,
        project_id=conversation.project_id,
        title=conversation.title,
        turns=_messages_to_turns(messages),
    )


async def load_llm_history_from_conversation(
    session: AsyncSession,
    conversation_id: UUID,
) -> list[dict[str, str]]:
    messages = await load_delivery_conversation_messages(
        session,
        conversation_id,
        limit=MAX_HISTORY_TURNS,
    )
    if len(messages) > MAX_HISTORY_TURNS * 2:
        messages = messages[-(MAX_HISTORY_TURNS * 2) :]
    history: list[dict[str, str]] = []
    for message in messages:
        if message.role == "user":
            history.append({"role": "user", "content": message.content})
        elif message.role == "assistant":
            history.append(
                {
                    "role": "assistant",
                    "content": message.content[:MAX_HISTORY_ANSWER_CHARS],
                }
            )
    return history


async def _migrate_legacy_conversation(
    session: AsyncSession,
    current_user: CurrentUser,
    anchor: AgentQuery,
) -> DeliveryConversation:
    rows = list(
        (
            await session.execute(
                select(AgentQuery)
                .where(
                    AgentQuery.user_id == anchor.user_id,
                    AgentQuery.agent_name == AGENT_NAME,
                    AgentQuery.project_id == anchor.project_id,
                    AgentQuery.created_at >= anchor.created_at,
                )
                .order_by(AgentQuery.created_at.asc())
                .limit(MAX_CONVERSATION_TURNS_RETURNED)
            )
        ).scalars()
    )
    query_ids = [row.id for row in rows]
    evidence_by_query: dict[UUID, list[AgentQueryEvidenceLink]] = {}
    if query_ids:
        evidence_rows = (
            await session.execute(
                select(AgentQueryEvidenceLink).where(
                    AgentQueryEvidenceLink.agent_query_id.in_(query_ids)
                )
            )
        ).scalars().all()
        for link in evidence_rows:
            evidence_by_query.setdefault(link.agent_query_id, []).append(link)

    conversation = DeliveryConversation(
        org_id=anchor.org_id,
        user_id=anchor.user_id,
        project_id=anchor.project_id,
        title=title_from_message(anchor.query_text),
        created_at=anchor.created_at,
        updated_at=rows[-1].created_at if rows else anchor.created_at,
    )
    session.add(conversation)
    await session.flush()

    for row in rows:
        session.add(
            DeliveryMessage(
                conversation_id=conversation.id,
                role="user",
                content=row.query_text,
                created_at=row.created_at,
            )
        )
        sources = [
            {
                "title": link.description,
                "type": EVIDENCE_TYPE_BY_SOURCE_TABLE.get(link.source_table, link.source_table),
                "id": str(link.source_row_id),
            }
            for link in evidence_by_query.get(row.id, [])
        ]
        session.add(
            DeliveryMessage(
                conversation_id=conversation.id,
                role="assistant",
                content=row.answer_text,
                agent_query_id=row.id,
                metadata_={
                    "sources": sources,
                    "model_used": row.model_used,
                    "latency_ms": row.latency_ms,
                },
                created_at=row.created_at,
            )
        )
    await session.flush()
    return conversation


async def resolve_conversation_for_turn(
    session: AsyncSession,
    current_user: CurrentUser,
    *,
    conversation_id: UUID | None,
    project_id: UUID | None,
    first_message: str,
) -> DeliveryConversation:
    if conversation_id is not None:
        conversation = await get_owned_conversation(session, current_user, conversation_id)
        if conversation is not None:
            if conversation.project_id != project_id:
                raise ApiError(400, "VALIDATION_ERROR", "Conversation project scope does not match.")
            return conversation

        anchor = await session.get(AgentQuery, conversation_id)
        if (
            anchor is not None
            and anchor.agent_name == AGENT_NAME
            and anchor.user_id == current_user.id
        ):
            await _assert_project_visible(session, anchor.project_id, current_user)
            return await _migrate_legacy_conversation(session, current_user, anchor)

    await _assert_project_visible(session, project_id, current_user)
    return await create_delivery_conversation(
        session,
        current_user,
        project_id=project_id,
        title=title_from_message(first_message),
    )


async def append_delivery_turn(
    session: AsyncSession,
    conversation: DeliveryConversation,
    *,
    user_message: str,
    assistant_message: str,
    agent_query: AgentQuery,
    response_sources: list[DeliveryChatSource],
) -> None:
    now = datetime.now(UTC)
    session.add(
        DeliveryMessage(
            conversation_id=conversation.id,
            role="user",
            content=user_message,
            created_at=now,
        )
    )
    session.add(
        DeliveryMessage(
            conversation_id=conversation.id,
            role="assistant",
            content=assistant_message,
            agent_query_id=agent_query.id,
            metadata_={
                "sources": [source.model_dump(mode="json") for source in response_sources],
                "model_used": agent_query.model_used,
                "latency_ms": agent_query.latency_ms,
            },
            created_at=now,
        )
    )
    if conversation.title == DEFAULT_CONVERSATION_TITLE:
        conversation.title = title_from_message(user_message)
    conversation.updated_at = now
    await session.flush()
