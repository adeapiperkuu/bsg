"""Pydantic contracts for Delivery root-cause intelligence."""

from __future__ import annotations

from datetime import date, datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class RootCauseFactorRead(BaseModel):
    model_config = ConfigDict(extra="forbid")

    factor: str
    label: str
    impact_percent: float
    impact_points: float
    severity: Literal["low", "medium", "high", "critical"]
    explanation: str
    evidence_json: dict[str, Any] | None = None


class MainContributorRead(BaseModel):
    model_config = ConfigDict(extra="forbid")

    factor: str
    label: str
    impact_percent: float


class RootCauseSnapshotRead(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    project_id: str
    org_id: str
    snapshot_date: date | str
    overall_confidence: float
    confidence_loss: float
    model_version: str
    generated_at: datetime | str | None = None
    factors: list[RootCauseFactorRead] = Field(default_factory=list)
    main_contributors: list[MainContributorRead] = Field(default_factory=list)


class ProjectRootCausesResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    project_id: str
    as_of: date | str
    latest: RootCauseSnapshotRead | None = None
    history: list[RootCauseSnapshotRead] = Field(default_factory=list)
    root_cause_summary: dict[str, Any] | None = None


class RootCauseTrendFactorRead(BaseModel):
    model_config = ConfigDict(extra="forbid")

    factor: str
    label: str
    today: float | None = None
    last_week: float | None = None
    last_month: float | None = None
    trend_direction: Literal["up", "down", "flat", "insufficient_data"]


class RootCauseTrendsResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    as_of: date | str
    project_id: str | None = None
    org_id: str | None = None
    factors: list[RootCauseTrendFactorRead] = Field(default_factory=list)


class RootCauseCauseStatRead(BaseModel):
    model_config = ConfigDict(extra="forbid")

    factor: str
    label: str
    frequency: int
    average_impact_percent: float
    confidence_impact: float


class RootCauseWorstProjectRead(BaseModel):
    model_config = ConfigDict(extra="forbid")

    project_id: str
    project_name: str
    confidence_loss: float
    overall_confidence: float
    snapshot_date: date | str


class RootCauseAnalyticsResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    lookback_days: int
    org_id: str | None = None
    top_recurring_causes: list[RootCauseCauseStatRead] = Field(default_factory=list)
    worst_projects: list[RootCauseWorstProjectRead] = Field(default_factory=list)
    generated_at: datetime | str
    duration_ms: float | None = None


class RootCauseRecalculateResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    snapshot: RootCauseSnapshotRead
    recalculated: bool = True
