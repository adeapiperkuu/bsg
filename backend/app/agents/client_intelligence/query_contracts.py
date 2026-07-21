"""Typed contracts for Client Intelligence grounded Q&A."""

from __future__ import annotations

from datetime import date, datetime
from enum import StrEnum
from typing import Annotated
from uuid import UUID

from pydantic import BeforeValidator, Field, field_validator, model_validator

from app.agents.client_intelligence.contracts import ClientIntelligenceModel, SourceAgent
from app.schemas.common import EvidenceLinkRead


def _strip_question(value: object) -> object:
    if isinstance(value, str):
        return value.strip()
    return value


class ClientIntelligenceAnswerAvailability(StrEnum):
    ANSWERED = "answered"
    INSUFFICIENT_EVIDENCE = "insufficient_evidence"
    UNSUPPORTED = "unsupported"
    PROVIDER_UNAVAILABLE = "provider_unavailable"


class ClientIntelligenceConfidenceLevel(StrEnum):
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"
    INSUFFICIENT = "insufficient"


class ClientIntelligenceQuestionCategory(StrEnum):
    PROJECT_HEALTH = "project_health"
    DELIVERY_CONFIDENCE = "delivery_confidence"
    CONFIDENCE_HISTORY = "confidence_history"
    MILESTONES = "milestones"
    RISKS = "risks"
    DELIVERY_TREND = "delivery_trend"
    CHANGE = "change"
    REPORTS = "reports"
    QUALITY = "quality"
    WORKFORCE = "workforce"
    GOVERNANCE = "governance"
    KNOWLEDGE = "knowledge"
    COMMITMENT = "commitment"
    CROSS_SCOPE = "cross_scope"
    SENSITIVE = "sensitive"
    INJECTION = "injection"
    UNSUPPORTED = "unsupported"
    GENERAL_STATUS = "general_status"


class ClientIntelligenceQuestionCreate(ClientIntelligenceModel):
    question: Annotated[
        str,
        BeforeValidator(_strip_question),
        Field(min_length=1, max_length=2000),
    ]


class ClientIntelligenceQueryEvidenceLink(ClientIntelligenceModel):
    id: UUID
    source_table: str
    source_row_id: UUID
    description: str
    created_at: datetime | None = None
    visibility: str | None = None
    observed_at: datetime | None = None
    claim_keys: list[str] = Field(default_factory=list)
    pack_source_fingerprint: str | None = None
    evidence_provenance_complete: bool = False


class ClientIntelligenceQueryRead(ClientIntelligenceModel):
    query_id: UUID
    project_id: UUID
    question: str
    answer_text: str
    answer_availability: ClientIntelligenceAnswerAvailability
    confidence_level: ClientIntelligenceConfidenceLevel
    limitations: list[str] = Field(default_factory=list)
    next_step: str | None = None
    escalation_required: bool = False
    source_agents: list[str] = Field(default_factory=list)
    evidence_links: list[ClientIntelligenceQueryEvidenceLink] = Field(default_factory=list)
    as_of: date | None = None
    reporting_period_start: date | None = None
    reporting_period_end: date | None = None
    model_used: str | None = None
    latency_ms: int | None = Field(default=None, ge=0)
    created_at: datetime
    category: ClientIntelligenceQuestionCategory | None = None
    insufficient_evidence: bool = False
    evidence_source_fingerprint: str | None = None
    evidence_provenance_complete: bool | None = None
    evidence_provenance_state: str | None = None

    @field_validator("limitations", "source_agents")
    @classmethod
    def _canonicalize_lists(cls, value: list[str]) -> list[str]:
        return sorted({item.strip() for item in value if item and item.strip()})

    @model_validator(mode="after")
    def _invariants(self) -> ClientIntelligenceQueryRead:
        if self.latency_ms is not None and self.latency_ms < 0:
            raise ValueError("latency_ms cannot be negative")
        if self.answer_availability == ClientIntelligenceAnswerAvailability.ANSWERED:
            if self.insufficient_evidence:
                raise ValueError("answered query cannot be marked insufficient_evidence")
            if not self.evidence_links:
                raise ValueError("answered query requires evidence links")
            if self.confidence_level == ClientIntelligenceConfidenceLevel.INSUFFICIENT:
                raise ValueError("answered query cannot use insufficient confidence")
        elif self.answer_availability in {
            ClientIntelligenceAnswerAvailability.INSUFFICIENT_EVIDENCE,
            ClientIntelligenceAnswerAvailability.UNSUPPORTED,
            ClientIntelligenceAnswerAvailability.PROVIDER_UNAVAILABLE,
        }:
            if self.confidence_level not in {
                ClientIntelligenceConfidenceLevel.LOW,
                ClientIntelligenceConfidenceLevel.INSUFFICIENT,
            }:
                raise ValueError("non-answered outcomes require low or insufficient confidence")
        if self.escalation_required and not (self.next_step or "").strip():
            raise ValueError("escalation_required requires next_step")
        return self


class ClientIntelligenceQueryHistoryRead(ClientIntelligenceModel):
    project_id: UUID
    items: list[ClientIntelligenceQueryRead]
    limit: int = Field(ge=1, le=50)
    offset: int = Field(ge=0)
    total: int = Field(ge=0)
    has_more: bool

    @model_validator(mode="after")
    def _page_invariants(self) -> ClientIntelligenceQueryHistoryRead:
        if len(self.items) > self.limit:
            raise ValueError("items cannot exceed limit")
        expected_more = self.offset + len(self.items) < self.total
        if self.has_more != expected_more:
            raise ValueError("has_more must match offset+len(items) < total")
        return self


class ClientIntelligenceQueryRetrievalParams(ClientIntelligenceModel):
    """Structured metadata stored on AgentQuery.retrieval_params."""

    schema_version: int = 1
    answer_availability: ClientIntelligenceAnswerAvailability
    confidence_level: ClientIntelligenceConfidenceLevel
    category: ClientIntelligenceQuestionCategory
    limitations: list[str] = Field(default_factory=list)
    next_step: str | None = None
    escalation_required: bool = False
    insufficient_evidence: bool = False
    source_agents: list[str] = Field(default_factory=list)
    as_of: date | None = None
    reporting_period_start: date | None = None
    reporting_period_end: date | None = None
    source_fingerprint: str | None = None


# Re-export for schema package convenience
__all__ = [
    "ClientIntelligenceAnswerAvailability",
    "ClientIntelligenceConfidenceLevel",
    "ClientIntelligenceQuestionCategory",
    "ClientIntelligenceQuestionCreate",
    "ClientIntelligenceQueryEvidenceLink",
    "ClientIntelligenceQueryHistoryRead",
    "ClientIntelligenceQueryRead",
    "ClientIntelligenceQueryRetrievalParams",
    "EvidenceLinkRead",
    "SourceAgent",
]
