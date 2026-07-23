from datetime import UTC, date, datetime
from types import SimpleNamespace
from uuid import uuid4

import pytest

from app.agents.governance.routes.governance import router as governance_router
from app.agents.governance.routes.weekly_summaries import router as weekly_summaries_router
from app.agents.governance.services.governance_service import assert_can_manage_weekly_summary
from app.agents.governance.services.summary_service import (
    SummaryEvidenceItem,
    build_template_summary,
    get_latest_weekly_summary_read_cached,
    has_sufficient_evidence,
    invalidate_latest_weekly_summary_read_cache,
    monday_of_week,
)
from app.core.exceptions import ApiError
from app.core.security import CurrentUser
from app.db.models import AppRole, GovernanceEvidenceSourceType


class FakeScalars:
    def __init__(self, items):
        self._items = items

    def all(self):
        return self._items

    def scalar_one_or_none(self):
        return self._items[0] if self._items else None


class FakeResult:
    def __init__(self, items):
        self._items = items

    def scalars(self):
        return FakeScalars(self._items)

    def scalar_one_or_none(self):
        return self._items[0] if self._items else None


class QueueSession:
    def __init__(self, results):
        self.results = list(results)
        self.execute_count = 0

    async def execute(self, *_args, **_kwargs):
        self.execute_count += 1
        return FakeResult(self.results.pop(0) if self.results else [])


def _user(role: AppRole) -> CurrentUser:
    return CurrentUser(
        id=uuid4(),
        org_id=uuid4(),
        email=f"{role.value}@example.com",
        role=role,
        is_active=True,
    )


def _summary(org_id):
    return SimpleNamespace(
        id=uuid4(),
        org_id=org_id,
        summary_week=date(2026, 7, 13),
        summary_text="## 1. Executive Overview\nStable governance posture.",
        status="draft",
        generated_by_ai=True,
        approved_by=None,
        approved_at=None,
        created_at=datetime(2026, 7, 14, tzinfo=UTC),
        updated_at=datetime(2026, 7, 14, tzinfo=UTC),
    )


def test_monday_of_week() -> None:
    assert monday_of_week(date(2026, 6, 26)) == date(2026, 6, 22)


def test_has_sufficient_evidence_requires_items() -> None:
    assert not has_sufficient_evidence([])
    assert has_sufficient_evidence(
        [
            SummaryEvidenceItem(
                source_type=GovernanceEvidenceSourceType.DEPENDENCY,
                source_id=uuid4(),
                evidence_ref="dependency:x",
                label="Test",
                category="dependency",
                project_name="Phoenix",
                detail="blocking",
            )
        ]
    )


def test_build_template_summary_includes_sections() -> None:
    item = SummaryEvidenceItem(
        source_type=GovernanceEvidenceSourceType.DEPENDENCY,
        source_id=uuid4(),
        evidence_ref="dependency:abc",
        label="Client API approval",
        category="dependency",
        project_name="Phoenix",
        detail="status=blocking",
    )
    context = {
        "summary_week": "2026-06-22",
        "dependencies": [
            {
                "evidence_ref": "dependency:abc",
                "title": "Client API approval",
                "project_name": "Phoenix",
                "status": "blocking",
                "overdue_days": 5,
            }
        ],
        "actions": [],
        "escalations": [],
        "scope_states": [],
        "delivery_signals": [],
        "knowledge_documents": [],
        "projects_attention": [
            {"project": "Phoenix", "score": 5, "reasons": ["blocking dependency"]}
        ],
    }
    text = build_template_summary(context, [item])
    assert "## 1. Executive Overview" in text
    assert "## 6. Evidence Section" in text
    assert "Client API approval" in text
    assert "Phoenix" in text


@pytest.mark.parametrize(
    "role",
    [AppRole.DELIVERY_MANAGER, AppRole.BSG_LEADERSHIP, AppRole.SUPER_ADMIN],
)
def test_summary_managers_can_generate_and_approve(role: AppRole) -> None:
    assert_can_manage_weekly_summary(_user(role))


def test_client_cannot_manage_weekly_summary() -> None:
    with pytest.raises(ApiError) as exc_info:
        assert_can_manage_weekly_summary(_user(AppRole.CLIENT))
    assert exc_info.value.status_code == 403


def test_weekly_summary_export_routes_are_registered() -> None:
    def _paths(routes) -> set[str]:
        found: set[str] = set()
        for route in routes:
            path = getattr(route, "path", None)
            if path:
                found.add(path)
            nested = getattr(route, "routes", None)
            if nested:
                found.update(_paths(nested))
        return found

    paths = _paths(governance_router.routes)
    paths.update(_paths(weekly_summaries_router.routes))
    assert "/governance/weekly-summary/{summary_id}/export.pdf" in paths
    assert "/governance/weekly-summary/{summary_id}/export.docx" in paths


@pytest.mark.asyncio
async def test_latest_weekly_summary_read_cache_returns_defensive_hit() -> None:
    invalidate_latest_weekly_summary_read_cache()
    user = _user(AppRole.DELIVERY_MANAGER)
    summary = _summary(user.org_id)
    first_session = QueueSession([[summary], [], []])

    first = await get_latest_weekly_summary_read_cached(first_session, user)
    second = await get_latest_weekly_summary_read_cached(QueueSession([]), user)

    assert first.cache_hit is False
    assert first.read.summary_text.endswith("Stable governance posture.")
    assert first_session.execute_count == 3
    assert first.execute_count == 3
    assert second.cache_hit is True
    assert second.execute_count == 0
    assert second.read.summary_text == first.read.summary_text
    assert second.read is not first.read

    assert invalidate_latest_weekly_summary_read_cache(org_id=user.org_id) == 1
