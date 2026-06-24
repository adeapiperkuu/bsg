"""Dashboard response schemas for the Delivery Performance Agent."""

from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class DashboardResponse(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)

    overview: dict[str, Any]
    milestones: list[dict[str, Any]]
    confidence: float
    risks: list[dict[str, Any]]
    bottlenecks: list[dict[str, Any]]
    traffic_light: Literal["green", "yellow", "red"]
    daily_summary: str | None = None


class DeliveryPortfolioProject(BaseModel):
    project_id: UUID
    dashboard: DashboardResponse


class DeliveryPortfolioResponse(BaseModel):
    projects: list[DeliveryPortfolioProject] = Field(default_factory=list)
    milestones: list[dict[str, Any]] = Field(default_factory=list)
