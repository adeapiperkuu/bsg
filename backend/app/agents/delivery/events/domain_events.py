"""Domain events for the Delivery Performance Agent."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID


@dataclass(frozen=True, slots=True)
class MilestoneStatusUpdate:
    """Pure milestone lifecycle transition computed during scoring."""

    milestone_id: UUID
    milestone_name: str
    previous_status: str
    new_status: str


@dataclass(frozen=True, slots=True)
class ConfidenceSnapshot:
    """Serializable confidence score state for idempotent handlers."""

    id: UUID
    milestone_id: UUID
    score_pct: Decimal
    status: str
    forecast_completion_date: date | None
    model_version: str | None


@dataclass(frozen=True, slots=True)
class RiskAlertSnapshot:
    """Serializable risk alert state for notification thresholds."""

    id: UUID
    alert_type: str
    risk_tier: str
    slippage_probability: Decimal | None
    milestone_id: UUID | None


@dataclass(frozen=True, slots=True)
class DeliveryScoresSnapshot:
    """Serializable delivery analytics output."""

    confidence: Decimal
    risk: Decimal
    traffic_light: str
    risk_tier: str
    contributing_causes: dict[str, float]
    confidence_status: str
    forecast_completion_date: date | None


@dataclass(frozen=True, slots=True)
class DeliveryScoredEvent:
    """Emitted after pure scoring completes; triggers all delivery side effects."""

    project_id: UUID
    org_id: UUID
    project_name: str
    as_of_date: date
    occurred_at: datetime
    scores: DeliveryScoresSnapshot
    current_milestone_id: UUID | None
    milestone_updates: tuple[MilestoneStatusUpdate, ...] = field(default_factory=tuple)
    previous_confidence: ConfidenceSnapshot | None = None
    previous_delivery_alert: RiskAlertSnapshot | None = None
    latest_confidence_by_milestone: dict[UUID, ConfidenceSnapshot] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class MilestoneUpdatedEvent:
    """Emitted when a milestone lifecycle status is persisted."""

    project_id: UUID
    org_id: UUID
    milestone_id: UUID
    milestone_name: str
    previous_status: str
    new_status: str
    as_of_date: date
    occurred_at: datetime


@dataclass(frozen=True, slots=True)
class RiskAlertChangedEvent:
    """Emitted when a delivery risk alert is created or updated."""

    project_id: UUID
    org_id: UUID
    alert_id: UUID
    alert_type: str
    risk_tier: str
    slippage_probability: Decimal | None
    milestone_id: UUID | None
    action: str
    as_of_date: date
    occurred_at: datetime
    detail: str = ""


@dataclass(frozen=True, slots=True)
class HandlerRunSummary:
    """Aggregated side-effect results from delivery scoring handlers."""

    milestones_updated: int = 0
    confidence_score_id: UUID | None = None
    risk_alert_id: UUID | None = None
    milestone_alert_ids: tuple[UUID, ...] = field(default_factory=tuple)
    notifications_sent: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "milestones_updated": self.milestones_updated,
            "confidence_score_id": str(self.confidence_score_id) if self.confidence_score_id else None,
            "risk_alert_id": str(self.risk_alert_id) if self.risk_alert_id else None,
            "milestone_alert_ids": [str(item) for item in self.milestone_alert_ids],
            "notifications_sent": self.notifications_sent,
        }
