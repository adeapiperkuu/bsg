"""Request/response schemas for the Delivery Agent chat endpoint."""

from uuid import UUID

from pydantic import BaseModel, Field


class DeliveryChatCreate(BaseModel):
    message: str = Field(min_length=1)
    project_id: UUID | None = None
    conversation_id: UUID | None = None


class DeliveryChatSource(BaseModel):
    title: str
    type: str
    id: UUID | None = None
    description: str | None = None


class DeliveryChatRead(BaseModel):
    answer: str
    sources: list[DeliveryChatSource] = Field(default_factory=list)
    conversation_id: UUID
