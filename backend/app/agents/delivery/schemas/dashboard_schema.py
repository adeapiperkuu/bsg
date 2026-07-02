"""Dashboard response schemas for the Delivery Performance Agent."""

from datetime import date, datetime
from decimal import Decimal
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class MilestoneSchema(BaseModel):
    """Matches the payload shape produced by dashboard_service._milestone_payload."""

    model_config = ConfigDict(extra="allow")

    id: UUID
    project_id: UUID
    name: str
    description: str | None = None
    planned_date: date
    actual_date: date | None = None
    status: str


class RiskSchema(BaseModel):
    """Matches the payload shape produced by dashboard_service._risk_payload."""

    model_config = ConfigDict(extra="allow")

    id: UUID
    project_id: UUID
    milestone_id: UUID | None = None
    alert_type: str
    risk_tier: str
    title: str
    detail: str
    slippage_probability: Decimal | None = None
    contributing_causes: dict[str, Any] | None = None
    status: str
    created_at: datetime
    updated_at: datetime


class BottleneckSchema(BaseModel):
    """Matches the payload shape produced by dashboard_service._bottleneck_payload."""

    model_config = ConfigDict(extra="allow")

    id: UUID
    project_id: UUID
    team_id: UUID | None = None
    title: str
    detail: str
    status: str
    created_at: datetime
    updated_at: datetime


class ProjectOverviewSchema(BaseModel):
    """Matches the payload shape produced by dashboard_service._project_payload."""

    model_config = ConfigDict(extra="allow")

    id: UUID
    org_id: UUID
    name: str
    description: str | None = None
    vertical: str
    status: str
    start_date: date
    target_end_date: date
    actual_end_date: date | None = None
    daily_target_units: int | None = None


class ThroughputSnapshotSchema(BaseModel):
    """Matches the payload shape produced by dashboard_service._throughput_payload."""

    model_config = ConfigDict(extra="allow")

    id: UUID
    project_id: UUID
    snapshot_date: date
    units_completed: int
    units_forecast: int | None = None
    rolling_7day_units: int | None = None
    created_at: datetime
    updated_at: datetime


class CalculatedRiskSchema(BaseModel):
    """Matches scoring_service.build_dashboard_response's overview.calculated_risk."""

    model_config = ConfigDict(extra="allow")

    score: float
    tier: str
    contributing_causes: dict[str, float]


class OverviewSchema(BaseModel):
    """Matches the `overview` dict produced by scoring_service.build_dashboard_response."""

    model_config = ConfigDict(extra="allow")

    project: ProjectOverviewSchema
    latest_throughput: ThroughputSnapshotSchema | None = None
    current_milestone: MilestoneSchema | None = None
    open_risk_count: int
    open_bottleneck_count: int
    calculated_risk: CalculatedRiskSchema
    # False only when the project has no throughput history yet — clients must render
    # "Insufficient data" rather than treating confidence/traffic_light as a real signal.
    has_sufficient_data: bool = True


class DashboardResponse(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)

    overview: OverviewSchema
    milestones: list[MilestoneSchema]
    confidence: float
    risks: list[RiskSchema]
    bottlenecks: list[BottleneckSchema]
    traffic_light: Literal["green", "yellow", "red"]
    daily_summary: str | None = None


class DeliveryPortfolioProject(BaseModel):
    project_id: UUID
    dashboard: DashboardResponse


class DeliveryPortfolioResponse(BaseModel):
    projects: list[DeliveryPortfolioProject] = Field(default_factory=list)
    milestones: list[dict[str, Any]] = Field(default_factory=list)
