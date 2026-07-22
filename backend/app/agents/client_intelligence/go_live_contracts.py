"""Go-Live readiness contracts and assessment (Phase 17.2)."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from enum import StrEnum
from uuid import UUID

from pydantic import Field, field_validator, model_validator

from app.agents.client_intelligence.contracts import ClientIntelligenceModel
from app.agents.client_intelligence.explainability import AiExplainability
from app.agents.client_intelligence.readiness_contracts import ReadinessEvidenceRef


class GoLiveDecision(StrEnum):
    GO = "go"
    GO_WITH_CONDITIONS = "go_with_conditions"
    NO_GO = "no_go"


class GoLiveAvailability(StrEnum):
    AVAILABLE = "available"
    PARTIAL = "partial"
    UNAVAILABLE = "unavailable"


class GoLiveAssessment(ClientIntelligenceModel):
    """Go / Go with Conditions / No Go decision with actionable context."""

    org_id: UUID
    project_id: UUID
    as_of: date
    assessed_at: datetime
    availability: GoLiveAvailability
    decision: GoLiveDecision
    confidence_score: Decimal = Field(ge=Decimal("0"), le=Decimal("1"))
    reasons: list[str] = Field(default_factory=list)
    blocking_items: list[str] = Field(default_factory=list)
    required_actions: list[str] = Field(default_factory=list)
    outstanding_defects: list[str] = Field(default_factory=list)
    open_blockers: list[str] = Field(default_factory=list)
    required_approvals: list[str] = Field(default_factory=list)
    dependency_gaps: list[str] = Field(default_factory=list)
    rollout_readiness_notes: list[str] = Field(default_factory=list)
    evidence: list[ReadinessEvidenceRef] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)
    source_fingerprint: str
    rules_version: str = "client_go_live_v1"
    explainability: AiExplainability | None = None

    @field_validator(
        "reasons",
        "blocking_items",
        "required_actions",
        "outstanding_defects",
        "open_blockers",
        "required_approvals",
        "dependency_gaps",
        "rollout_readiness_notes",
        "limitations",
    )
    @classmethod
    def _canonicalize(cls, value: list[str]) -> list[str]:
        cleaned: list[str] = []
        seen: set[str] = set()
        for item in value:
            text = item.strip() if isinstance(item, str) else ""
            if not text or text in seen:
                continue
            seen.add(text)
            cleaned.append(text)
        return cleaned

    @field_validator("assessed_at")
    @classmethod
    def _aware(cls, value: datetime) -> datetime:
        if value.tzinfo is None:
            raise ValueError("assessed_at must be timezone-aware")
        return value

    @model_validator(mode="after")
    def _decision_invariants(self) -> GoLiveAssessment:
        if self.decision == GoLiveDecision.GO and self.blocking_items:
            raise ValueError("Go decisions cannot retain blocking items")
        if self.decision == GoLiveDecision.NO_GO and not (
            self.blocking_items or self.reasons
        ):
            raise ValueError("No Go decisions require blocking items or reasons")
        if (
            self.decision == GoLiveDecision.GO_WITH_CONDITIONS
            and not self.required_actions
        ):
            raise ValueError("Go with Conditions requires required actions")
        return self


def go_live_decision_label(decision: GoLiveDecision) -> str:
    return {
        GoLiveDecision.GO: "Go",
        GoLiveDecision.GO_WITH_CONDITIONS: "Go with Conditions",
        GoLiveDecision.NO_GO: "No Go",
    }[decision]
