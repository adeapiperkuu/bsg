"""Schemas for Phase 15.5 Delivery ↔ Knowledge evidence retrieval."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class KnowledgeEvidenceCitation(BaseModel):
    model_config = ConfigDict(extra="allow")

    document_id: str
    chunk_id: str | None = None
    title: str
    source_type: str = ""
    folder: str | None = None
    section_title: str | None = None
    page: str | None = None
    version: Any = None
    relevance_score: float = 0
    excerpt: str = ""
    visibility: str | None = None


class KnowledgeEvidenceResponse(BaseModel):
    project_id: str | None = None
    project_name: str | None = None
    query_text: str | None = None
    citations: list[KnowledgeEvidenceCitation] = Field(default_factory=list)
    enabled: bool = True
    empty_reason: str | None = None
    applied_filters: dict[str, Any] | None = None
    fallback_level: int | None = None
