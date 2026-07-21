"""Schemas for PM Daily Action Planner."""

from __future__ import annotations

from datetime import date, datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class PmDailyActionRead(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    project_id: str
    org_id: str
    plan_date: date | str
    rank: int
    title: str
    description: str | None = None
    deterministic_rationale: str
    ai_rationale: str | None = None
    urgency: Literal["low", "medium", "high", "critical"]
    estimated_impact_points: float
    due_date: date | str
    status: Literal["todo", "done", "skipped", "deferred"]
    source_type: Literal["root_cause_factor", "risk_alert", "bottleneck", "mitigation", "milestone"]
    source_key: str
    root_cause_factor: str | None = None
    mitigation_recommendation_id: str | None = None
    evidence_json: dict[str, Any] = Field(default_factory=dict)
    completed_at: datetime | str | None = None
    completed_by: str | None = None
    completion_note: str | None = None
    model_version: str | None = None
    generated_at: datetime | str | None = None


class PmDailyActionsResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    project_id: str
    plan_date: date | str
    todays_focus: list[PmDailyActionRead] = Field(default_factory=list)
    all_today: list[PmDailyActionRead] = Field(default_factory=list)
    history: list[PmDailyActionRead] = Field(default_factory=list)
    generated_at: datetime | str | None = None


class PmDailyActionGenerateRequest(BaseModel):
    plan_date: date | None = None
    with_ai_rationale: bool = False
    limit: int = Field(default=8, ge=1, le=20)


class PmDailyActionCompleteRequest(BaseModel):
    status: Literal["done", "skipped", "deferred"] = "done"
    note: str | None = Field(default=None, max_length=2000)
