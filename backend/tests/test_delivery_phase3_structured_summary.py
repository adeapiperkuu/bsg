"""Phase 3 deterministic structured delivery summary."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
from pydantic import ValidationError

from app.agents.delivery.analytics.summary import build_structured_summary
from app.agents.delivery.configuration import DEFAULT_DELIVERY_SCORING_THRESHOLDS
from app.agents.delivery.schemas.dashboard_schema import (
    DashboardResponse,
    DeliveryPortfolioResponse,
    StructuredSummarySchema,
)
from app.agents.delivery.services.dashboard_service import (
    _gather_delivery_queries,
    _portfolio_cache,
    _portfolio_cache_key,
    clear_delivery_portfolio_cache,
    get_portfolio_data,
)
from app.agents.delivery.services.scoring_service import (
    ScoringContext,
    build_dashboard_response,
)
from app.agents.delivery.services.summary_service import build_structured_summary_payload
from app.core.security import CurrentUser
from app.db.models import AppRole, Project

ORG_ID = uuid4()
PROJECT_ID = uuid4()
AS_OF = date(2026, 7, 20)
GENERATED_AT = datetime(2026, 7, 20, 12, 0, tzinfo=UTC)


def _project_payload(**overrides):
    payload = {
        "id": PROJECT_ID,
        "org_id": ORG_ID,
        "name": "Atlas",
        "description": None,
        "vertical": "AI",
        "status": "active",
        "start_date": AS_OF - timedelta(days=30),
        "target_end_date": AS_OF + timedelta(days=60),
        "actual_end_date": None,
        "daily_target_units": 100,
        "updated_at": GENERATED_AT,
    }
    payload.update(overrides)
    return payload


def _throughput(units: int, *, days_ago: int = 0, rolling: int | None = None):
    snapshot_date = AS_OF - timedelta(days=days_ago)
    return {
        "id": uuid4(),
        "project_id": PROJECT_ID,
        "snapshot_date": snapshot_date,
        "units_completed": units,
        "units_forecast": None,
        "rolling_7day_units": rolling if rolling is not None else units * 7,
        "created_at": GENERATED_AT,
        "updated_at": GENERATED_AT,
    }


def _milestone(name: str, *, status: str, days_offset: int):
    return {
        "id": uuid4(),
        "project_id": PROJECT_ID,
        "name": name,
        "description": None,
        "planned_date": AS_OF + timedelta(days=days_offset),
        "actual_date": None,
        "status": status,
    }


def _risk(title: str, *, tier: str = "medium", days_ago: int = 1):
    return {
        "id": uuid4(),
        "project_id": PROJECT_ID,
        "milestone_id": None,
        "alert_type": "delivery_risk",
        "risk_tier": tier,
        "title": title,
        "detail": "internal detail must not appear in structured_summary",
        "slippage_probability": None,
        "contributing_causes": {"internal_cause": 1.0},
        "status": "open",
        "created_at": datetime(2026, 7, 20, tzinfo=UTC) - timedelta(days=days_ago),
        "updated_at": GENERATED_AT,
    }


def _bottleneck(
    title: str,
    *,
    status: str = "open",
    severity: str = "medium",
    team_id=None,
    days_ago: int = 1,
):
    return {
        "id": uuid4(),
        "project_id": PROJECT_ID,
        "team_id": team_id or uuid4(),
        "title": title,
        "detail": "evidence detail must not appear in structured_summary",
        "status": status,
        "severity": severity,
        "source_key": "delivery-team-throughput-bottleneck:v1:secret",
        "created_at": datetime(2026, 7, 20, tzinfo=UTC) - timedelta(days=days_ago),
        "updated_at": GENERATED_AT,
    }


def _raw_data(
    *,
    project=None,
    milestones=None,
    throughput=None,
    risks=None,
    bottlenecks=None,
    quality=None,
):
    return {
        "as_of_date": AS_OF,
        "project": project or _project_payload(),
        "milestones": milestones if milestones is not None else [],
        "throughput_snapshots": throughput if throughput is not None else [],
        "risks": risks if risks is not None else [],
        "bottlenecks": bottlenecks if bottlenecks is not None else [],
        "quality_snapshot": quality,
    }


def _summary_from_raw(raw_data: dict, *, generated_at=GENERATED_AT) -> dict:
    context = ScoringContext.from_raw_data(raw_data, thresholds=DEFAULT_DELIVERY_SCORING_THRESHOLDS)
    from app.agents.delivery.services.scoring_service import compute_delivery_scores

    scores = compute_delivery_scores(context)
    return build_structured_summary_payload(context, scores, generated_at=generated_at)


# ---------------------------------------------------------------------------
# Healthy / warning / critical summaries
# ---------------------------------------------------------------------------


def test_healthy_project_structured_summary() -> None:
    raw = _raw_data(
        throughput=[
            _throughput(100, days_ago=0, rolling=700),
            _throughput(100, days_ago=1, rolling=700),
            _throughput(100, days_ago=2, rolling=700),
        ],
        milestones=[_milestone("Launch", status="on_track", days_offset=20)],
    )
    summary = _summary_from_raw(raw)

    assert summary["status"] == "green"
    assert summary["headline"] == "Delivery on track"
    assert summary["bottleneck_summary"] == {"active_count": 0, "highest_severity": None}
    assert summary["data_quality"] == []
    assert summary["risks"] == []
    assert any(fact.startswith("Confidence score:") for fact in summary["key_facts"])
    assert any("Throughput trend: flat" in fact for fact in summary["key_facts"])


def test_warning_summary_with_active_bottleneck_and_medium_risk() -> None:
    raw = _raw_data(
        throughput=[
            _throughput(90, days_ago=0, rolling=630),
            _throughput(100, days_ago=1, rolling=700),
        ],
        risks=[_risk("Scope creep", tier="medium")],
        bottlenecks=[_bottleneck("Team share decline", severity="high")],
        milestones=[_milestone("Beta", status="at_risk", days_offset=5)],
    )
    summary = _summary_from_raw(raw)

    assert summary["status"] == "yellow"
    assert summary["headline"] == "Delivery needs attention"
    assert summary["bottleneck_summary"]["active_count"] == 1
    assert summary["bottleneck_summary"]["highest_severity"] == "high"
    assert summary["risks"] == ["medium: Scope creep"]


def test_critical_summary_with_missed_milestone_and_critical_risk() -> None:
    raw = _raw_data(
        throughput=[
            _throughput(20, days_ago=0, rolling=100),
            _throughput(80, days_ago=1, rolling=500),
        ],
        risks=[_risk("Slippage", tier="critical")],
        milestones=[_milestone("Alpha", status="missed", days_offset=-3)],
        bottlenecks=[
            _bottleneck("Critical blocker", severity="critical"),
            _bottleneck("Secondary", severity="low"),
        ],
    )
    summary = _summary_from_raw(raw)

    assert summary["status"] == "red"
    assert summary["headline"] == "Delivery at risk"
    assert summary["bottleneck_summary"]["highest_severity"] == "critical"
    assert summary["bottleneck_summary"]["active_count"] == 2
    assert any("Overdue milestone: Alpha" in change for change in summary["delivery_changes"])
    assert summary["risks"][0] == "critical: Slippage"


# ---------------------------------------------------------------------------
# Active vs resolved bottlenecks
# ---------------------------------------------------------------------------


def test_resolved_bottlenecks_are_excluded_from_summary() -> None:
    # Dashboard inputs only include open/acknowledged rows; a resolved row must not
    # contribute even if a caller accidentally passes one through.
    raw = _raw_data(
        throughput=[_throughput(100, rolling=700)],
        bottlenecks=[
            _bottleneck("Still active", status="acknowledged", severity="medium"),
            _bottleneck("Already resolved", status="resolved", severity="critical"),
        ],
    )
    summary = _summary_from_raw(raw)

    assert summary["bottleneck_summary"] == {
        "active_count": 1,
        "highest_severity": "medium",
    }
    assert not any("Already resolved" in change for change in summary["delivery_changes"])


# ---------------------------------------------------------------------------
# Missing / stale data
# ---------------------------------------------------------------------------


def test_missing_throughput_produces_insufficient_data_summary() -> None:
    summary = _summary_from_raw(_raw_data(throughput=[]))

    assert summary["headline"] == "Insufficient delivery data"
    assert "missing_throughput_history" in summary["data_quality"]
    assert any("Data sufficiency: insufficient" in fact for fact in summary["key_facts"])


def test_stale_and_missing_target_data_quality_warnings() -> None:
    summary = build_structured_summary(
        as_of_date=AS_OF,
        traffic_light="yellow",
        confidence=Decimal("70.00"),
        risk_score=Decimal("40.00"),
        risk_tier="medium",
        rolling_windows=[700, 700],
        flat_tolerance_pct=Decimal("5.00"),
        latest_throughput=_throughput(100, days_ago=5, rolling=700),
        previous_throughput=None,
        daily_target_units=None,
        milestones=[],
        risks=[],
        bottlenecks=[],
        has_sufficient_data=True,
        quality_snapshot={"has_drift_alert": True, "rework_rate_pct": Decimal("12.0")},
        milestone_warning_window_days=14,
        stale_after_days=2,
        generated_at=GENERATED_AT,
    )

    assert summary["data_quality"] == [
        "missing_daily_target",
        "stale_throughput_data",
        "quality_drift_signal",
    ]


# ---------------------------------------------------------------------------
# Deterministic ordering and client-safe fields
# ---------------------------------------------------------------------------


def test_structured_summary_ordering_is_deterministic() -> None:
    risks = [
        _risk("Zulu risk", tier="low"),
        _risk("Alpha risk", tier="high"),
        _risk("Beta risk", tier="high"),
    ]
    bottlenecks = [
        _bottleneck("Zulu bn", severity="low", days_ago=0),
        _bottleneck("Alpha bn", severity="critical", days_ago=0),
    ]
    raw = _raw_data(
        throughput=[_throughput(50, rolling=350), _throughput(80, rolling=560)],
        risks=risks,
        bottlenecks=bottlenecks,
        milestones=[
            _milestone("Zulu MS", status="missed", days_offset=-2),
            _milestone("Alpha MS", status="missed", days_offset=-5),
        ],
    )
    first = _summary_from_raw(raw)
    second = _summary_from_raw(raw)

    assert (
        first["risks"]
        == second["risks"]
        == [
            "high: Alpha risk",
            "high: Beta risk",
            "low: Zulu risk",
        ]
    )
    assert first["delivery_changes"] == second["delivery_changes"]
    assert first["key_facts"] == second["key_facts"]
    assert first["data_quality"] == second["data_quality"]
    overdue = [c for c in first["delivery_changes"] if c.startswith("Overdue milestone:")]
    assert overdue[0].startswith("Overdue milestone: Alpha MS")
    assert overdue[1].startswith("Overdue milestone: Zulu MS")


def test_structured_summary_is_client_safe() -> None:
    raw = _raw_data(
        throughput=[_throughput(100, rolling=700)],
        risks=[_risk("Visible title", tier="high")],
        bottlenecks=[
            _bottleneck(
                "Share decline",
                severity="high",
                team_id=uuid4(),
            )
        ],
    )
    summary = _summary_from_raw(raw)
    dumped = StructuredSummarySchema.model_validate(summary).model_dump()
    blob = str(dumped).lower()

    assert "source_key" not in blob
    assert "evidence" not in blob
    assert "team_id" not in blob
    assert "headcount" not in blob
    assert "acknowledged_by" not in blob
    assert "contributing_causes" not in blob
    assert "internal detail" not in blob
    assert "internal_cause" not in blob
    assert dumped["risks"] == ["high: Visible title"]
    assert set(dumped.keys()) == {
        "status",
        "headline",
        "key_facts",
        "risks",
        "delivery_changes",
        "bottleneck_summary",
        "data_quality",
        "generated_at",
    }


# ---------------------------------------------------------------------------
# daily_summary preserved; response schema compatibility
# ---------------------------------------------------------------------------


def test_build_dashboard_response_keeps_daily_summary_null_and_adds_structured() -> None:
    dashboard = build_dashboard_response(
        _raw_data(throughput=[_throughput(100, rolling=700)]),
        thresholds=DEFAULT_DELIVERY_SCORING_THRESHOLDS,
    )

    assert dashboard["daily_summary"] is None
    assert dashboard["structured_summary"] is not None
    assert dashboard["structured_summary"]["status"] in {"green", "yellow", "red"}
    assert dashboard["traffic_light"] != "amber"

    validated = DashboardResponse.model_validate(dashboard)
    assert validated.daily_summary is None
    assert validated.structured_summary is not None
    assert validated.structured_summary.status == dashboard["structured_summary"]["status"]


def test_dashboard_schema_accepts_legacy_payload_without_structured_summary() -> None:
    project_id = uuid4()
    payload = {
        "overview": {
            "project": {
                "id": project_id,
                "org_id": uuid4(),
                "name": "Legacy",
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
        "traffic_light": "yellow",
        "daily_summary": None,
    }
    dashboard = DashboardResponse.model_validate(payload)
    assert dashboard.structured_summary is None
    assert dashboard.daily_summary is None
    assert dashboard.traffic_light == "yellow"

    portfolio = DeliveryPortfolioResponse.model_validate(
        {
            "projects": [{"project_id": project_id, "dashboard": payload}],
            "milestones": [],
            "total_count": 1,
        }
    )
    assert portfolio.projects[0].dashboard.structured_summary is None


def test_structured_summary_rejects_amber_status() -> None:
    with pytest.raises(ValidationError):
        StructuredSummarySchema.model_validate(
            {
                "status": "amber",
                "headline": "x",
                "key_facts": [],
                "risks": [],
                "delivery_changes": [],
                "bottleneck_summary": {"active_count": 0, "highest_severity": None},
                "data_quality": [],
                "generated_at": GENERATED_AT,
            }
        )


# ---------------------------------------------------------------------------
# Query counts and cache invalidation
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_portfolio_input_bundle_remains_one_query_with_structured_summary() -> None:
    session = AsyncMock()
    result = MagicMock()
    result.all.return_value = []
    session.execute.return_value = result

    await _gather_delivery_queries(session, [uuid4(), uuid4(), uuid4()])

    session.execute.assert_awaited_once()


@pytest.mark.asyncio
async def test_portfolio_cache_invalidation_refreshes_structured_summary(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    clear_delivery_portfolio_cache()
    user = CurrentUser(
        id=uuid4(),
        org_id=ORG_ID,
        email="dm@example.com",
        role=AppRole.DELIVERY_MANAGER,
        is_active=True,
    )
    project = Project(
        id=PROJECT_ID,
        org_id=ORG_ID,
        name="Atlas",
        description=None,
        vertical="AI",
        status="active",
        start_date=AS_OF,
        target_end_date=AS_OF + timedelta(days=30),
        actual_end_date=None,
        daily_target_units=100,
    )

    call_state = {"n": 0}

    async def fake_thresholds(session, org_ids):
        return {org_id: DEFAULT_DELIVERY_SCORING_THRESHOLDS for org_id in org_ids}

    async def fake_inputs(session, project_ids):
        call_state["n"] += 1
        bottlenecks = [] if call_state["n"] == 1 else [_bottleneck("New blocker", severity="high")]
        return {
            "milestones": {PROJECT_ID: []},
            "throughput_snapshots": {
                PROJECT_ID: [
                    _throughput(100, rolling=700),
                    _throughput(100, days_ago=1, rolling=700),
                ]
            },
            "risks": {PROJECT_ID: []},
            "bottlenecks": {PROJECT_ID: bottlenecks},
            "quality_snapshots": {PROJECT_ID: None},
        }

    monkeypatch.setattr(
        "app.agents.delivery.services.dashboard_service"
        ".load_delivery_scoring_thresholds_for_organisations",
        fake_thresholds,
    )
    monkeypatch.setattr(
        "app.agents.delivery.services.dashboard_service._fetch_delivery_inputs_by_project",
        fake_inputs,
    )

    session = AsyncMock()
    first = await get_portfolio_data(session=session, current_user=user, projects=[project])
    cache_key = _portfolio_cache_key(user)
    _portfolio_cache[cache_key] = (datetime.now(UTC), first)

    cached = await get_portfolio_data(session=session, current_user=user)
    assert call_state["n"] == 1
    assert (
        cached["projects"][0]["dashboard"]["structured_summary"]["bottleneck_summary"][
            "active_count"
        ]
        == 0
    )

    removed = clear_delivery_portfolio_cache(org_id=ORG_ID)
    assert removed >= 1
    assert cache_key not in _portfolio_cache

    second = await get_portfolio_data(session=session, current_user=user, projects=[project])
    assert call_state["n"] == 2
    assert (
        second["projects"][0]["dashboard"]["structured_summary"]["bottleneck_summary"][
            "active_count"
        ]
        == 1
    )
    assert (
        second["projects"][0]["dashboard"]["structured_summary"]["bottleneck_summary"][
            "highest_severity"
        ]
        == "high"
    )
