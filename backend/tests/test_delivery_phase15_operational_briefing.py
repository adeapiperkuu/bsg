"""Phase 15.4 — deterministic operational briefing unit tests."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from uuid import uuid4

from app.agents.delivery.ai.summary_service import build_daily_summary_prompt
from app.agents.delivery.analytics.operational_briefing import build_operational_briefing
from app.agents.delivery.schemas.operational_briefing import OperationalBriefingSchema


def _milestone(*, name: str, planned: date, status: str = "pending") -> dict:
    return {
        "id": uuid4(),
        "name": name,
        "planned_date": planned,
        "status": status,
    }


def _risk(*, title: str, tier: str, created_at: datetime, status: str = "open") -> dict:
    return {
        "id": uuid4(),
        "title": title,
        "risk_tier": tier,
        "status": status,
        "created_at": created_at,
        "detail": "internal",
    }


def _bottleneck(*, title: str, severity: str, created_at: datetime) -> dict:
    return {
        "id": uuid4(),
        "title": title,
        "status": "open",
        "severity": severity,
        "created_at": created_at,
        "detail": "internal",
    }


def test_operational_briefing_sections_are_grounded() -> None:
    as_of = date(2026, 7, 20)
    created = datetime(2026, 7, 20, 8, 0, tzinfo=UTC)
    briefing = build_operational_briefing(
        as_of_date=as_of,
        traffic_light="yellow",
        confidence=72.0,
        previous_confidence=80.0,
        has_sufficient_data=True,
        latest_throughput={
            "units_completed": 40,
            "snapshot_date": as_of,
        },
        previous_throughput={
            "units_completed": 55,
            "snapshot_date": as_of - timedelta(days=1),
        },
        daily_target_units=50,
        milestones=[
            _milestone(name="Alpha", planned=as_of + timedelta(days=2)),
            _milestone(name="Beta", planned=as_of - timedelta(days=1), status="at_risk"),
        ],
        risks=[_risk(title="Review backlog", tier="high", created_at=created)],
        bottlenecks=[
            _bottleneck(title="QA queue", severity="critical", created_at=created)
        ],
        root_cause_summary={
            "overall_confidence": 72.0,
            "confidence_loss": 18.0,
            "top_causes": [
                {
                    "factor": "review_turnaround",
                    "label": "Review turnaround",
                    "impact_percent": 55.0,
                    "impact_points": 9.9,
                    "explanation": "Pending reviews above SLA",
                }
            ],
            "model_version": "delivery_root_cause_v1",
        },
        pm_actions=[
            {
                "rank": 1,
                "title": "Clear review queue",
                "urgency": "critical",
                "estimated_impact_points": 9.9,
                "due_date": as_of.isoformat(),
                "status": "todo",
                "deterministic_rationale": "Top confidence-loss driver",
                "root_cause_factor": "review_turnaround",
            }
        ],
        milestone_warning_window_days=14,
        generated_at=datetime(2026, 7, 20, 9, 0, tzinfo=UTC),
    )

    assert briefing["traffic_light"] == "yellow"
    assert any("Throughput changed" in line for line in briefing["overnight_changes"])
    assert briefing["confidence_movement"]["direction"] == "down"
    assert briefing["confidence_movement"]["delta"] == -8.0
    assert any("Review turnaround" in d for d in briefing["confidence_movement"]["drivers"])
    assert briefing["new_risks"][0].startswith("high:")
    assert any("Review turnaround" in p for p in briefing["top_priorities"])
    assert any("Alpha" in m for m in briefing["milestones_due_soon"])
    assert any("Beta" in m for m in briefing["milestones_due_soon"])
    assert briefing["recommended_pm_actions"][0]["title"] == "Clear review queue"
    assert briefing["ai_generated"] is False
    assert "72%" in briefing["narrative"]

    validated = OperationalBriefingSchema.model_validate(briefing)
    assert validated.headline
    assert validated.recommended_pm_actions[0].rank == 1


def test_insufficient_data_briefing() -> None:
    briefing = build_operational_briefing(
        as_of_date=date(2026, 7, 20),
        traffic_light="green",
        confidence=100.0,
        previous_confidence=None,
        has_sufficient_data=False,
        latest_throughput=None,
        previous_throughput=None,
        daily_target_units=None,
        milestones=[],
        risks=[],
        bottlenecks=[],
        root_cause_summary=None,
        pm_actions=[],
        milestone_warning_window_days=14,
    )
    assert briefing["headline"].startswith("Insufficient")
    assert "Insufficient delivery activity" in briefing["narrative"]
    assert briefing["confidence_movement"]["direction"] == "insufficient_data"


def test_daily_summary_prompt_includes_root_causes_and_briefing_sections() -> None:
    prompt = build_daily_summary_prompt(
        {
            "traffic_light": "red",
            "confidence": 55,
            "overview": {"has_sufficient_data": True},
            "risks": [],
            "bottlenecks": [],
            "root_cause_summary": {
                "top_causes": [{"factor": "capacity_shortage", "label": "Capacity shortage"}]
            },
            "operational_briefing": {
                "overnight_changes": ["Throughput changed -5 units"],
                "top_priorities": ["Address Capacity shortage"],
            },
            "pm_actions": [{"rank": 1, "title": "Add capacity", "urgency": "high"}],
        }
    )
    assert "root_cause_summary" in prompt
    assert "Capacity shortage" in prompt
    assert "operational_briefing" in prompt
    assert "Add capacity" in prompt
    assert "Never invent causes" in prompt or "never invent causes" in prompt.lower()
