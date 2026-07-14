from datetime import date
from uuid import uuid4

import pytest

from app.agents.governance.services.summary_service import (
    SummaryEvidenceItem,
    build_template_summary,
    has_sufficient_evidence,
    monday_of_week,
)
from app.agents.governance.services.governance_service import assert_can_manage_weekly_summary
from app.agents.governance.routes.governance import router as governance_router
from app.core.exceptions import ApiError
from app.core.security import CurrentUser
from app.db.models import AppRole, GovernanceEvidenceSourceType


def _user(role: AppRole) -> CurrentUser:
    return CurrentUser(
        id=uuid4(),
        org_id=uuid4(),
        email=f"{role.value}@example.com",
        role=role,
        is_active=True,
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
        "projects_attention": [{"project": "Phoenix", "score": 5, "reasons": ["blocking dependency"]}],
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
    paths = {route.path for route in governance_router.routes}
    assert "/governance/weekly-summary/{summary_id}/export.pdf" in paths
    assert "/governance/weekly-summary/{summary_id}/export.docx" in paths
