"""Client Intelligence evidence contracts, reporting period, and pack assembler."""

from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest

from app.agents.client_intelligence import (
    ClientEvidencePack,
    ClientEvidenceReference,
    DataQualityIssue,
    DataQualityState,
    EvidenceVisibility,
    SourceAgent,
    build_client_evidence_pack,
    resolve_reporting_period,
)
from app.agents.client_intelligence.evidence_pack import _fingerprint
from app.core.exceptions import ApiError
from app.core.security import CurrentUser
from app.db.models import (
    AlertStatus,
    AlertType,
    AppRole,
    MilestoneStatus,
    ProjectStatus,
    RiskTier,
)

# ---------------------------------------------------------------------------
# Fixtures / fakes
# ---------------------------------------------------------------------------


class FakeScalars:
    def __init__(self, items: list[object] | None = None) -> None:
        self._items = items or []

    def all(self) -> list[object]:
        return list(self._items)

    def __iter__(self):
        return iter(self._items)


class FakeResult:
    def __init__(self, value: object = None, items: list[object] | None = None) -> None:
        self._value = value
        self._items = items or []

    def scalar_one_or_none(self) -> object:
        return self._value

    def scalars(self) -> FakeScalars:
        return FakeScalars(self._items)

    def all(self) -> list[object]:
        return list(self._items)


class FakeSession:
    """Routes SELECT results by compiled FROM clause (bounded query inspection)."""

    def __init__(
        self,
        *,
        milestones: list[object] | None = None,
        throughput: object | None = None,
        confidence: object | None = None,
        risks: list[object] | None = None,
        bottlenecks: list[object] | None = None,
    ) -> None:
        self.milestones = milestones or []
        self.throughput = throughput
        self.confidence = confidence
        self.risks = risks or []
        self.bottlenecks = bottlenecks or []
        self.statements: list[str] = []

    async def execute(self, stmt) -> FakeResult:
        compiled = str(stmt.compile(compile_kwargs={"literal_binds": True}))
        self.statements.append(compiled)
        if "FROM milestones" in compiled:
            assert "LIMIT" in compiled.upper() or "limit" in compiled
            assert "ORDER BY" in compiled.upper() or "order by" in compiled
            return FakeResult(None, self.milestones)
        if "FROM throughput_snapshots" in compiled:
            assert "LIMIT" in compiled.upper() or "limit" in compiled
            return FakeResult(self.throughput)
        if "FROM delivery_confidence_scores" in compiled:
            assert "LIMIT" in compiled.upper() or "limit" in compiled
            return FakeResult(self.confidence)
        if "FROM risk_alerts" in compiled:
            assert "LIMIT" in compiled.upper() or "limit" in compiled
            assert "ORDER BY" in compiled.upper() or "order by" in compiled
            return FakeResult(None, self.risks)
        if "FROM bottlenecks" in compiled:
            assert "LIMIT" in compiled.upper() or "limit" in compiled
            assert "ORDER BY" in compiled.upper() or "order by" in compiled
            return FakeResult(None, self.bottlenecks)
        return FakeResult(None, [])


def _user(role: AppRole, org_id=None) -> CurrentUser:
    return CurrentUser(
        id=uuid4(),
        org_id=org_id or uuid4(),
        email="ci-test@example.com",
        role=role,
        is_active=True,
    )


def _project(org_id=None) -> SimpleNamespace:
    return SimpleNamespace(
        id=uuid4(),
        org_id=org_id or uuid4(),
        name="Aurora Labeling",
        status=ProjectStatus.ACTIVE,
        description="INTERNAL NOTE — never expose",
    )


def _milestone(project_id, **kwargs) -> SimpleNamespace:
    data = {
        "id": uuid4(),
        "project_id": project_id,
        "name": "Batch 14 QA",
        "description": "Internal milestone note",
        "planned_date": date(2026, 6, 24),
        "actual_date": None,
        "status": MilestoneStatus.ON_TRACK,
        "deleted_at": None,
        "updated_at": datetime(2026, 6, 20, tzinfo=UTC),
    }
    data.update(kwargs)
    return SimpleNamespace(**data)


def _throughput(project_id, **kwargs) -> SimpleNamespace:
    data = {
        "id": uuid4(),
        "project_id": project_id,
        "snapshot_date": date(2026, 6, 18),
        "units_completed": 120,
        "units_forecast": 130,
        "rolling_7day_units": 80,
    }
    data.update(kwargs)
    return SimpleNamespace(**data)


def _confidence(project_id, milestone_id, **kwargs) -> SimpleNamespace:
    data = {
        "id": uuid4(),
        "project_id": project_id,
        "milestone_id": milestone_id,
        "score_pct": Decimal("92.50"),
        "status": MilestoneStatus.ON_TRACK,
        "forecast_completion_date": date(2026, 6, 24),
        "model_version": "delivery-v1",
        "created_at": datetime(2026, 6, 18, 12, 0, tzinfo=UTC),
    }
    data.update(kwargs)
    return SimpleNamespace(**data)


def _risk(project_id, **kwargs) -> SimpleNamespace:
    data = {
        "id": uuid4(),
        "project_id": project_id,
        "milestone_id": None,
        "alert_type": AlertType.DELIVERY_RISK,
        "risk_tier": RiskTier.HIGH,
        "title": "Backlog pressure",
        "detail": "INTERNAL: annotator fatigue on team Kosovo-A",
        "contributing_causes": {"reviewer_id": str(uuid4())},
        "status": AlertStatus.OPEN,
        "created_at": datetime(2026, 6, 17, tzinfo=UTC),
        "deleted_at": None,
    }
    data.update(kwargs)
    return SimpleNamespace(**data)


def _bottleneck(project_id, **kwargs) -> SimpleNamespace:
    data = {
        "id": uuid4(),
        "project_id": project_id,
        "team_id": uuid4(),
        "title": "QA queue",
        "detail": "INTERNAL: reviewer Alice overloaded",
        "status": AlertStatus.OPEN,
        "created_at": datetime(2026, 6, 16, tzinfo=UTC),
        "deleted_at": None,
        "resolved_by": uuid4(),
    }
    data.update(kwargs)
    return SimpleNamespace(**data)


# ---------------------------------------------------------------------------
# Contracts
# ---------------------------------------------------------------------------


def test_contracts_json_serializable() -> None:
    ref = ClientEvidenceReference(
        source_agent=SourceAgent.DELIVERY_PERFORMANCE,
        source_table="projects",
        source_row_id=uuid4(),
        description="Project identity",
        visibility=EvidenceVisibility.CLIENT_SAFE,
        claim_keys=["project_id"],
    )
    issue = DataQualityIssue(
        source="throughput_snapshots",
        state=DataQualityState.UNAVAILABLE,
        detail="Missing",
    )
    payload = {
        "ref": ref.model_dump(mode="json"),
        "issue": issue.model_dump(mode="json"),
        "visibility": list(EvidenceVisibility),
        "states": list(DataQualityState),
    }
    assert payload["ref"]["visibility"] == "client_safe"
    assert payload["issue"]["state"] == "unavailable"
    assert EvidenceVisibility.INTERNAL.value == "internal"
    assert DataQualityState.CONFLICTING.value == "conflicting"


def test_contracts_no_mutable_shared_defaults() -> None:
    left = ClientEvidenceReference(
        source_agent=SourceAgent.CLIENT_INTELLIGENCE,
        source_table="projects",
        source_row_id=uuid4(),
        description="a",
        visibility=EvidenceVisibility.INTERNAL,
    )
    right = ClientEvidenceReference(
        source_agent=SourceAgent.CLIENT_INTELLIGENCE,
        source_table="projects",
        source_row_id=uuid4(),
        description="b",
        visibility=EvidenceVisibility.INTERNAL,
    )
    left.claim_keys.append("x")
    assert right.claim_keys == []


# ---------------------------------------------------------------------------
# Reporting period
# ---------------------------------------------------------------------------


def test_reporting_period_weekday() -> None:
    period = resolve_reporting_period(date(2026, 6, 17))  # Wednesday
    assert period.start_date == date(2026, 6, 15)
    assert period.end_date == date(2026, 6, 21)
    assert period.previous_start_date == date(2026, 6, 8)
    assert period.previous_end_date == date(2026, 6, 14)
    assert period.as_of == date(2026, 6, 17)


def test_reporting_period_monday() -> None:
    period = resolve_reporting_period(date(2026, 6, 15))
    assert period.start_date == date(2026, 6, 15)
    assert period.end_date == date(2026, 6, 21)


def test_reporting_period_sunday() -> None:
    period = resolve_reporting_period(date(2026, 6, 21))
    assert period.start_date == date(2026, 6, 15)
    assert period.end_date == date(2026, 6, 21)


def test_reporting_period_month_boundary() -> None:
    period = resolve_reporting_period(date(2026, 7, 1))  # Wednesday
    assert period.start_date == date(2026, 6, 29)
    assert period.end_date == date(2026, 7, 5)
    assert period.previous_start_date == date(2026, 6, 22)
    assert period.previous_end_date == date(2026, 6, 28)


def test_reporting_period_year_boundary() -> None:
    period = resolve_reporting_period(date(2026, 1, 1))  # Thursday
    assert period.start_date == date(2025, 12, 29)
    assert period.end_date == date(2026, 1, 4)
    assert period.previous_start_date == date(2025, 12, 22)
    assert period.previous_end_date == date(2025, 12, 28)


# ---------------------------------------------------------------------------
# Assembler
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_assembler_calls_project_authorization() -> None:
    project = _project()
    user = _user(AppRole.DELIVERY_MANAGER, project.org_id)
    session = FakeSession()
    with patch(
        "app.agents.client_intelligence.evidence_pack.get_visible_project",
        new=AsyncMock(return_value=project),
    ) as mocked:
        await build_client_evidence_pack(session, user, project.id, as_of=date(2026, 6, 18))
        mocked.assert_awaited_once()
        assert mocked.await_args.args[1] == project.id
        assert mocked.await_args.args[2] is user


@pytest.mark.asyncio
async def test_client_role_forces_client_safe_mode() -> None:
    project = _project()
    user = _user(AppRole.CLIENT, project.org_id)
    milestone = _milestone(project.id)
    risk = _risk(project.id)
    bottleneck = _bottleneck(project.id)
    session = FakeSession(
        milestones=[milestone],
        throughput=_throughput(project.id),
        confidence=_confidence(project.id, milestone.id),
        risks=[risk],
        bottlenecks=[bottleneck],
    )
    with patch(
        "app.agents.client_intelligence.evidence_pack.get_visible_project",
        new=AsyncMock(return_value=project),
    ):
        pack = await build_client_evidence_pack(
            session,
            user,
            project.id,
            as_of=date(2026, 6, 18),
            visibility_mode=EvidenceVisibility.INTERNAL,  # must be ignored
        )
    assert pack.visibility_mode == EvidenceVisibility.CLIENT_SAFE
    assert all(item.visibility == EvidenceVisibility.CLIENT_SAFE for item in pack.evidence)
    assert pack.delivery.open_risks == []
    assert pack.delivery.open_bottlenecks == []
    assert pack.delivery.latest_throughput is None
    assert pack.delivery.latest_delivery_confidence is None
    assert pack.delivery.milestones[0].description is None
    assert pack.policy_fingerprint is not None
    dump = pack.model_dump(mode="json")
    blob = str(dump).lower()
    assert "annotator" not in blob
    assert "reviewer" not in blob
    assert "alice" not in blob
    assert "kosovo-a" not in blob
    assert "fatigue" not in blob
    assert "backlog pressure" not in blob
    assert "qa queue" not in blob
    assert any(item.source == "risk_alerts" for item in pack.visibility_limitations)
    assert any(item.source == "bottlenecks" for item in pack.visibility_limitations)
    # Visibility redaction is not a data-quality failure for risks.
    assert not any(
        issue.source == "risk_alerts" and issue.state == DataQualityState.UNAVAILABLE
        for issue in pack.data_quality
    )


@pytest.mark.asyncio
async def test_internal_role_can_receive_internal_mode() -> None:
    project = _project()
    user = _user(AppRole.DELIVERY_MANAGER, project.org_id)
    risk = _risk(project.id)
    bottleneck = _bottleneck(project.id)
    session = FakeSession(
        milestones=[_milestone(project.id)],
        risks=[risk],
        bottlenecks=[bottleneck],
    )
    with patch(
        "app.agents.client_intelligence.evidence_pack.get_visible_project",
        new=AsyncMock(return_value=project),
    ):
        pack = await build_client_evidence_pack(
            session,
            user,
            project.id,
            as_of=date(2026, 6, 18),
            visibility_mode=EvidenceVisibility.INTERNAL,
        )
    assert pack.visibility_mode == EvidenceVisibility.INTERNAL
    assert pack.policy_fingerprint is None
    assert pack.delivery.open_risks[0].detail == risk.detail
    assert pack.delivery.open_bottlenecks[0].detail == bottleneck.detail
    assert any(item.visibility == EvidenceVisibility.INTERNAL for item in pack.evidence)
    # Internal evidence descriptions must not embed raw titles (avoid accidental leakage).
    risk_evidence = [item for item in pack.evidence if item.source_table == "risk_alerts"]
    assert risk_evidence
    assert risk.title not in risk_evidence[0].description


@pytest.mark.asyncio
async def test_past_as_of_adds_historical_status_limitation_internal() -> None:
    project = _project()
    user = _user(AppRole.DELIVERY_MANAGER, project.org_id)
    session = FakeSession(milestones=[_milestone(project.id)], risks=[_risk(project.id)])
    with patch(
        "app.agents.client_intelligence.evidence_pack.get_visible_project",
        new=AsyncMock(return_value=project),
    ):
        pack = await build_client_evidence_pack(
            session,
            user,
            project.id,
            as_of=date(2026, 1, 1),
            visibility_mode=EvidenceVisibility.INTERNAL,
        )
    assert any("status history" in item.lower() for item in pack.limitations)


@pytest.mark.asyncio
async def test_missing_throughput_and_confidence_do_not_fabricate() -> None:
    project = _project()
    user = _user(AppRole.DELIVERY_MANAGER, project.org_id)
    session = FakeSession(milestones=[])
    with patch(
        "app.agents.client_intelligence.evidence_pack.get_visible_project",
        new=AsyncMock(return_value=project),
    ):
        pack = await build_client_evidence_pack(session, user, project.id, as_of=date(2026, 6, 18))
    assert pack.delivery.latest_throughput is None
    assert pack.delivery.latest_delivery_confidence is None
    assert pack.delivery.next_milestone_id is None
    states = {issue.source: issue.state for issue in pack.data_quality}
    assert states["throughput_snapshots"] == DataQualityState.UNAVAILABLE
    assert states["delivery_confidence_scores"] == DataQualityState.UNAVAILABLE
    assert pack.overall_data_quality == DataQualityState.UNAVAILABLE
    assert any("throughput" in item.lower() for item in pack.limitations)
    assert any("confidence" in item.lower() for item in pack.limitations)


@pytest.mark.asyncio
async def test_evidence_row_ids_match_included_facts() -> None:
    project = _project()
    user = _user(AppRole.DELIVERY_MANAGER, project.org_id)
    milestone = _milestone(project.id)
    throughput = _throughput(project.id)
    confidence = _confidence(project.id, milestone.id)
    risk = _risk(project.id)
    bottleneck = _bottleneck(project.id)
    session = FakeSession(
        milestones=[milestone],
        throughput=throughput,
        confidence=confidence,
        risks=[risk],
        bottlenecks=[bottleneck],
    )
    with patch(
        "app.agents.client_intelligence.evidence_pack.get_visible_project",
        new=AsyncMock(return_value=project),
    ):
        pack = await build_client_evidence_pack(session, user, project.id, as_of=date(2026, 6, 18))
    by_table = {item.source_table: item.source_row_id for item in pack.evidence}
    assert by_table["projects"] == project.id
    assert by_table["milestones"] == milestone.id
    assert by_table["throughput_snapshots"] == throughput.id
    assert by_table["delivery_confidence_scores"] == confidence.id
    assert by_table["risk_alerts"] == risk.id
    assert by_table["bottlenecks"] == bottleneck.id
    assert pack.delivery.latest_throughput is not None
    assert pack.delivery.latest_throughput.id == throughput.id
    assert pack.delivery.latest_delivery_confidence is not None
    assert pack.delivery.latest_delivery_confidence.id == confidence.id
    assert pack.delivery.next_milestone_id == milestone.id


@pytest.mark.asyncio
async def test_fingerprint_stable_when_evidence_order_changes() -> None:
    project_id = uuid4()
    a = ClientEvidenceReference(
        source_agent=SourceAgent.DELIVERY_PERFORMANCE,
        source_table="milestones",
        source_row_id=uuid4(),
        description="m1",
        visibility=EvidenceVisibility.CLIENT_SAFE,
    )
    b = ClientEvidenceReference(
        source_agent=SourceAgent.DELIVERY_PERFORMANCE,
        source_table="throughput_snapshots",
        source_row_id=uuid4(),
        description="t1",
        visibility=EvidenceVisibility.CLIENT_SAFE,
    )
    left = _fingerprint(
        project_id=project_id,
        reporting_period_start=date(2026, 6, 15),
        reporting_period_end=date(2026, 6, 21),
        visibility_mode=EvidenceVisibility.CLIENT_SAFE,
        evidence=[a, b],
    )
    right = _fingerprint(
        project_id=project_id,
        reporting_period_start=date(2026, 6, 15),
        reporting_period_end=date(2026, 6, 21),
        visibility_mode=EvidenceVisibility.CLIENT_SAFE,
        evidence=[b, a],
    )
    assert left == right


@pytest.mark.asyncio
async def test_cross_tenant_access_rejected_via_scoping() -> None:
    project = _project()
    user = _user(AppRole.DELIVERY_MANAGER, uuid4())
    session = FakeSession()
    forbidden = ApiError(403, "FORBIDDEN", "Authenticated user lacks permission.")
    with (
        patch(
            "app.agents.client_intelligence.evidence_pack.get_visible_project",
            new=AsyncMock(side_effect=forbidden),
        ),
        pytest.raises(ApiError) as exc,
    ):
        await build_client_evidence_pack(session, user, project.id, as_of=date(2026, 6, 18))
    assert exc.value.status_code == 403
    assert session.statements == []


@pytest.mark.asyncio
async def test_pack_excludes_project_description_and_is_serializable() -> None:
    project = _project()
    user = _user(AppRole.BSG_LEADERSHIP, project.org_id)
    session = FakeSession(milestones=[_milestone(project.id)])
    with patch(
        "app.agents.client_intelligence.evidence_pack.get_visible_project",
        new=AsyncMock(return_value=project),
    ):
        pack = await build_client_evidence_pack(session, user, project.id, as_of=date(2026, 6, 18))
    assert isinstance(pack, ClientEvidencePack)
    dumped = pack.model_dump(mode="json")
    assert "description" not in dumped["project"]
    assert "INTERNAL NOTE" not in str(dumped)
    assert pack.source_fingerprint
    assert pack.generated_at.tzinfo is not None
