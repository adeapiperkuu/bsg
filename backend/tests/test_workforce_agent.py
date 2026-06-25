from datetime import date, datetime, timezone
from decimal import Decimal
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest
from httpx import AsyncClient

from app.core.exceptions import ApiError
from app.core.security import CurrentUser
from app.db.models import (
    AgentQuery,
    AgentQueryEvidenceLink,
    AlertType,
    Annotator,
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
    Team,
    UtilizationSnapshot,
)
from app.schemas.domain import (
    AgentQueryCreate,
    SkillMatrixRead,
    SkillMatrixRow,
    TrainingGapSummaryRead,
)
from app.services.agent_queries import SUPPORTED_AGENTS
from app.services.workforce_agent import (
    WORKFORCE_AGENT_NAME,
    WorkforceEvidenceBundle,
    WorkforceMetrics,
    answer_workforce_query,
    build_workforce_answer,
    classify_workforce_question,
    gather_workforce_evidence,
)
from tests.conftest import ORG_A, ORG_B, client_a, override_user


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
        name="Radiology Program",
        vertical="medical",
        status="active",
        start_date="2026-01-01",
        target_end_date="2026-12-31",
    )


def _team(org_id, project_id, *, name="Radiology Pod A") -> Team:
    return Team(
        id=uuid4(),
        org_id=org_id,
        project_id=project_id,
        name=name,
        site=DeliverySite.INDIA,
        domain="radiology",
        is_active=True,
    )


def _annotator(org_id, team_id, *, name="Priya Sharma", sme=False) -> Annotator:
    return Annotator(
        id=uuid4(),
        org_id=org_id,
        team_id=team_id,
        full_name=name,
        site=DeliverySite.INDIA,
        is_sme_certified=sme,
        is_active=True,
    )


def _snapshot(org_id, project_id, team_id, pct) -> UtilizationSnapshot:
    return UtilizationSnapshot(
        id=uuid4(),
        org_id=org_id,
        project_id=project_id,
        team_id=team_id,
        annotator_id=None,
        snapshot_date=date.today(),
        allocated_hours=Decimal("90"),
        available_hours=Decimal("100"),
        utilization_pct=Decimal(str(pct)),
    )


def _requirement(org_id, project_id) -> ProjectSkillRequirement:
    return ProjectSkillRequirement(
        id=uuid4(),
        org_id=org_id,
        project_id=project_id,
        skill_id=uuid4(),
        required_proficiency_level=ProficiencyLevel.ADVANCED,
        required_headcount=3,
        required_sme_count=1,
    )


def _gap(org_id, project_id, *, severity=CapabilityGapSeverity.HIGH) -> CapabilityGap:
    return CapabilityGap(
        id=uuid4(),
        org_id=org_id,
        project_id=project_id,
        gap_type=CapabilityGapType.SME_SHORTAGE,
        severity=severity,
        title="SME shortage: Radiology QA",
        detail="Available SMEs below required.",
        status=CapabilityGapStatus.OPEN,
        detected_at=datetime.now(timezone.utc),
    )


def _risk_alert(org_id, project_id) -> RiskAlert:
    return RiskAlert(
        id=uuid4(),
        org_id=org_id,
        project_id=project_id,
        alert_type=AlertType.WORKFORCE_IMBALANCE,
        risk_tier="high",
        title="Rebalance workforce allocation",
        detail="Workforce imbalance detected.",
        status="open",
    )


def _recommendation(org_id, project_id, risk_id) -> MitigationRecommendation:
    return MitigationRecommendation(
        id=uuid4(),
        org_id=org_id,
        project_id=project_id,
        title="Rebalance workforce allocation",
        description="Shift capacity across teams.",
        severity="high",
        confidence_score=Decimal("0.750"),
        status="pending",
        source_risk_id=risk_id,
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
        self.project = kwargs.get("project")
        self.teams = kwargs.get("teams", [])
        self.annotators = kwargs.get("annotators", [])
        self.snapshots = kwargs.get("snapshots", [])
        self.requirements = kwargs.get("requirements", [])
        self.gaps = kwargs.get("gaps", [])
        self.risk_alerts = kwargs.get("risk_alerts", [])
        self.recommendations = kwargs.get("recommendations", [])
        self.added: list[object] = []

    def add(self, obj: object) -> None:
        self.added.append(obj)
        if isinstance(obj, AgentQuery) and obj.id is None:
            obj.id = uuid4()

    async def flush(self) -> None:
        return None

    async def execute(self, stmt):
        compiled = str(stmt.compile(compile_kwargs={"literal_binds": True}))
        if "FROM projects" in compiled:
            return FakeResult(self.project)
        if "FROM teams" in compiled:
            return FakeResult(None, self.teams)
        if "FROM annotators" in compiled:
            return FakeResult(None, self.annotators)
        if "FROM utilization_snapshots" in compiled:
            return FakeResult(None, self.snapshots)
        if "FROM project_skill_requirements" in compiled:
            return FakeResult(None, self.requirements)
        if "FROM capability_gaps" in compiled:
            return FakeResult(None, self.gaps)
        if "FROM risk_alerts" in compiled:
            return FakeResult(None, self.risk_alerts)
        if "FROM mitigation_recommendations" in compiled:
            return FakeResult(None, self.recommendations)
        return FakeResult(None, [])


def _empty_matrix(project_id) -> SkillMatrixRead:
    return SkillMatrixRead(project_id=project_id, rows=[])


def _matrix_with_low(project_id) -> SkillMatrixRead:
    return SkillMatrixRead(
        project_id=project_id,
        rows=[
            SkillMatrixRow(
                skill_id=uuid4(),
                skill_name="Radiology QA",
                category="Life Sciences",
                domain="radiology",
                required_proficiency_level=ProficiencyLevel.ADVANCED,
                required_headcount=3,
                available_headcount=0,
                required_sme_count=1,
                available_sme_count=0,
                coverage_status="low",
                by_site=[],
            )
        ],
    )


def _training(project_id, total=0) -> TrainingGapSummaryRead:
    return TrainingGapSummaryRead(
        project_id=project_id,
        total_training_gaps=total,
        mandatory_training_incomplete=total,
        expired_or_failed_training=0,
        expired_certifications=0,
        pending_certification_reviews=0,
        rows=[],
    )


def test_workforce_agent_is_registered() -> None:
    assert WORKFORCE_AGENT_NAME == "workforce_capability_agent"
    assert WORKFORCE_AGENT_NAME in SUPPORTED_AGENTS


def test_classify_delivery_question_redirects_to_delivery_performance() -> None:
    redirect = classify_workforce_question("What is our delivery confidence and slippage?")
    assert redirect is not None
    assert redirect.target_agent == "Delivery Performance Agent"


def test_classify_quality_question_redirects_to_quality_intelligence() -> None:
    redirect = classify_workforce_question("Is there quality drift on the project?")
    assert redirect is not None
    assert redirect.target_agent == "Quality Intelligence Agent"


def test_classify_client_question_redirects_to_client_interaction() -> None:
    redirect = classify_workforce_question("Can you draft a client email update?")
    assert redirect is not None
    assert redirect.target_agent == "Client Interaction Agent"


def test_classify_sop_question_redirects_to_operational_knowledge() -> None:
    redirect = classify_workforce_question("Where is the SOP document for labeling?")
    assert redirect is not None
    assert redirect.target_agent == "Operational Knowledge Agent"


def test_classify_in_scope_question_returns_none() -> None:
    assert classify_workforce_question("What is our SME coverage and capacity?") is None


def test_build_answer_insufficient_data_fallback() -> None:
    bundle = WorkforceEvidenceBundle(
        project_id=uuid4(),
        project_name="Radiology Program",
        metrics=WorkforceMetrics(),
        evidence=[],
    )
    answer = build_workforce_answer("What is our capacity?", bundle)
    assert "not enough workforce evidence" in answer.lower()


def test_build_answer_cites_evidence_count_and_metrics() -> None:
    from app.services.evidence import EvidenceInput

    metrics = WorkforceMetrics(
        active_annotators=12,
        sme_count=4,
        sme_coverage_pct=33,
        team_count=2,
        teams_overloaded=1,
        teams_underloaded=0,
        team_utilization=[("Pod A", 105.0)],
        skill_requirements=3,
        skill_low_coverage=1,
        open_capability_gaps=2,
        high_critical_gaps=1,
    )
    evidence = [
        EvidenceInput(source_table="projects", source_row_id=uuid4(), description="Project."),
        EvidenceInput(source_table="teams", source_row_id=uuid4(), description="Team."),
    ]
    bundle = WorkforceEvidenceBundle(
        project_id=uuid4(),
        project_name="Radiology Program",
        metrics=metrics,
        evidence=evidence,
    )
    answer = build_workforce_answer("What is our capacity?", bundle)
    assert "12 active annotators" in answer
    assert "Grounded in 2 workforce evidence record(s)" in answer


@pytest.mark.asyncio
async def test_client_blocked_from_workforce_agent_service() -> None:
    user = _user(AppRole.CLIENT, ORG_A)
    session = FakeSession()
    payload = AgentQueryCreate(
        agent_name=WORKFORCE_AGENT_NAME,
        project_id=None,
        query_text="What is our SME coverage?",
    )
    with pytest.raises(ApiError) as exc:
        await answer_workforce_query(session, user, payload)
    assert exc.value.status_code == 403


@pytest.mark.asyncio
async def test_client_blocked_from_workforce_agent_http(
    api_client: AsyncClient, client_a
) -> None:
    override_user(client_a)
    response = await api_client.post(
        "/api/v1/agent-queries",
        json={
            "agent_name": WORKFORCE_AGENT_NAME,
            "query_text": "What is our SME coverage?",
        },
    )
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "FORBIDDEN"


@pytest.mark.asyncio
async def test_delivery_manager_can_ask_scoped_question_and_cites_evidence() -> None:
    org_a = uuid4()
    user = _user(AppRole.DELIVERY_MANAGER, org_a)
    project = _project(org_a)
    team = _team(org_a, project.id)
    annotators = [
        _annotator(org_a, team.id, name="Priya Sharma", sme=True),
        _annotator(org_a, team.id, name="Arben Krasniqi", sme=False),
    ]
    session = FakeSession(
        project=project,
        teams=[team],
        annotators=annotators,
        snapshots=[_snapshot(org_a, project.id, team.id, 105)],
        requirements=[_requirement(org_a, project.id)],
        gaps=[_gap(org_a, project.id)],
    )
    payload = AgentQueryCreate(
        agent_name=WORKFORCE_AGENT_NAME,
        project_id=project.id,
        query_text="What is our SME coverage and capacity?",
    )

    with (
        patch(
            "app.services.workforce_agent.build_project_skill_matrix",
            new=AsyncMock(return_value=_matrix_with_low(project.id)),
        ),
        patch(
            "app.services.workforce_agent.build_project_training_gaps",
            new=AsyncMock(return_value=_training(project.id, total=2)),
        ),
    ):
        query = await answer_workforce_query(session, user, payload)

    assert query.agent_name == WORKFORCE_AGENT_NAME
    assert "active annotators" in query.answer_text
    evidence_links = [obj for obj in session.added if isinstance(obj, AgentQueryEvidenceLink)]
    assert len(evidence_links) >= 1
    cited_tables = {link.source_table for link in evidence_links}
    assert "projects" in cited_tables


@pytest.mark.asyncio
async def test_no_individual_annotator_names_in_answer_or_evidence() -> None:
    org_a = uuid4()
    user = _user(AppRole.DELIVERY_MANAGER, org_a)
    project = _project(org_a)
    team = _team(org_a, project.id)
    secret_name = "Priya Sharma"
    annotators = [
        _annotator(org_a, team.id, name=secret_name, sme=True),
        _annotator(org_a, team.id, name="Arben Krasniqi", sme=False),
    ]
    session = FakeSession(
        project=project,
        teams=[team],
        annotators=annotators,
        snapshots=[_snapshot(org_a, project.id, team.id, 92)],
        requirements=[_requirement(org_a, project.id)],
        gaps=[],
    )

    with (
        patch(
            "app.services.workforce_agent.build_project_skill_matrix",
            new=AsyncMock(return_value=_empty_matrix(project.id)),
        ),
        patch(
            "app.services.workforce_agent.build_project_training_gaps",
            new=AsyncMock(return_value=_training(project.id, total=0)),
        ),
    ):
        bundle = await gather_workforce_evidence(session, project, user)
        answer = build_workforce_answer("capacity?", bundle)

    assert secret_name not in answer
    for item in bundle.evidence:
        assert secret_name not in item.description
        assert item.source_table != "annotators"


@pytest.mark.asyncio
async def test_evidence_is_project_scoped() -> None:
    org_a = uuid4()
    user = _user(AppRole.DELIVERY_MANAGER, org_a)
    project = _project(org_a)
    team = _team(org_a, project.id)
    session = FakeSession(
        project=project,
        teams=[team],
        annotators=[],
        snapshots=[_snapshot(org_a, project.id, team.id, 70)],
        requirements=[],
        gaps=[],
    )

    with (
        patch(
            "app.services.workforce_agent.build_project_skill_matrix",
            new=AsyncMock(return_value=_empty_matrix(project.id)),
        ),
        patch(
            "app.services.workforce_agent.build_project_training_gaps",
            new=AsyncMock(return_value=_training(project.id, total=0)),
        ),
    ):
        bundle = await gather_workforce_evidence(session, project, user)

    assert bundle.project_id == project.id
    project_links = [e for e in bundle.evidence if e.source_table == "projects"]
    assert len(project_links) == 1
    assert project_links[0].source_row_id == project.id


@pytest.mark.asyncio
async def test_cross_org_project_blocked() -> None:
    user = _user(AppRole.DELIVERY_MANAGER, ORG_A)
    project = _project(ORG_B)
    session = FakeSession(project=project)
    payload = AgentQueryCreate(
        agent_name=WORKFORCE_AGENT_NAME,
        project_id=project.id,
        query_text="What is our SME coverage?",
    )
    with pytest.raises(ApiError) as exc:
        await answer_workforce_query(session, user, payload)
    assert exc.value.status_code == 403


@pytest.mark.asyncio
async def test_out_of_scope_delivery_question_redirects() -> None:
    user = _user(AppRole.DELIVERY_MANAGER, ORG_A)
    session = FakeSession()
    payload = AgentQueryCreate(
        agent_name=WORKFORCE_AGENT_NAME,
        project_id=None,
        query_text="What is our delivery confidence for the next milestone?",
    )
    query = await answer_workforce_query(session, user, payload)
    assert "Delivery Performance Agent" in query.answer_text


@pytest.mark.asyncio
async def test_out_of_scope_quality_question_redirects() -> None:
    user = _user(AppRole.DELIVERY_MANAGER, ORG_A)
    session = FakeSession()
    payload = AgentQueryCreate(
        agent_name=WORKFORCE_AGENT_NAME,
        project_id=None,
        query_text="Is there quality drift in the labeling output?",
    )
    query = await answer_workforce_query(session, user, payload)
    assert "Quality Intelligence Agent" in query.answer_text


@pytest.mark.asyncio
async def test_insufficient_evidence_fallback_when_no_project() -> None:
    user = _user(AppRole.BSG_LEADERSHIP, ORG_A)
    session = FakeSession()
    payload = AgentQueryCreate(
        agent_name=WORKFORCE_AGENT_NAME,
        project_id=None,
        query_text="What is our SME coverage?",
    )
    query = await answer_workforce_query(session, user, payload)
    assert "Select a project" in query.answer_text
