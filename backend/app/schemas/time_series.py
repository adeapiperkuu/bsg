"""API schemas for the Phase 18.2 Platform Time-Series Engine."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


IntervalLiteral = Literal["hour", "day", "week", "month", "quarter", "on_demand"]
CompareMode = Literal["period", "baseline", "project", "department", "portfolio"]


class TimeSeriesScopeFilters(BaseModel):
    org_id: UUID | None = None
    project_id: UUID | None = None
    client_user_id: UUID | None = None
    department_key: str | None = None
    agent_key: str | None = None
    definition_version: str | None = None
    calculator_version: str | None = None
    date_from: datetime | None = None
    date_to: datetime | None = None
    interval: IntervalLiteral | None = None


class KpiObservationRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    org_id: UUID
    project_id: UUID | None = None
    kpi_key: str
    version: str
    definition_version: str | None = None
    calculator_key: str | None = None
    calculator_version: str | None = None
    observed_at: datetime
    evaluated_at: datetime | None = None
    numeric_value: Decimal | None = None
    text_value: str | None = None
    normalized_value: Decimal | None = None
    confidence: Decimal | None = None
    value_type: str = "numeric"
    status: str
    department_key: str | None = None
    agent_key: str | None = None
    source_type: str
    bucket_interval: str | None = None
    bucket_start: datetime | None = None
    bucket_end: datetime | None = None
    evidence_refs: list[Any] = Field(default_factory=list)
    lineage_refs: dict[str, Any] = Field(default_factory=dict)
    explainability: dict[str, Any] | None = None
    idempotency_fingerprint: str | None = None
    supersedes_observation_id: UUID | None = None


class KpiTrendSummaryRead(BaseModel):
    kpi_key: str
    latest: KpiObservationRead | None = None
    previous: KpiObservationRead | None = None
    absolute_change: Decimal | None = None
    percentage_change: Decimal | None = None
    raw_direction: Literal["up", "down", "flat", "unknown"] = "unknown"
    semantic_favorability: Literal[
        "improving", "declining", "stable", "on_target", "off_target", "unknown"
    ] = "unknown"
    trend_direction_policy: str
    observation_count: int = 0
    rolling_average: Decimal | None = None
    min_value: Decimal | None = None
    max_value: Decimal | None = None
    average_value: Decimal | None = None
    median_value: Decimal | None = None


class KpiSeriesPointRead(BaseModel):
    bucket_start: datetime
    bucket_end: datetime | None = None
    numeric_value: Decimal | None = None
    text_value: str | None = None
    observation_count: int = 1
    min_value: Decimal | None = None
    max_value: Decimal | None = None
    avg_value: Decimal | None = None
    median_value: Decimal | None = None


class KpiSeriesRead(BaseModel):
    kpi_key: str
    interval: IntervalLiteral
    points: list[KpiSeriesPointRead] = Field(default_factory=list)
    source: Literal["observations", "rollups"] = "observations"


class KpiComparisonSeriesRead(BaseModel):
    label: str
    scope_key: str
    project_id: UUID | None = None
    department_key: str | None = None
    points: list[KpiSeriesPointRead] = Field(default_factory=list)
    latest_value: Decimal | None = None


class KpiCompareRead(BaseModel):
    kpi_key: str
    mode: CompareMode
    interval: IntervalLiteral
    baseline_label: str | None = None
    series: list[KpiComparisonSeriesRead] = Field(default_factory=list)
    absolute_deltas: dict[str, Decimal | None] = Field(default_factory=dict)
    percentage_deltas: dict[str, Decimal | None] = Field(default_factory=dict)


class KpiForecastPointRead(BaseModel):
    forecast_at: datetime
    value: Decimal
    lower_bound: Decimal | None = None
    upper_bound: Decimal | None = None


class KpiForecastRead(BaseModel):
    kpi_key: str
    status: Literal["ok", "insufficient_data"]
    method: str | None = None
    model_version: str | None = None
    horizon: int | None = None
    training_window_start: datetime | None = None
    training_window_end: datetime | None = None
    sample_count: int = 0
    assumptions: list[str] = Field(default_factory=list)
    points: list[KpiForecastPointRead] = Field(default_factory=list)
    message: str | None = None


class TimeSeriesDimensionsRead(BaseModel):
    kpi_keys: list[str] = Field(default_factory=list)
    agents: list[str] = Field(default_factory=list)
    departments: list[str] = Field(default_factory=list)
    intervals: list[str] = Field(default_factory=list)
    min_observed_at: datetime | None = None
    max_observed_at: datetime | None = None


class RecommendationTimelineEventRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    org_id: UUID
    project_id: UUID | None = None
    domain: str
    subject_table: str
    subject_id: UUID
    event_type: str
    actor_user_id: UUID | None = None
    source_agent: str | None = None
    recommendation_type: str | None = None
    severity: str | None = None
    confidence: Decimal | None = None
    affected_kpi_keys: list[Any] = Field(default_factory=list)
    status_snapshot: str | None = None
    related_table: str | None = None
    related_id: UUID | None = None
    conversion_target: str | None = None
    resolution_outcome: str | None = None
    strategy_version: str | None = None
    evidence_fingerprint: str | None = None
    event_timestamp: datetime
    payload: dict[str, Any] = Field(default_factory=dict)


class RecommendationSubjectSummaryRead(BaseModel):
    domain: str
    subject_table: str
    subject_id: UUID
    project_id: UUID | None = None
    source_agent: str | None = None
    recommendation_type: str | None = None
    severity: str | None = None
    status_snapshot: str | None = None
    last_event_type: str
    last_event_at: datetime
    event_count: int = 1
