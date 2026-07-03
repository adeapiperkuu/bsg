"""Request/response schemas for the Delivery Agent chat endpoints."""

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field, field_validator

from app.core.config import get_settings


class DeliveryChatCreate(BaseModel):
    message: str = Field(min_length=1)
    project_id: UUID | None = None
    conversation_id: UUID | None = None

    @field_validator("message")
    @classmethod
    def _enforce_max_length(cls, value: str) -> str:
        max_length = get_settings().delivery_chat_max_message_length
        if len(value) > max_length:
            raise ValueError(f"Message must be {max_length} characters or fewer.")
        return value


class DeliveryChatSource(BaseModel):
    title: str
    type: str
    id: UUID | None = None
    description: str | None = None


class DeliveryChatRead(BaseModel):
    answer: str
    sources: list[DeliveryChatSource] = Field(default_factory=list)
    conversation_id: UUID


class DeliveryChatTurnRead(BaseModel):
    id: UUID
    query_text: str
    answer_text: str
    created_at: datetime
    sources: list[DeliveryChatSource] = Field(default_factory=list)


class DeliveryChatConversationRead(BaseModel):
    conversation_id: UUID
    project_id: UUID | None
    turns: list[DeliveryChatTurnRead]
