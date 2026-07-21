"""Schemas for Phase 15.4 AI daily operational briefing."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from app.agents.delivery.contracts import DeliveryTrafficLight

ConfidenceDirection = Literal["up", "down", "flat", "insufficient_data"]


class ConfidenceMovementSchema(BaseModel):
    current: float
    previous: float | None = None
    delta: float | None = None
    direction: ConfidenceDirection
    drivers: list[str] = Field(default_factory=list)


class RecommendedPmActionSchema(BaseModel):
    rank: int
    title: str
    urgency: str
    estimated_impact_points: float = 0
    due_date: str = ""
    rationale: str = ""
    root_cause_factor: str | None = None


class OperationalBriefingSchema(BaseModel):
    """Grounded morning briefing. Deterministic sections; optional AI narrative."""

    model_config = ConfigDict(extra="allow")

    as_of: str
    traffic_light: DeliveryTrafficLight
    headline: str
    overnight_changes: list[str] = Field(default_factory=list)
    confidence_movement: ConfidenceMovementSchema
    new_risks: list[str] = Field(default_factory=list)
    top_priorities: list[str] = Field(default_factory=list)
    milestones_due_soon: list[str] = Field(default_factory=list)
    recommended_pm_actions: list[RecommendedPmActionSchema] = Field(default_factory=list)
    knowledge_evidence: list[dict[str, Any]] = Field(default_factory=list)
    root_cause_summary: dict[str, Any] | None = None
    narrative: str | None = None
    ai_generated: bool = False
    model_version: str
    generated_at: str


class OperationalBriefingGenerateRequest(BaseModel):
    with_ai: bool = True
