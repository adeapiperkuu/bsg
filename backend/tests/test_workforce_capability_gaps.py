from datetime import date, datetime, timezone
from decimal import Decimal
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest
from httpx import AsyncClient

from app.core.exceptions import ApiError
from app.core.security import CurrentUser
from app.db.models import (
    AppRole,
    CapabilityGap,
    CapabilityGapSeverity,
    CapabilityGapStatus,
    CapabilityGapType,
    DeliverySite,
    MitigationRecommendation,
    Project,
    ProjectSkillRequirement,
    ProficiencyLevel,
    RiskAlert,
    Skill,
    SkillCoverageStatus,
    SkillRequirementPriority,
    Team,
    UtilizationSnapshot,
)
from app.schemas.domain import (
    CapabilityGapUpdate,
    SkillMatrixRead,
    SkillMatrixRow,
    TrainingGapSummaryRead,
)
from app.services.workforce_gaps import (
    GapCandidate,
    _persist_candidates,
    _skill_shortage_severity,
    detect_and_persist_capability_gaps,
    detect_gap_candidates,
    get_capability_gap_or_404,
    list_project_capability_gaps,
    update_capability_gap,
)
from tests.conftest import ORG_A, client_a, delivery_manager, override_user


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
        name="Test Project",
        vertical="medical",
        status="active",
        start_date="2026-01-01",
        target_end_date="2026-12-31",
    )


def _requirement(project_id, org_id, skill_id, *, priority=SkillRequirementPriority.MEDIUM) -> ProjectSkillRequirement:
    return ProjectSkillRequirement(
        id=uuid4(),
        org_id=org_id,
        project_id=project_id,
        skill_id=skill_id,
        required_proficiency_level=ProficiencyLevel.ADVANCED,
        required_headcount=3,
        required_sme_count=1,
        priority=priority,
    )


def _skill(org_id, *, is_critical=False) -> Skill:
    return Skill(
        id=uuid4(),
        org_id=org_id,
        name="Radiology QA",
        category="Life Sciences",
        domain="radiology",
        is_critical=is_critical,
    )


def _matrix_row(skill_id, skill_name, *, available=0, required=3, sme_available=0, sme_required=1) -> SkillMatrixRow:
    return SkillMatrixRow(
        skill_id=skill_id,
        skill_name=skill_name,
        category="Life Sciences",
        domain="radiology",
        required_proficiency_level=ProficiencyLevel.ADVANCED,
        required_headcount=required,
        available_headcount=available,
        required_sme_count=sme_required,
        available_sme_count=sme_available,
        coverage_status=SkillCoverageStatus.LOW,
        by_site=[],
    )


class FakeScalars:
    def __init__(self, items):
        self._items = items

    def all(self):
        return self._items


class FakeResult:
    def __init__(self, value=None, items=None):
        self._value = value
        self._items = items or []

    def scalar_one_or_none(self):
        return self._value

    def scalars(self):
        return FakeScalars(self._items)


class FakeSession:
    def __init__(self, **kwargs):
        self.gap = kwargs.get("gap")
        self.gaps = kwargs.get("gaps", [])
        self.requirements = kwargs.get("requirements", [])
        self.skills = kwargs.get("skills", [])
        self.utilization = kwargs.get("utilization", [])
        self.risk_alert = kwargs.get("risk_alert")
        self.recommendation = kwargs.get("recommendation")
        self.filter_org_id = kwargs.get("filter_org_id")
        self.added: list[object] = []

    def add(self, obj: object) -> None:
        self.added.append(obj)
        if isinstance(obj, CapabilityGap) and obj.id is None:
            obj.id = uuid4()

    async def flush(self) -> None:
        return None

    async def execute(self, stmt):
        compiled = str(stmt.compile(compile_kwargs={"literal_binds": True}))
        if "FROM capability_gaps" in compiled:
            if "capability_gaps.id =" in compiled or "capability_gaps.id=" in compiled:
                return FakeResult(self.gap)
            gaps = self.gaps
            if "capability_gaps.org_id" in compiled and self.filter_org_id is not None:
                gaps = [gap for gap in gaps if gap.org_id == self.filter_org_id]
            return FakeResult(None, gaps)
        if "FROM project_skill_requirements" in compiled:
            return FakeResult(None, self.requirements)
        if "FROM skills" in compiled and "skills.id IN" in compiled:
            return FakeResult(None, self.skills)
        if "FROM utilization_snapshots" in compiled:
            return FakeResult(None, self.utilization)
        if "FROM risk_alerts" in compiled:
            return FakeResult(self.risk_alert)
        if "FROM mitigation_recommendations" in compiled:
            return FakeResult(self.recommendation)
        return FakeResult(None, [])


def test_skill_shortage_severity_critical_for_zero_high_priority() -> None:
    req = _requirement(uuid4(), uuid4(), uuid4(), priority=SkillRequirementPriority.CRITICAL)
    severity = _skill_shortage_severity(0, req, None)
    assert severity == CapabilityGapSeverity.CRITICAL


def test_skill_shortage_severity_medium_for_partial_shortage() -> None:
    req = _requirement(uuid4(), uuid4(), uuid4(), priority=SkillRequirementPriority.LOW)
    severity = _skill_shortage_severity(1, req, None)
    assert severity == CapabilityGapSeverity.MEDIUM


@pytest.mark.asyncio
async def test_detect_skill_shortage_from_matrix() -> None:
    org_a = uuid4()
    project = _project(org_a)
    skill = _skill(org_a)
    user = _user(AppRole.DELIVERY_MANAGER, org_a)
    session = FakeSession(
        requirements=[_requirement(project.id, org_a, skill.id)],
        skills=[skill],
    )
    matrix = SkillMatrixRead(
        project_id=project.id,
        rows=[_matrix_row(skill.id, skill.name, available=1, required=3)],
    )
    training = TrainingGapSummaryRead(
        project_id=project.id,
        total_training_gaps=0,
        mandatory_training_incomplete=0,
        expired_or_failed_training=0,
        expired_certifications=0,
        pending_certification_reviews=0,
        rows=[],
    )

    with (
        patch(
            "app.services.workforce_gaps.build_project_skill_matrix",
            new=AsyncMock(return_value=matrix),
        ),
        patch(
            "app.services.workforce_gaps.build_project_training_gaps",
            new=AsyncMock(return_value=training),
        ),
    ):
        candidates = await detect_gap_candidates(session, project, user)

    skill_gaps = [c for c in candidates if c.gap_type == CapabilityGapType.SKILL_SHORTAGE]
    assert len(skill_gaps) == 1
    assert skill_gaps[0].severity == CapabilityGapSeverity.MEDIUM


@pytest.mark.asyncio
async def test_detect_sme_shortage_is_high_severity() -> None:
    org_a = uuid4()
    project = _project(org_a)
    skill = _skill(org_a)
    user = _user(AppRole.DELIVERY_MANAGER, org_a)
    session = FakeSession(requirements=[], skills=[skill])
    matrix = SkillMatrixRead(
        project_id=project.id,
        rows=[_matrix_row(skill.id, skill.name, available=3, required=3, sme_available=0, sme_required=2)],
    )
    training = TrainingGapSummaryRead(
        project_id=project.id,
        total_training_gaps=0,
        mandatory_training_incomplete=0,
        expired_or_failed_training=0,
        expired_certifications=0,
        pending_certification_reviews=0,
        rows=[],
    )

    with (
        patch(
            "app.services.workforce_gaps.build_project_skill_matrix",
            new=AsyncMock(return_value=matrix),
        ),
        patch(
            "app.services.workforce_gaps.build_project_training_gaps",
            new=AsyncMock(return_value=training),
        ),
    ):
        candidates = await detect_gap_candidates(session, project, user)

    sme_gaps = [c for c in candidates if c.gap_type == CapabilityGapType.SME_SHORTAGE]
    assert len(sme_gaps) == 1
    assert sme_gaps[0].severity == CapabilityGapSeverity.HIGH


@pytest.mark.asyncio
async def test_detect_training_gap_from_summary() -> None:
    org_a = uuid4()
    project = _project(org_a)
    user = _user(AppRole.DELIVERY_MANAGER, org_a)
    session = FakeSession()
    matrix = SkillMatrixRead(project_id=project.id, rows=[])
    training = TrainingGapSummaryRead(
        project_id=project.id,
        total_training_gaps=2,
        mandatory_training_incomplete=2,
        expired_or_failed_training=0,
        expired_certifications=0,
        pending_certification_reviews=0,
        rows=[],
    )

    with (
        patch(
            "app.services.workforce_gaps.build_project_skill_matrix",
            new=AsyncMock(return_value=matrix),
        ),
        patch(
            "app.services.workforce_gaps.build_project_training_gaps",
            new=AsyncMock(return_value=training),
        ),
    ):
        candidates = await detect_gap_candidates(session, project, user)

    training_gaps = [c for c in candidates if c.gap_type == CapabilityGapType.TRAINING_GAP]
    assert len(training_gaps) == 1
    assert training_gaps[0].severity == CapabilityGapSeverity.MEDIUM


@pytest.mark.asyncio
async def test_detect_certification_gap_from_summary() -> None:
    org_a = uuid4()
    project = _project(org_a)
    user = _user(AppRole.DELIVERY_MANAGER, org_a)
    session = FakeSession()
    matrix = SkillMatrixRead(project_id=project.id, rows=[])
    training = TrainingGapSummaryRead(
        project_id=project.id,
        total_training_gaps=1,
        mandatory_training_incomplete=0,
        expired_or_failed_training=0,
        expired_certifications=1,
        pending_certification_reviews=1,
        rows=[],
    )

    with (
        patch(
            "app.services.workforce_gaps.build_project_skill_matrix",
            new=AsyncMock(return_value=matrix),
        ),
        patch(
            "app.services.workforce_gaps.build_project_training_gaps",
            new=AsyncMock(return_value=training),
        ),
    ):
        candidates = await detect_gap_candidates(session, project, user)

    cert_gaps = [c for c in candidates if c.gap_type == CapabilityGapType.CERTIFICATION_GAP]
    assert len(cert_gaps) == 1


@pytest.mark.asyncio
async def test_detect_utilization_overload_and_underload() -> None:
    org_a = uuid4()
    project = _project(org_a)
    user = _user(AppRole.DELIVERY_MANAGER, org_a)
    team_over = uuid4()
    team_under = uuid4()
    session = FakeSession(
        utilization=[
            UtilizationSnapshot(
                id=uuid4(),
                org_id=org_a,
                project_id=project.id,
                team_id=team_over,
                annotator_id=None,
                snapshot_date=date.today(),
                allocated_hours=Decimal("90"),
                available_hours=Decimal("100"),
                utilization_pct=Decimal("105"),
            ),
            UtilizationSnapshot(
                id=uuid4(),
                org_id=org_a,
                project_id=project.id,
                team_id=team_under,
                annotator_id=None,
                snapshot_date=date.today(),
                allocated_hours=Decimal("20"),
                available_hours=Decimal("40"),
                utilization_pct=Decimal("50"),
            ),
        ],
    )
    matrix = SkillMatrixRead(project_id=project.id, rows=[])
    training = TrainingGapSummaryRead(
        project_id=project.id,
        total_training_gaps=0,
        mandatory_training_incomplete=0,
        expired_or_failed_training=0,
        expired_certifications=0,
        pending_certification_reviews=0,
        rows=[],
    )

    with (
        patch(
            "app.services.workforce_gaps.build_project_skill_matrix",
            new=AsyncMock(return_value=matrix),
        ),
        patch(
            "app.services.workforce_gaps.build_project_training_gaps",
            new=AsyncMock(return_value=training),
        ),
    ):
        candidates = await detect_gap_candidates(session, project, user)

    overload = [c for c in candidates if c.gap_type == CapabilityGapType.UTILIZATION_OVERLOAD]
    underload = [c for c in candidates if c.gap_type == CapabilityGapType.UTILIZATION_UNDERLOAD]
    assert len(overload) == 1
    assert overload[0].severity == CapabilityGapSeverity.HIGH
    assert len(underload) == 1
    assert underload[0].severity == CapabilityGapSeverity.LOW


@pytest.mark.asyncio
async def test_duplicate_open_gap_prevention() -> None:
    org_a = uuid4()
    project = _project(org_a)
    skill_id = uuid4()
    existing = CapabilityGap(
        id=uuid4(),
        org_id=org_a,
        project_id=project.id,
        skill_id=skill_id,
        gap_type=CapabilityGapType.SKILL_SHORTAGE,
        severity=CapabilityGapSeverity.MEDIUM,
        title="Existing",
        detail="Existing gap",
        status=CapabilityGapStatus.OPEN,
        detected_at=datetime.now(timezone.utc),
    )
    session = FakeSession()
    candidates = [
        GapCandidate(
            gap_type=CapabilityGapType.SKILL_SHORTAGE,
            severity=CapabilityGapSeverity.MEDIUM,
            title="New",
            detail="New gap",
            skill_id=skill_id,
        ),
    ]
    existing_by_key = {("skill_shortage", None, skill_id): existing}

    gaps, created_count = await _persist_candidates(session, project, candidates, existing_by_key)

    assert created_count == 0
    assert len(gaps) == 1
    assert gaps[0].id == existing.id
    assert len(session.added) == 0


@pytest.mark.asyncio
async def test_update_capability_gap_sets_resolved_at() -> None:
    org_a = uuid4()
    user = _user(AppRole.DELIVERY_MANAGER, org_a)
    gap = CapabilityGap(
        id=uuid4(),
        org_id=org_a,
        project_id=uuid4(),
        gap_type=CapabilityGapType.TRAINING_GAP,
        severity=CapabilityGapSeverity.MEDIUM,
        title="Training gaps",
        detail="detail",
        status=CapabilityGapStatus.OPEN,
        detected_at=datetime.now(timezone.utc),
    )
    session = FakeSession(gap=gap)

    updated = await update_capability_gap(
        session,
        gap,
        CapabilityGapUpdate(status=CapabilityGapStatus.RESOLVED),
        user,
    )
    assert updated.status == CapabilityGapStatus.RESOLVED
    assert updated.resolved_at is not None

    updated = await update_capability_gap(
        session,
        gap,
        CapabilityGapUpdate(status=CapabilityGapStatus.OPEN),
        user,
    )
    assert updated.resolved_at is None


@pytest.mark.asyncio
async def test_get_capability_gap_cross_org_returns_404() -> None:
    org_a = uuid4()
    org_b = uuid4()
    gap = CapabilityGap(
        id=uuid4(),
        org_id=org_a,
        project_id=uuid4(),
        gap_type=CapabilityGapType.TRAINING_GAP,
        severity=CapabilityGapSeverity.MEDIUM,
        title="Training gaps",
        detail="detail",
        status=CapabilityGapStatus.OPEN,
        detected_at=datetime.now(timezone.utc),
    )
    session = FakeSession(gap=gap)
    user = _user(AppRole.DELIVERY_MANAGER, org_b)

    with pytest.raises(ApiError) as exc:
        await get_capability_gap_or_404(session, gap.id, user, for_mutation=True)

    assert exc.value.status_code == 404


@pytest.mark.asyncio
async def test_leadership_can_read_gap_but_not_mutate_via_service() -> None:
    org_a = uuid4()
    gap = CapabilityGap(
        id=uuid4(),
        org_id=org_a,
        project_id=uuid4(),
        gap_type=CapabilityGapType.TRAINING_GAP,
        severity=CapabilityGapSeverity.MEDIUM,
        title="Training gaps",
        detail="detail",
        status=CapabilityGapStatus.OPEN,
        detected_at=datetime.now(timezone.utc),
    )
    session = FakeSession(gap=gap)
    leadership = _user(AppRole.BSG_LEADERSHIP, org_a)

    result = await get_capability_gap_or_404(session, gap.id, leadership)
    assert result.id == gap.id

    with pytest.raises(ApiError) as exc:
        await get_capability_gap_or_404(session, gap.id, leadership, for_mutation=True)
    assert exc.value.status_code == 403


@pytest.mark.asyncio
async def test_detect_creates_risk_alert_for_high_severity_gap() -> None:
    org_a = uuid4()
    project = _project(org_a)
    user = _user(AppRole.DELIVERY_MANAGER, org_a)
    session = FakeSession()
    skill = _skill(org_a)
    matrix = SkillMatrixRead(
        project_id=project.id,
        rows=[_matrix_row(skill.id, skill.name, available=3, required=3, sme_available=0, sme_required=2)],
    )
    training = TrainingGapSummaryRead(
        project_id=project.id,
        total_training_gaps=0,
        mandatory_training_incomplete=0,
        expired_or_failed_training=0,
        expired_certifications=0,
        pending_certification_reviews=0,
        rows=[],
    )

    with (
        patch(
            "app.services.workforce_gaps.build_project_skill_matrix",
            new=AsyncMock(return_value=matrix),
        ),
        patch(
            "app.services.workforce_gaps.build_project_training_gaps",
            new=AsyncMock(return_value=training),
        ),
    ):
        result = await detect_and_persist_capability_gaps(session, project, user)

    assert result.created_count >= 1
    assert result.risk_alerts_created >= 1
    assert result.recommendations_created >= 1
    assert any(isinstance(obj, RiskAlert) for obj in session.added)
    assert any(isinstance(obj, MitigationRecommendation) for obj in session.added)


@pytest.mark.asyncio
async def test_list_project_capability_gaps_scoped_to_org_for_dm() -> None:
    org_a = uuid4()
    org_b = uuid4()
    project = _project(org_a)
    user = _user(AppRole.DELIVERY_MANAGER, org_a)
    gaps = [
        CapabilityGap(
            id=uuid4(),
            org_id=org_a,
            project_id=project.id,
            gap_type=CapabilityGapType.TRAINING_GAP,
            severity=CapabilityGapSeverity.MEDIUM,
            title="Org A gap",
            detail="detail",
            status=CapabilityGapStatus.OPEN,
            detected_at=datetime.now(timezone.utc),
        ),
        CapabilityGap(
            id=uuid4(),
            org_id=org_b,
            project_id=project.id,
            gap_type=CapabilityGapType.TRAINING_GAP,
            severity=CapabilityGapSeverity.MEDIUM,
            title="Org B gap",
            detail="detail",
            status=CapabilityGapStatus.OPEN,
            detected_at=datetime.now(timezone.utc),
        ),
    ]
    session = FakeSession(gaps=gaps, filter_org_id=org_a)

    listed = await list_project_capability_gaps(session, project, user)
    assert len(listed) == 1
    assert listed[0].org_id == org_a


@pytest.mark.asyncio
async def test_client_cannot_list_capability_gaps_http(api_client: AsyncClient, client_a) -> None:
    override_user(client_a)
    response = await api_client.get(f"/api/v1/projects/{uuid4()}/capability-gaps")
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "FORBIDDEN"


@pytest.mark.asyncio
async def test_client_cannot_detect_capability_gaps_http(api_client: AsyncClient, client_a) -> None:
    override_user(client_a)
    response = await api_client.post(f"/api/v1/projects/{uuid4()}/capability-gaps/detect")
    assert response.status_code == 403


@pytest.mark.asyncio
async def test_client_cannot_update_capability_gap_http(api_client: AsyncClient, client_a) -> None:
    override_user(client_a)
    response = await api_client.patch(
        f"/api/v1/capability-gaps/{uuid4()}",
        json={"status": "resolved"},
    )
    assert response.status_code == 403


@pytest.mark.asyncio
async def test_client_cannot_delete_capability_gap_http(api_client: AsyncClient, client_a) -> None:
    override_user(client_a)
    response = await api_client.delete(f"/api/v1/capability-gaps/{uuid4()}")
    assert response.status_code == 403


@pytest.mark.asyncio
async def test_leadership_cannot_detect_capability_gaps_http(api_client: AsyncClient) -> None:
    leadership = CurrentUser(
        id=uuid4(),
        org_id=ORG_A,
        email="leadership@example.com",
        role=AppRole.BSG_LEADERSHIP,
        is_active=True,
    )
    override_user(leadership)
    response = await api_client.post(f"/api/v1/projects/{uuid4()}/capability-gaps/detect")
    assert response.status_code == 403


@pytest.mark.asyncio
async def test_leadership_cannot_generate_recommendations_http(api_client: AsyncClient) -> None:
    leadership = CurrentUser(
        id=uuid4(),
        org_id=ORG_A,
        email="leadership@example.com",
        role=AppRole.BSG_LEADERSHIP,
        is_active=True,
    )
    override_user(leadership)
    response = await api_client.post(f"/api/v1/projects/{uuid4()}/workforce-recommendations/generate")
    assert response.status_code == 403
