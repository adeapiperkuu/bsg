"""Phase 15.3 PM Daily Action Planner tests."""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from uuid import UUID, uuid4

import pytest
from httpx import AsyncClient

from app.agents.delivery.analytics.pm_actions import (
    build_candidates_from_root_causes,
    due_date_for_urgency,
    rank_daily_actions,
    urgency_from_impact,
)
from app.core.security import CurrentUser
from app.db.models import AppRole
from tests.conftest import client_a, delivery_manager, override_user

PROJECT_ID = UUID("22222222-2222-2222-2222-222222222222")
TODAY = date(2026, 7, 20)


def test_urgency_and_due_dates() -> None:
    assert urgency_from_impact(Decimal("12")) == "critical"
    assert urgency_from_impact(Decimal("7"), severity="high") == "high"
    assert due_date_for_urgency(TODAY, "critical") == TODAY
    assert due_date_for_urgency(TODAY, "high") == date(2026, 7, 21)


def test_rank_from_root_causes() -> None:
    factors = [
        {
            "factor": "review_turnaround",
            "impact_percent": 40,
            "impact_points": -8,
            "severity": "high",
            "explanation": "Review delays dominate loss.",
            "evidence_json": {"data_available": True},
        },
        {
            "factor": "rework",
            "impact_percent": 25,
            "impact_points": -5,
            "severity": "medium",
            "explanation": "Rework elevated.",
            "evidence_json": {"data_available": True},
        },
    ]
    candidates = build_candidates_from_root_causes(plan_date=TODAY, factors=factors)
    ranked = rank_daily_actions(candidates, limit=5)
    assert ranked
    assert ranked[0].root_cause_factor == "review_turnaround"
    assert ranked[0].estimated_impact_points == Decimal("8.00")
    assert "confidence loss" in ranked[0].deterministic_rationale.lower() or "Review" in ranked[
        0
    ].deterministic_rationale


@pytest.mark.asyncio
async def test_daily_actions_client_forbidden(api_client: AsyncClient, client_a) -> None:
    override_user(client_a)
    response = await api_client.get(
        f"/api/v1/delivery/projects/{PROJECT_ID}/daily-actions",
        headers={"Authorization": "Bearer test-token"},
    )
    assert response.status_code == 403


@pytest.mark.asyncio
async def test_daily_actions_dm_not_role_blocked(
    api_client: AsyncClient, delivery_manager
) -> None:
    override_user(delivery_manager)
    response = await api_client.get(
        f"/api/v1/delivery/projects/{PROJECT_ID}/daily-actions",
        headers={"Authorization": "Bearer test-token"},
    )
    assert response.status_code != 403


@pytest.mark.asyncio
async def test_generate_daily_actions_client_forbidden(
    api_client: AsyncClient, client_a
) -> None:
    override_user(client_a)
    response = await api_client.post(
        f"/api/v1/delivery/projects/{PROJECT_ID}/daily-actions/generate",
        headers={"Authorization": "Bearer test-token"},
        json={},
    )
    assert response.status_code == 403


@pytest.mark.asyncio
async def test_generate_daily_actions_dm_not_role_blocked(
    api_client: AsyncClient, delivery_manager
) -> None:
    override_user(delivery_manager)
    response = await api_client.post(
        f"/api/v1/delivery/projects/{PROJECT_ID}/daily-actions/generate",
        headers={"Authorization": "Bearer test-token"},
        json={"with_ai_rationale": False, "limit": 5},
    )
    assert response.status_code != 403


@pytest.mark.asyncio
async def test_complete_daily_action_client_forbidden(
    api_client: AsyncClient, client_a
) -> None:
    override_user(client_a)
    response = await api_client.post(
        f"/api/v1/delivery/daily-actions/{uuid4()}/complete",
        headers={"Authorization": "Bearer test-token"},
        json={"status": "done"},
    )
    assert response.status_code == 403
