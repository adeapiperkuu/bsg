from datetime import date, datetime, timezone
from decimal import Decimal
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest
from httpx import AsyncClient

from app.core.exceptions import ApiError
from app.core.security import CurrentUser
from app.db.models import (
    AlertType,
    AppRole,
    CapabilityGap,
    CapabilityGapSeverity,
    CapabilityGapStatus,
    CapabilityGapType,
    DeliverySite,
    OwnerType,
    Project,
    RecommendationSeverity,
    RecommendationStatus,
    UtilizationSnapshot,
)
from app.agents.delivery.services.recommendation_service import OwnerOption, RecommendationRow
from app.db.models import MitigationRecommendation
from app.schemas.domain import (
    ProjectWorkforceSummaryRead,
    SkillMatrixRead,
    TrainingGapSummaryRead,
)
from app.services.workforce_dashboard import get_project_workforce_dashboard
from tests.conftest import ORG_A, client_a, override_user


def _user(role: AppRole, org_id=None) -> CurrentUser:
    return CurrentUser(
        id=uuid4(),
        org_id=org_id or uuid4(),
        email=f"{role.value}@example.com",
        role=role,
        is_active=True,
    )


def _project(org_id) -> Project:
    return Project(
        id=uuid4(),
        org_id=org_id,
        name="Workforce Dashboard Project",
        vertical="medical",
        status="active",
        start_date="2026-01-01",
        target_end_date="2026-12-31",
    )


class FakeScalars:
    def __init__(self, items):
        self._items = items

    def all(self):
        return self._items


class FakeResult:
    def __init__(self, items=None):
        self._items = items or []

    def scalars(self):
        return FakeScalars(self._items)


class FakeSession:
    def __init__(self, *, utilization=None):
        self.utilization = utilization or []

    async def execute(self, _stmt):
        return FakeResult(self.utilization)


@pytest.mark.asyncio
async def test_client_cannot_access_workforce_dashboard_http(api_client: AsyncClient, client_a) -> None:
    override_user(client_a)
    response = await api_client.get(f"/api/v1/projects/{uuid4()}/workforce-dashboard")
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "FORBIDDEN"


@pytest.mark.asyncio
async def test_get_project_workforce_dashboard_assembles_sections() -> None:
    org_id = uuid4()
    project = _project(org_id)
    user = _user(AppRole.DELIVERY_MANAGER, org_id)
    now = datetime.now(timezone.utc)
    snapshot = UtilizationSnapshot(
        id=uuid4(),
        org_id=org_id,
        project_id=project.id,
        team_id=uuid4(),
        annotator_id=None,
        snapshot_date=date(2026, 7, 1),
        allocated_hours=Decimal("40"),
        available_hours=Decimal("40"),
        utilization_pct=Decimal("100"),
        billable_hours=None,
        non_billable_hours=None,
        notes=None,
        created_at=now,
        updated_at=now,
    )
    gap = CapabilityGap(
        id=uuid4(),
        org_id=org_id,
        project_id=project.id,
        team_id=None,
        skill_id=None,
        gap_type=CapabilityGapType.SME_SHORTAGE,
        severity=CapabilityGapSeverity.HIGH,
        title="SME shortage",
        detail="Need more SMEs",
        evidence=None,
        status=CapabilityGapStatus.OPEN,
        detected_at=now,
        resolved_at=None,
        created_at=now,
        updated_at=now,
    )
    recommendation = MitigationRecommendation(
        id=uuid4(),
        project_id=project.id,
        org_id=org_id,
        title="Hire SMEs",
        description="Backfill SME coverage",
        severity=RecommendationSeverity.HIGH,
        confidence_score=Decimal("0.800"),
        status=RecommendationStatus.PENDING,
        owner_type=None,
        owner_id=None,
        source_risk_id=uuid4(),
        created_at=now,
        updated_at=now,
    )
    delivery_recommendation = MitigationRecommendation(
        id=uuid4(),
        project_id=project.id,
        org_id=org_id,
        title="Protect milestone",
        description="Delivery only",
        severity=RecommendationSeverity.MEDIUM,
        confidence_score=Decimal("0.700"),
        status=RecommendationStatus.PENDING,
        owner_type=None,
        owner_id=None,
        source_risk_id=uuid4(),
        created_at=now,
        updated_at=now,
    )
    summary = ProjectWorkforceSummaryRead(project_id=project.id, teams=[], annotators=[])
    matrix = SkillMatrixRead(project_id=project.id, rows=[])
    training = TrainingGapSummaryRead(
        project_id=project.id,
        total_training_gaps=2,
        mandatory_training_incomplete=1,
        expired_or_failed_training=1,
        expired_certifications=0,
        pending_certification_reviews=0,
        rows=[],
    )
    session = FakeSession(utilization=[snapshot])

    async def _run_on_fake_session(_user, builder):
        # The real _run_section opens a fresh pooled DB session per dashboard
        # section; in unit tests every section must run on the FakeSession.
        return await builder(session)

    with (
        patch(
            "app.services.workforce_dashboard._run_section",
            new=_run_on_fake_session,
        ),
        patch(
            "app.services.workforce_dashboard.get_project_workforce_summary",
            new=AsyncMock(return_value=summary),
        ),
        patch(
            "app.services.workforce_dashboard.build_project_skill_matrix",
            new=AsyncMock(return_value=matrix),
        ),
        patch(
            "app.services.workforce_dashboard.build_project_training_gaps",
            new=AsyncMock(return_value=training),
        ),
        patch(
            "app.services.workforce_dashboard.list_project_capability_gaps",
            new=AsyncMock(return_value=[gap]),
        ),
        patch(
            "app.services.workforce_dashboard.list_project_recommendations",
            new=AsyncMock(
                return_value=(
                    [
                        RecommendationRow(
                            recommendation=recommendation,
                            owner_label=None,
                            source_risk_title="SME shortage",
                            source_risk_type=AlertType.WORKFORCE_IMBALANCE.value,
                            source_risk_slippage_probability=None,
                        ),
                        RecommendationRow(
                            recommendation=delivery_recommendation,
                            owner_label=None,
                            source_risk_title="Milestone slip",
                            source_risk_type="schedule_slippage",
                            source_risk_slippage_probability=None,
                        ),
                    ],
                    [
                        OwnerOption(
                            owner_type=OwnerType.USER,
                            owner_id=uuid4(),
                            label="Delivery Manager",
                        )
                    ],
                )
            ),
        ),
    ):
        dashboard = await get_project_workforce_dashboard(session, project, user)

    assert dashboard.project_id == project.id
    assert dashboard.summary.project_id == project.id
    assert len(dashboard.utilization) == 1
    assert dashboard.utilization[0].utilization_pct == Decimal("100")
    assert dashboard.skill_matrix.project_id == project.id
    assert dashboard.training_gaps.total_training_gaps == 2
    assert len(dashboard.capability_gaps) == 1
    assert dashboard.capability_gaps[0].title == "SME shortage"
    assert len(dashboard.recommendations.data) == 1
    assert dashboard.recommendations.data[0].title == "Hire SMEs"
    assert dashboard.recommendations.data[0].risks[0].source_risk_type == "workforce_imbalance"
    assert len(dashboard.recommendations.assignable_owners) == 1


@pytest.mark.asyncio
async def test_get_project_workforce_dashboard_rejects_client_role() -> None:
    project = _project(uuid4())
    user = _user(AppRole.CLIENT, project.org_id)
    session = FakeSession()

    with pytest.raises(ApiError) as exc:
        await get_project_workforce_dashboard(session, project, user)

    assert exc.value.status_code == 403
