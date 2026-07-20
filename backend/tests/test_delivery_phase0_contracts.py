"""Phase 0 compatibility contracts for the Delivery Performance Agent."""

from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
from pydantic import ValidationError

from app.agents.delivery.events.domain_events import DeliveryScoredEvent
from app.agents.delivery.events.event_bus import EventBus
from app.agents.delivery.events.handlers import handle_delivery_scored, register_delivery_handlers
from app.agents.delivery.schemas.dashboard_schema import (
    DashboardResponse,
    DeliveryPortfolioResponse,
)
from app.agents.delivery.services.dashboard_service import _gather_delivery_queries


def _dashboard_payload(*, traffic_light: str = "yellow", daily_summary=None) -> dict:
    project_id = uuid4()
    return {
        "overview": {
            "project": {
                "id": project_id,
                "org_id": uuid4(),
                "name": "Contract project",
                "vertical": "test",
                "status": "active",
                "start_date": "2026-01-01",
                "target_end_date": "2026-12-31",
            },
            "latest_throughput": None,
            "current_milestone": None,
            "open_risk_count": 0,
            "open_bottleneck_count": 0,
            "calculated_risk": {"score": 20, "tier": "medium", "contributing_causes": {}},
        },
        "milestones": [],
        "confidence": 75,
        "risks": [],
        "bottlenecks": [],
        "traffic_light": traffic_light,
        "daily_summary": daily_summary,
    }


def test_dashboard_accepts_yellow_and_nullable_daily_summary() -> None:
    dashboard = DashboardResponse.model_validate(_dashboard_payload())

    assert dashboard.traffic_light == "yellow"
    assert dashboard.daily_summary is None


def test_dashboard_rejects_amber_as_api_traffic_light() -> None:
    with pytest.raises(ValidationError):
        DashboardResponse.model_validate(_dashboard_payload(traffic_light="amber"))


def test_portfolio_schema_remains_backward_compatible() -> None:
    dashboard = _dashboard_payload(daily_summary=None)
    portfolio = DeliveryPortfolioResponse.model_validate(
        {
            "projects": [
                {"project_id": dashboard["overview"]["project"]["id"], "dashboard": dashboard}
            ],
            "milestones": [],
            "total_count": 1,
        }
    )

    assert portfolio.total_count == 1
    assert portfolio.projects[0].dashboard.daily_summary is None


def test_delivery_scored_event_has_registered_consumer(monkeypatch: pytest.MonkeyPatch) -> None:
    bus = EventBus()
    monkeypatch.setattr("app.agents.delivery.events.handlers.get_delivery_event_bus", lambda: bus)
    monkeypatch.setattr("app.agents.delivery.events.handlers._handlers_registered", False)

    register_delivery_handlers()

    assert bus._handlers[DeliveryScoredEvent] == [handle_delivery_scored]


@pytest.mark.asyncio
async def test_portfolio_input_bundle_is_one_query_for_multiple_projects() -> None:
    session = AsyncMock()
    result = MagicMock()
    result.all.return_value = []
    session.execute.return_value = result

    await _gather_delivery_queries(session, [uuid4(), uuid4(), uuid4()])

    session.execute.assert_awaited_once()
