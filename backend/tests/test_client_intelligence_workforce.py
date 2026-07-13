"""Client Intelligence Workforce & Capability evidence adapter tests."""

from __future__ import annotations

from datetime import UTC, date, datetime, time
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest

from app.agents.client_intelligence import (
    CapabilityGapCountFacts,
    DataQualityState,
    EvidenceVisibility,
    build_client_evidence_pack,
    load_workforce_evidence,
    resolve_reporting_period,
)
from app.agents.client_intelligence import workforce_adapter as workforce_adapter_mod
from app.agents.client_intelligence.evidence_pack import (
    _fingerprint,
    _workforce_fingerprint_projection,
)
from app.agents.client_intelligence.workforce_adapter import _UTILIZATION_CLAIM_KEYS
from app.core.exceptions import ApiError
from app.core.security import CurrentUser
from app.db.models import (
    AppRole,
    CapabilityGapSeverity,
    CapabilityGapStatus,
    CapabilityGapType,
    ProficiencyLevel,
    ProjectStatus,
    SkillRequirementPriority,
    TrainingRecordStatus,
)


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
    def __init__(
        self,
        *,
        as_of: date | None = None,
        teams: list[object] | None = None,
        annotators: list[object] | None = None,
        utilization: list[object] | None = None,
        requirements: list[object] | None = None,
        skills: list[object] | None = None,
        annotator_skills: list[object] | None = None,
        programs: list[object] | None = None,
        training_records: list[object] | None = None,
        gaps: list[object] | None = None,
        milestones: list[object] | None = None,
        metrics: list[object] | None = None,
    ) -> None:
        self.as_of = as_of or date(2026, 6, 18)
        self.as_of_end = datetime.combine(self.as_of, time.max, tzinfo=UTC)
        self.teams = teams or []
        self.annotators = annotators or []
        self.utilization = utilization or []
        self.requirements = requirements or []
        self.skills = skills or []
        self.annotator_skills = annotator_skills or []
        self.programs = programs or []
        self.training_records = training_records or []
        self.gaps = gaps or []
        self.milestones = milestones or []
        self.metrics = metrics or []
        self.statements: list[str] = []

    def _created_ok(self, row: object) -> bool:
        created = getattr(row, "created_at", None)
        return created is None or created <= self.as_of_end

    def _filter_created(self, rows: list[object]) -> list[object]:
        return [row for row in rows if self._created_ok(row)]

    async def execute(self, stmt) -> FakeResult:
        compiled = str(stmt.compile(compile_kwargs={"literal_binds": True}))
        self.statements.append(compiled)
        upper = compiled.upper()
        assert "LIMIT" in upper or "limit" in compiled

        if "FROM teams" in compiled:
            assert "ORDER BY" in upper or "order by" in compiled
            assert "created_at" in compiled.lower()
            return FakeResult(None, self._filter_created(self.teams))
        if "FROM annotators" in compiled:
            assert "full_name" not in compiled.lower()
            assert "ORDER BY" in upper or "order by" in compiled
            assert "created_at" in compiled.lower()
            return FakeResult(None, self._filter_created(self.annotators))
        if "FROM utilization_snapshots" in compiled:
            assert "notes" not in compiled.lower()
            assert "billable_hours" not in compiled.lower()
            assert "non_billable_hours" not in compiled.lower()
            assert "ORDER BY" in upper or "order by" in compiled
            assert "created_at" in compiled.lower()
            rows = []
            for row in self.utilization:
                if getattr(row, "annotator_id", None) is not None:
                    continue
                if getattr(row, "snapshot_date", date.min) > self.as_of:
                    continue
                if not self._created_ok(row):
                    continue
                rows.append(row)
            return FakeResult(None, rows)
        if "FROM project_skill_requirements" in compiled:
            assert "created_at" in compiled.lower()
            return FakeResult(None, self._filter_created(self.requirements))
        if "FROM skills" in compiled:
            assert "created_at" in compiled.lower()
            return FakeResult(None, self._filter_created(self.skills))
        if "FROM annotator_skills" in compiled:
            assert "created_at" in compiled.lower()
            return FakeResult(None, self._filter_created(self.annotator_skills))
        if "FROM training_programs" in compiled:
            assert "created_at" in compiled.lower()
            return FakeResult(None, self._filter_created(self.programs))
        if "FROM training_records" in compiled:
            assert "score_pct" not in compiled.lower()
            assert "created_at" in compiled.lower()
            return FakeResult(None, self._filter_created(self.training_records))
        if "FROM capability_gaps" in compiled:
            assert "title" not in compiled.lower()
            assert "detail" not in compiled.lower()
            assert "evidence" not in compiled.lower()
            rows = [
                row
                for row in self.gaps
                if getattr(row, "detected_at", self.as_of_end) <= self.as_of_end
                and getattr(row, "status", None)
                in {CapabilityGapStatus.OPEN, CapabilityGapStatus.ACKNOWLEDGED}
            ]
            return FakeResult(None, rows)
        if "FROM milestones" in compiled:
            return FakeResult(None, self.milestones)
        if "FROM metric_configurations" in compiled:
            visible = [row for row in self.metrics if getattr(row, "is_client_visible", False)]
            return FakeResult(None, visible)
        if "FROM throughput_snapshots" in compiled:
            return FakeResult(None)
        if "FROM delivery_confidence_scores" in compiled:
            return FakeResult(None)
        if "FROM quality_snapshots" in compiled:
            return FakeResult(None, [])
        if "FROM risk_alerts" in compiled:
            return FakeResult(None, [])
        if "FROM bottlenecks" in compiled:
            return FakeResult(None, [])
        if "FROM knowledge_documents" in compiled:
            assert "extracted_text" not in compiled.lower()
            return FakeResult(None, [])
        if "FROM knowledge_document_versions" in compiled:
            assert "file_name" not in compiled.lower()
            return FakeResult(None, [])
        if "FROM knowledge_document_chunks" in compiled:
            assert "embedding" not in compiled.lower()
            return FakeResult(None, [])
        if "FROM knowledge_document_embeddings" in compiled:
            raise AssertionError("Knowledge embeddings must not be queried")
        if "FROM client_communications" in compiled:
            raise AssertionError("ClientCommunication must not be queried by Knowledge adapter")
        if "FROM project_scope_states" in compiled:
            assert "notes" not in compiled.lower()
            return FakeResult(None, [])
        if "FROM project_charters" in compiled:
            assert "generated_text" not in compiled.lower()
            return FakeResult(None, [])
        if "FROM project_dependencies" in compiled:
            assert "title" not in compiled.lower()
            return FakeResult(None, [])
        if "FROM governance_actions" in compiled:
            assert "title" not in compiled.lower()
            return FakeResult(None, [])
        if "FROM governance_escalations" in compiled:
            assert "title" not in compiled.lower()
            return FakeResult(None, [])
        if "FROM governance_weekly_summaries" in compiled:
            raise AssertionError("Weekly summary must not be queried")
        return FakeResult(None, [])


def _user(role: AppRole, org_id=None) -> CurrentUser:
    return CurrentUser(
        id=uuid4(),
        org_id=org_id or uuid4(),
        email="ci-workforce@example.com",
        role=role,
        is_active=True,
    )


def _project(org_id=None) -> SimpleNamespace:
    return SimpleNamespace(
        id=uuid4(),
        org_id=org_id or uuid4(),
        name="Aurora Labeling",
        status=ProjectStatus.ACTIVE,
        description="INTERNAL",
    )


_PAST = datetime(2026, 1, 1, tzinfo=UTC)
_FUTURE = datetime(2026, 6, 25, tzinfo=UTC)


def _team_row(team_id=None, *, created_at=None) -> SimpleNamespace:
    return SimpleNamespace(id=team_id or uuid4(), created_at=created_at or _PAST)


def _annotator_row(*, team_id, sme=False, annotator_id=None, created_at=None) -> SimpleNamespace:
    return SimpleNamespace(
        id=annotator_id or uuid4(),
        team_id=team_id,
        is_sme_certified=sme,
        is_active=True,
        created_at=created_at or _PAST,
    )


def _util_row(*, team_id, snapshot_date, allocated, available, util_id=None) -> SimpleNamespace:
    available_dec = Decimal(str(available))
    allocated_dec = Decimal(str(allocated))
    pct = (
        Decimal("0")
        if available_dec == 0
        else (allocated_dec / available_dec * Decimal("100")).quantize(Decimal("0.01"))
    )
    return SimpleNamespace(
        id=util_id or uuid4(),
        team_id=team_id,
        snapshot_date=snapshot_date,
        allocated_hours=allocated_dec,
        available_hours=available_dec,
        utilization_pct=pct,
        created_at=datetime(2026, 6, 10, tzinfo=UTC),
        notes="SECRET_NOTES",
        billable_hours=Decimal("1"),
        non_billable_hours=Decimal("2"),
        annotator_id=None,
    )


def _requirement(
    *,
    skill_id,
    required_level=ProficiencyLevel.INTERMEDIATE,
    headcount=2,
    sme=1,
    req_id=None,
    created_at=None,
) -> SimpleNamespace:
    return SimpleNamespace(
        id=req_id or uuid4(),
        skill_id=skill_id,
        required_proficiency_level=required_level,
        priority=SkillRequirementPriority.HIGH,
        required_headcount=headcount,
        required_sme_count=sme,
        created_at=created_at or _PAST,
    )


def _skill(skill_id=None, *, created_at=None) -> SimpleNamespace:
    return SimpleNamespace(id=skill_id or uuid4(), created_at=created_at or _PAST)


def _assignment(
    *,
    annotator_id,
    skill_id,
    level=ProficiencyLevel.ADVANCED,
    created_at=None,
) -> SimpleNamespace:
    return SimpleNamespace(
        annotator_id=annotator_id,
        skill_id=skill_id,
        proficiency_level=level,
        created_at=created_at or _PAST,
    )


def _program(program_id=None, *, created_at=None) -> SimpleNamespace:
    return SimpleNamespace(id=program_id or uuid4(), created_at=created_at or _PAST)


def _training(
    *,
    annotator_id,
    program_id,
    status=TrainingRecordStatus.COMPLETED,
    created_at=None,
    record_id=None,
) -> SimpleNamespace:
    return SimpleNamespace(
        id=record_id or uuid4(),
        annotator_id=annotator_id,
        training_program_id=program_id,
        status=status,
        created_at=created_at or datetime(2026, 6, 5, tzinfo=UTC),
        score_pct=Decimal("99.00"),
    )


def _gap(
    *,
    gap_type=CapabilityGapType.SKILL_SHORTAGE,
    severity=CapabilityGapSeverity.HIGH,
    status=CapabilityGapStatus.OPEN,
    detected_at=None,
    team_id=None,
    skill_id=None,
    gap_id=None,
) -> SimpleNamespace:
    return SimpleNamespace(
        id=gap_id or uuid4(),
        gap_type=gap_type,
        severity=severity,
        status=status,
        team_id=team_id or uuid4(),
        skill_id=skill_id or uuid4(),
        detected_at=detected_at or datetime(2026, 6, 10, tzinfo=UTC),
        resolved_at=None,
        created_at=datetime(2026, 6, 10, tzinfo=UTC),
        title="SECRET_TITLE",
        detail="SECRET_DETAIL",
        evidence={"secret": True},
    )


@pytest.mark.asyncio
async def test_auth_runs_before_workforce_queries() -> None:
    project = _project()
    user = _user(AppRole.DELIVERY_MANAGER, project.org_id)
    session = FakeSession(teams=[_team_row()])
    with (
        patch(
            "app.agents.client_intelligence.evidence_pack.get_visible_project",
            new=AsyncMock(side_effect=ApiError(404, "NOT_FOUND", "missing")),
        ),
        pytest.raises(ApiError),
    ):
        await build_client_evidence_pack(session, user, project.id, as_of=date(2026, 6, 18))
    assert session.statements == []


@pytest.mark.asyncio
async def test_capacity_weighted_utilization_and_latest_snapshot() -> None:
    org_id = uuid4()
    project_id = uuid4()
    team_a = uuid4()
    team_b = uuid4()
    period = resolve_reporting_period(date(2026, 6, 18))
    older = _util_row(team_id=team_a, snapshot_date=date(2026, 6, 1), allocated=10, available=100)
    newer = _util_row(team_id=team_a, snapshot_date=date(2026, 6, 15), allocated=80, available=100)
    other = _util_row(team_id=team_b, snapshot_date=date(2026, 6, 14), allocated=20, available=50)
    future = _util_row(team_id=team_a, snapshot_date=date(2026, 6, 20), allocated=1, available=1)
    # FakeSession does not apply SQL date filters; omit future/individual rows here.
    _ = future

    session = FakeSession(
        teams=[_team_row(team_a), _team_row(team_b)],
        annotators=[
            _annotator_row(team_id=team_a, sme=True),
            _annotator_row(team_id=team_b, sme=False),
        ],
        utilization=[newer, older, other],
    )
    facts, evidence, issues, _, _ = await load_workforce_evidence(
        session,
        project_id,
        org_id,
        period,
        visibility_mode=EvidenceVisibility.INTERNAL,
    )
    assert facts.capacity.active_team_count == 2
    assert facts.capacity.active_worker_count == 2
    assert facts.capacity.certified_sme_count == 1
    assert facts.capacity.allocated_hours_total == Decimal("100.00")
    assert facts.capacity.available_hours_total == Decimal("150.00")
    # Weighted: 100/150*100 = 66.67, not average of 80% and 40%.
    assert facts.capacity.utilization_pct == Decimal("66.67")
    assert facts.capacity.latest_snapshot_date == date(2026, 6, 15)
    assert len(facts.team_capacity) == 2
    assert {row.team_id for row in facts.team_capacity} == {team_a, team_b}
    assert all(item.source_agent.value == "workforce_capability" for item in evidence)
    util_states = [i.state for i in issues if i.source == "workforce_utilization"]
    assert DataQualityState.COMPLETE in util_states


@pytest.mark.asyncio
async def test_zero_available_hours_returns_none_and_partial() -> None:
    org_id = uuid4()
    team_id = uuid4()
    period = resolve_reporting_period(date(2026, 6, 18))
    session = FakeSession(
        teams=[_team_row(team_id)],
        annotators=[_annotator_row(team_id=team_id)],
        utilization=[
            _util_row(
                team_id=team_id,
                snapshot_date=date(2026, 6, 10),
                allocated=5,
                available=0,
            )
        ],
    )
    facts, _, issues, _, _ = await load_workforce_evidence(
        session,
        uuid4(),
        org_id,
        period,
        visibility_mode=EvidenceVisibility.CLIENT_SAFE,
    )
    assert facts.capacity.utilization_pct is None
    assert facts.team_capacity == []
    assert any(
        i.source == "workforce_utilization" and i.state == DataQualityState.PARTIAL for i in issues
    )


@pytest.mark.asyncio
async def test_missing_team_snapshot_is_partial_and_no_zero_fill() -> None:
    org_id = uuid4()
    team_a = uuid4()
    team_b = uuid4()
    period = resolve_reporting_period(date(2026, 6, 18))
    session = FakeSession(
        teams=[_team_row(team_a), _team_row(team_b)],
        annotators=[_annotator_row(team_id=team_a)],
        utilization=[
            _util_row(
                team_id=team_a,
                snapshot_date=date(2026, 6, 10),
                allocated=40,
                available=80,
            )
        ],
    )
    facts, _, issues, _, _ = await load_workforce_evidence(
        session,
        uuid4(),
        org_id,
        period,
        visibility_mode=EvidenceVisibility.INTERNAL,
    )
    assert facts.capacity.teams_with_utilization == 1
    assert facts.capacity.teams_without_utilization == 1
    assert facts.capacity.available_hours_total == Decimal("80.00")
    assert any(
        i.source == "workforce_utilization" and i.state == DataQualityState.PARTIAL for i in issues
    )


@pytest.mark.asyncio
async def test_no_snapshots_unavailable() -> None:
    org_id = uuid4()
    team_id = uuid4()
    period = resolve_reporting_period(date(2026, 6, 18))
    session = FakeSession(
        teams=[_team_row(team_id)],
        annotators=[_annotator_row(team_id=team_id)],
        utilization=[],
    )
    facts, _, issues, _, _ = await load_workforce_evidence(
        session,
        uuid4(),
        org_id,
        period,
        visibility_mode=EvidenceVisibility.INTERNAL,
    )
    assert facts.capacity.allocated_hours_total is None
    assert facts.capacity.utilization_pct is None
    assert any(
        i.source == "workforce_utilization" and i.state == DataQualityState.UNAVAILABLE
        for i in issues
    )


@pytest.mark.asyncio
async def test_skill_coverage_sme_and_proficiency_rules() -> None:
    org_id = uuid4()
    team_id = uuid4()
    skill_id = uuid4()
    sme = _annotator_row(team_id=team_id, sme=True)
    junior = _annotator_row(team_id=team_id, sme=False)
    period = resolve_reporting_period(date(2026, 6, 18))
    session = FakeSession(
        teams=[_team_row(team_id)],
        annotators=[sme, junior],
        requirements=[_requirement(skill_id=skill_id, headcount=2, sme=1)],
        skills=[_skill(skill_id)],
        annotator_skills=[
            _assignment(annotator_id=sme.id, skill_id=skill_id, level=ProficiencyLevel.ADVANCED),
            _assignment(
                annotator_id=junior.id, skill_id=skill_id, level=ProficiencyLevel.BEGINNER
            ),
        ],
    )
    facts, _, issues, _, _ = await load_workforce_evidence(
        session,
        uuid4(),
        org_id,
        period,
        visibility_mode=EvidenceVisibility.INTERNAL,
    )
    assert facts.skill_coverage.requirement_count == 1
    assert facts.skill_coverage.partial_requirement_count == 1
    assert facts.skill_coverage.available_headcount_slots == 1
    assert facts.skill_coverage.available_sme_slots == 1
    assert len(facts.skill_requirements) == 1
    assert facts.skill_requirements[0].coverage_status == "partial"

    safe_facts, _, _, _, _ = await load_workforce_evidence(
        session,
        uuid4(),
        org_id,
        period,
        visibility_mode=EvidenceVisibility.CLIENT_SAFE,
    )
    assert safe_facts.skill_requirements == []
    assert safe_facts.skill_coverage.requirement_count == 1


@pytest.mark.asyncio
async def test_no_requirements_not_fully_covered() -> None:
    org_id = uuid4()
    team_id = uuid4()
    period = resolve_reporting_period(date(2026, 6, 18))
    session = FakeSession(
        teams=[_team_row(team_id)],
        annotators=[_annotator_row(team_id=team_id)],
        requirements=[],
    )
    facts, _, issues, _, _ = await load_workforce_evidence(
        session,
        uuid4(),
        org_id,
        period,
        visibility_mode=EvidenceVisibility.CLIENT_SAFE,
    )
    assert facts.skill_coverage.requirement_count == 0
    assert facts.skill_coverage.covered_requirement_count == 0
    assert any(
        i.source == "workforce_skill_coverage" and i.state == DataQualityState.UNAVAILABLE
        for i in issues
    )


@pytest.mark.asyncio
async def test_training_aggregates_and_duplicates() -> None:
    org_id = uuid4()
    team_id = uuid4()
    worker = _annotator_row(team_id=team_id)
    program = _program()
    period = resolve_reporting_period(date(2026, 6, 18))
    newer = _training(
        annotator_id=worker.id,
        program_id=program.id,
        status=TrainingRecordStatus.COMPLETED,
        created_at=datetime(2026, 6, 8, tzinfo=UTC),
    )
    older = _training(
        annotator_id=worker.id,
        program_id=program.id,
        status=TrainingRecordStatus.FAILED,
        created_at=datetime(2026, 6, 1, tzinfo=UTC),
    )
    session = FakeSession(
        teams=[_team_row(team_id)],
        annotators=[worker],
        programs=[program],
        training_records=[newer, older],
    )
    facts, evidence, issues, _, _ = await load_workforce_evidence(
        session,
        uuid4(),
        org_id,
        period,
        visibility_mode=EvidenceVisibility.CLIENT_SAFE,
    )
    assert facts.training.mandatory_program_count == 1
    assert facts.training.required_assignment_count == 1
    assert facts.training.completed_assignment_count == 1
    assert facts.training.incomplete_assignment_count == 0
    assert facts.training.completion_pct == Decimal("100.00")
    assert any(i.state == DataQualityState.CONFLICTING for i in issues)
    training_issues = [i for i in issues if i.source == "workforce_training"]
    assert len(training_issues) == 1
    assert training_issues[0].state == DataQualityState.CONFLICTING
    assert all(item.source_table != "training_records" for item in evidence)
    assert all(item.source_table != "annotators" for item in evidence)


@pytest.mark.asyncio
async def test_training_missing_and_failed_and_zero_denominator() -> None:
    org_id = uuid4()
    team_id = uuid4()
    worker = _annotator_row(team_id=team_id)
    program_a = _program()
    program_b = _program()
    period = resolve_reporting_period(date(2026, 6, 18))
    session = FakeSession(
        teams=[_team_row(team_id)],
        annotators=[worker],
        programs=[program_a, program_b],
        training_records=[
            _training(
                annotator_id=worker.id,
                program_id=program_a.id,
                status=TrainingRecordStatus.FAILED,
            )
        ],
    )
    facts, _, _, _, _ = await load_workforce_evidence(
        session,
        uuid4(),
        org_id,
        period,
        visibility_mode=EvidenceVisibility.INTERNAL,
    )
    assert facts.training.required_assignment_count == 2
    assert facts.training.completed_assignment_count == 0
    assert facts.training.incomplete_assignment_count == 2
    assert facts.training.expired_or_failed_assignment_count == 1
    assert facts.training.completion_pct == Decimal("0.00")

    empty = FakeSession(teams=[], annotators=[], programs=[])
    empty_facts, _, issues, _, _ = await load_workforce_evidence(
        empty,
        uuid4(),
        org_id,
        period,
        visibility_mode=EvidenceVisibility.INTERNAL,
    )
    assert empty_facts.training.completion_pct is None
    assert empty_facts.training.required_assignment_count == 0


@pytest.mark.asyncio
async def test_capability_gaps_internal_vs_client_safe() -> None:
    org_id = uuid4()
    team_id = uuid4()
    skill_id = uuid4()
    gap_id = uuid4()
    period = resolve_reporting_period(date(2026, 6, 18))
    open_gap = _gap(
        gap_id=gap_id,
        team_id=team_id,
        skill_id=skill_id,
        detected_at=datetime(2026, 6, 10, tzinfo=UTC),
    )
    future_gap = _gap(detected_at=datetime(2026, 6, 25, tzinfo=UTC))
    resolved = _gap(status=CapabilityGapStatus.RESOLVED)
    session = FakeSession(
        teams=[_team_row(team_id)],
        annotators=[_annotator_row(team_id=team_id)],
        gaps=[open_gap, future_gap, resolved],
    )
    # Fake does not apply SQL filters; simulate SQL by returning only open+as_of rows.
    session.gaps = [open_gap]

    internal, _, _, _, _ = await load_workforce_evidence(
        session,
        uuid4(),
        org_id,
        period,
        visibility_mode=EvidenceVisibility.INTERNAL,
    )
    assert len(internal.open_gaps) == 1
    assert internal.open_gaps[0].gap_id == gap_id
    assert internal.open_gaps[0].team_id == team_id
    dump = str(internal.model_dump(mode="json")).lower()
    assert "secret_title" not in dump
    assert "secret_detail" not in dump

    safe, evidence, _, _, _ = await load_workforce_evidence(
        session,
        uuid4(),
        org_id,
        period,
        visibility_mode=EvidenceVisibility.CLIENT_SAFE,
    )
    assert safe.open_gaps == []
    assert safe.open_gap_counts == [
        CapabilityGapCountFacts(
            gap_type=CapabilityGapType.SKILL_SHORTAGE.value,
            severity=CapabilityGapSeverity.HIGH.value,
            count=1,
        )
    ]
    assert all("gap_id" not in item.claim_keys for item in evidence)
    assert all("team_id" not in item.claim_keys for item in evidence)
    blob = str(safe.model_dump(mode="json")).lower()
    assert str(gap_id).lower() not in blob
    assert str(team_id).lower() not in blob
    assert str(skill_id).lower() not in blob
    assert "secret" not in blob


@pytest.mark.asyncio
async def test_zero_open_gaps_is_complete_not_unavailable() -> None:
    org_id = uuid4()
    period = resolve_reporting_period(date(2026, 6, 18))
    session = FakeSession(teams=[], gaps=[])
    facts, _, issues, _, _ = await load_workforce_evidence(
        session,
        uuid4(),
        org_id,
        period,
        visibility_mode=EvidenceVisibility.INTERNAL,
    )
    assert facts.open_gap_counts == []
    assert facts.open_gaps == []
    assert any(
        i.source == "workforce_capability_gaps" and i.state == DataQualityState.COMPLETE
        for i in issues
    )


@pytest.mark.asyncio
async def test_historical_as_of_adds_current_state_limitation() -> None:
    org_id = uuid4()
    period = resolve_reporting_period(date(2026, 6, 18))
    session = FakeSession()
    _, _, _, _, limitations = await load_workforce_evidence(
        session,
        uuid4(),
        org_id,
        period,
        visibility_mode=EvidenceVisibility.INTERNAL,
    )
    assert any("current-state" in item for item in limitations)


@pytest.mark.asyncio
async def test_client_safe_pack_hides_identities_and_keeps_aggregates() -> None:
    org_id = uuid4()
    project = _project(org_id)
    team_id = uuid4()
    worker_id = uuid4()
    skill_id = uuid4()
    gap_id = uuid4()
    secret_name = "Priya Sharma"
    team_name = "Kosovo-A"
    session = FakeSession(
        teams=[_team_row(team_id)],
        annotators=[_annotator_row(team_id=team_id, sme=True, annotator_id=worker_id)],
        utilization=[
            _util_row(team_id=team_id, snapshot_date=date(2026, 6, 10), allocated=40, available=50)
        ],
        requirements=[_requirement(skill_id=skill_id, headcount=1, sme=1)],
        skills=[_skill(skill_id)],
        annotator_skills=[
            _assignment(annotator_id=worker_id, skill_id=skill_id, level=ProficiencyLevel.EXPERT)
        ],
        programs=[_program()],
        training_records=[
            _training(
                annotator_id=worker_id,
                program_id=uuid4(),
                status=TrainingRecordStatus.COMPLETED,
            )
        ],
        gaps=[_gap(gap_id=gap_id, team_id=team_id, skill_id=skill_id)],
        milestones=[],
    )
    # Align training program id with record for completion math.
    program = _program()
    session.programs = [program]
    session.training_records = [
        _training(
            annotator_id=worker_id,
            program_id=program.id,
            status=TrainingRecordStatus.COMPLETED,
        )
    ]

    user = _user(AppRole.CLIENT, org_id)
    with patch(
        "app.agents.client_intelligence.evidence_pack.get_visible_project",
        new=AsyncMock(return_value=project),
    ):
        pack = await build_client_evidence_pack(
            session,
            user,
            project.id,
            as_of=date(2026, 6, 18),
        )

    assert pack.visibility_mode == EvidenceVisibility.CLIENT_SAFE
    assert pack.workforce.team_capacity == []
    assert pack.workforce.skill_requirements == []
    assert pack.workforce.open_gaps == []
    assert pack.workforce.capacity.active_team_count == 1
    assert pack.workforce.capacity.active_worker_count == 1
    assert pack.workforce.capacity.utilization_pct == Decimal("80.00")
    blob = str(pack.model_dump(mode="json")).lower()
    assert secret_name.lower() not in blob
    assert team_name.lower() not in blob
    assert "annotator" not in blob
    assert "secret_title" not in blob
    assert "secret_notes" not in blob
    workforce_blob = str(pack.workforce.model_dump(mode="json")).lower()
    assert str(worker_id).lower() not in workforce_blob
    assert str(team_id).lower() not in workforce_blob
    assert str(skill_id).lower() not in workforce_blob
    assert str(gap_id).lower() not in workforce_blob
    assert all(item.visibility == EvidenceVisibility.CLIENT_SAFE for item in pack.evidence)
    for item in pack.evidence:
        if item.source_agent.value == "workforce_capability":
            assert "gap_id" not in item.claim_keys
            assert "team_id" not in item.claim_keys
            assert "skill_id" not in item.claim_keys
            assert "requirement_id" not in item.claim_keys


@pytest.mark.asyncio
async def test_fingerprint_aggregate_change_and_hidden_identity_stability() -> None:
    org_id = uuid4()
    team_id = uuid4()
    period = resolve_reporting_period(date(2026, 6, 18))
    util = _util_row(team_id=team_id, snapshot_date=date(2026, 6, 10), allocated=40, available=50)
    base_session = FakeSession(
        teams=[_team_row(team_id)],
        annotators=[_annotator_row(team_id=team_id, annotator_id=uuid4())],
        utilization=[util],
    )
    renamed_session = FakeSession(
        teams=[_team_row(team_id)],
        annotators=[_annotator_row(team_id=team_id, annotator_id=uuid4())],
        utilization=[util],
    )
    changed_util = FakeSession(
        teams=[_team_row(team_id)],
        annotators=[_annotator_row(team_id=team_id)],
        utilization=[
            _util_row(team_id=team_id, snapshot_date=date(2026, 6, 10), allocated=45, available=50)
        ],
    )

    left, left_ev, _, _, _ = await load_workforce_evidence(
        base_session,
        uuid4(),
        org_id,
        period,
        visibility_mode=EvidenceVisibility.CLIENT_SAFE,
    )
    right, right_ev, _, _, _ = await load_workforce_evidence(
        renamed_session,
        uuid4(),
        org_id,
        period,
        visibility_mode=EvidenceVisibility.CLIENT_SAFE,
    )
    changed, changed_ev, _, _, _ = await load_workforce_evidence(
        changed_util,
        uuid4(),
        org_id,
        period,
        visibility_mode=EvidenceVisibility.CLIENT_SAFE,
    )

    project_id = uuid4()
    fp_left = _fingerprint(
        project_id=project_id,
        reporting_period_start=period.start_date,
        reporting_period_end=period.end_date,
        visibility_mode=EvidenceVisibility.CLIENT_SAFE,
        evidence=left_ev,
        workforce_projection=_workforce_fingerprint_projection(left),
    )
    fp_right = _fingerprint(
        project_id=project_id,
        reporting_period_start=period.start_date,
        reporting_period_end=period.end_date,
        visibility_mode=EvidenceVisibility.CLIENT_SAFE,
        evidence=right_ev,
        workforce_projection=_workforce_fingerprint_projection(right),
    )
    fp_changed = _fingerprint(
        project_id=project_id,
        reporting_period_start=period.start_date,
        reporting_period_end=period.end_date,
        visibility_mode=EvidenceVisibility.CLIENT_SAFE,
        evidence=changed_ev,
        workforce_projection=_workforce_fingerprint_projection(changed),
    )
    assert fp_left == fp_right
    assert fp_left != fp_changed

    # Ordering of evidence pairs must not change fingerprint.
    shuffled = list(reversed(left_ev))
    fp_shuffled = _fingerprint(
        project_id=project_id,
        reporting_period_start=period.start_date,
        reporting_period_end=period.end_date,
        visibility_mode=EvidenceVisibility.CLIENT_SAFE,
        evidence=shuffled,
        workforce_projection=_workforce_fingerprint_projection(left),
    )
    assert fp_shuffled == fp_left


@pytest.mark.asyncio
async def test_internal_mode_skips_metric_configuration() -> None:
    project = _project()
    user = _user(AppRole.DELIVERY_MANAGER, project.org_id)
    team_id = uuid4()
    session = FakeSession(
        teams=[_team_row(team_id)],
        annotators=[_annotator_row(team_id=team_id)],
        metrics=[SimpleNamespace(id=uuid4(), metric_key="x", is_client_visible=True)],
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
    assert pack.policy_fingerprint is None
    assert not any("FROM metric_configurations" in stmt for stmt in session.statements)
    assert pack.workforce.team_capacity or pack.workforce.capacity.active_team_count == 1


def _workforce_issues(issues: list) -> dict[str, DataQualityState]:
    by_source: dict[str, list] = {}
    for issue in issues:
        if issue.source.startswith("workforce_"):
            by_source.setdefault(issue.source, []).append(issue)
    assert all(len(items) == 1 for items in by_source.values())
    return {source: items[0].state for source, items in by_source.items()}


@pytest.mark.asyncio
async def test_historical_as_of_excludes_future_created_rows() -> None:
    org_id = uuid4()
    as_of = date(2026, 6, 18)
    period = resolve_reporting_period(as_of)
    team_ok = uuid4()
    team_future = uuid4()
    worker_ok = uuid4()
    worker_future = uuid4()
    skill_ok = uuid4()
    skill_future = uuid4()
    program_ok = _program(created_at=_PAST)
    program_future = _program(created_at=_FUTURE)
    req_ok = _requirement(skill_id=skill_ok, headcount=1, sme=0, created_at=_PAST)
    req_future = _requirement(skill_id=skill_future, headcount=1, sme=0, created_at=_FUTURE)
    util_ok = _util_row(
        team_id=team_ok,
        snapshot_date=date(2026, 6, 10),
        allocated=10,
        available=20,
    )
    util_future_created = _util_row(
        team_id=team_ok,
        snapshot_date=date(2026, 6, 10),
        allocated=99,
        available=100,
    )
    util_future_created.created_at = _FUTURE

    session = FakeSession(
        as_of=as_of,
        teams=[
            _team_row(team_ok, created_at=_PAST),
            _team_row(team_future, created_at=_FUTURE),
        ],
        annotators=[
            _annotator_row(team_id=team_ok, annotator_id=worker_ok, sme=True, created_at=_PAST),
            _annotator_row(
                team_id=team_ok,
                annotator_id=worker_future,
                sme=True,
                created_at=_FUTURE,
            ),
        ],
        utilization=[util_ok, util_future_created],
        requirements=[req_ok, req_future],
        skills=[
            _skill(skill_ok, created_at=_PAST),
            _skill(skill_future, created_at=_FUTURE),
        ],
        annotator_skills=[
            _assignment(
                annotator_id=worker_ok,
                skill_id=skill_ok,
                level=ProficiencyLevel.EXPERT,
                created_at=_PAST,
            ),
            _assignment(
                annotator_id=worker_ok,
                skill_id=skill_ok,
                level=ProficiencyLevel.BEGINNER,
                created_at=_FUTURE,
            ),
        ],
        programs=[program_ok, program_future],
        training_records=[
            _training(
                annotator_id=worker_ok,
                program_id=program_ok.id,
                status=TrainingRecordStatus.COMPLETED,
                created_at=_PAST,
            ),
            _training(
                annotator_id=worker_ok,
                program_id=program_ok.id,
                status=TrainingRecordStatus.COMPLETED,
                created_at=_FUTURE,
            ),
        ],
    )
    facts, evidence, _, _, limitations = await load_workforce_evidence(
        session,
        uuid4(),
        org_id,
        period,
        visibility_mode=EvidenceVisibility.INTERNAL,
    )
    assert any("current-state" in item for item in limitations)
    assert facts.capacity.active_team_count == 1
    assert facts.capacity.active_worker_count == 1
    assert facts.capacity.allocated_hours_total == Decimal("10")
    assert facts.skill_coverage.requirement_count == 1
    assert facts.training.mandatory_program_count == 1
    assert facts.training.completed_assignment_count == 1
    future_ids = {
        str(team_future),
        str(worker_future),
        str(skill_future),
        str(req_future.id),
        str(program_future.id),
        str(util_future_created.id),
    }
    evidence_ids = {str(item.source_row_id) for item in evidence}
    assert future_ids.isdisjoint(evidence_ids)


@pytest.mark.asyncio
async def test_historical_fingerprint_ignores_future_created_rows() -> None:
    org_id = uuid4()
    as_of = date(2026, 6, 18)
    period = resolve_reporting_period(as_of)
    team_id = uuid4()
    worker = _annotator_row(team_id=team_id)
    util = _util_row(team_id=team_id, snapshot_date=date(2026, 6, 10), allocated=10, available=20)
    base = FakeSession(
        as_of=as_of,
        teams=[_team_row(team_id)],
        annotators=[worker],
        utilization=[util],
    )
    with_future = FakeSession(
        as_of=as_of,
        teams=[_team_row(team_id), _team_row(created_at=_FUTURE)],
        annotators=[worker, _annotator_row(team_id=team_id, created_at=_FUTURE)],
        utilization=[util],
    )
    left, left_ev, _, _, _ = await load_workforce_evidence(
        base,
        uuid4(),
        org_id,
        period,
        visibility_mode=EvidenceVisibility.CLIENT_SAFE,
    )
    right, right_ev, _, _, _ = await load_workforce_evidence(
        with_future,
        uuid4(),
        org_id,
        period,
        visibility_mode=EvidenceVisibility.CLIENT_SAFE,
    )
    project_id = uuid4()
    assert _fingerprint(
        project_id=project_id,
        reporting_period_start=period.start_date,
        reporting_period_end=period.end_date,
        visibility_mode=EvidenceVisibility.CLIENT_SAFE,
        evidence=left_ev,
        workforce_projection=_workforce_fingerprint_projection(left),
    ) == _fingerprint(
        project_id=project_id,
        reporting_period_start=period.start_date,
        reporting_period_end=period.end_date,
        visibility_mode=EvidenceVisibility.CLIENT_SAFE,
        evidence=right_ev,
        workforce_projection=_workforce_fingerprint_projection(right),
    )


@pytest.mark.asyncio
async def test_roster_bound_partial_not_complete() -> None:
    org_id = uuid4()
    period = resolve_reporting_period(date(2026, 6, 18))
    teams = [_team_row() for _ in range(3)]
    with patch.object(workforce_adapter_mod, "_MAX_TEAMS", 2):
        session = FakeSession(
            teams=teams,
            annotators=[_annotator_row(team_id=teams[0].id)],
        )
        facts, _, issues, _, _ = await load_workforce_evidence(
            session,
            uuid4(),
            org_id,
            period,
            visibility_mode=EvidenceVisibility.INTERNAL,
        )
    by_source = _workforce_issues(issues)
    assert facts.capacity.active_team_count == 2
    assert by_source["workforce_roster"] == DataQualityState.PARTIAL


@pytest.mark.asyncio
async def test_exact_max_rows_not_treated_as_truncation() -> None:
    org_id = uuid4()
    period = resolve_reporting_period(date(2026, 6, 18))
    teams = [_team_row() for _ in range(2)]
    with patch.object(workforce_adapter_mod, "_MAX_TEAMS", 2):
        session = FakeSession(
            teams=teams,
            annotators=[
                _annotator_row(team_id=teams[0].id),
                _annotator_row(team_id=teams[1].id),
            ],
            utilization=[
                _util_row(
                    team_id=teams[0].id,
                    snapshot_date=date(2026, 6, 10),
                    allocated=10,
                    available=20,
                ),
                _util_row(
                    team_id=teams[1].id,
                    snapshot_date=date(2026, 6, 10),
                    allocated=10,
                    available=20,
                ),
            ],
        )
        facts, _, issues, _, _ = await load_workforce_evidence(
            session,
            uuid4(),
            org_id,
            period,
            visibility_mode=EvidenceVisibility.INTERNAL,
        )
    by_source = _workforce_issues(issues)
    assert facts.capacity.active_team_count == 2
    assert by_source["workforce_roster"] == DataQualityState.COMPLETE
    assert by_source["workforce_utilization"] == DataQualityState.COMPLETE


@pytest.mark.asyncio
async def test_missing_skill_is_unavailable_not_gap() -> None:
    org_id = uuid4()
    team_id = uuid4()
    missing_skill = uuid4()
    valid_skill = uuid4()
    worker = _annotator_row(team_id=team_id)
    period = resolve_reporting_period(date(2026, 6, 18))
    session = FakeSession(
        teams=[_team_row(team_id)],
        annotators=[worker],
        requirements=[
            _requirement(skill_id=missing_skill, headcount=1, sme=0),
            _requirement(skill_id=valid_skill, headcount=1, sme=0),
        ],
        skills=[_skill(valid_skill)],
        annotator_skills=[],
    )
    facts, _, issues, _, _ = await load_workforce_evidence(
        session,
        uuid4(),
        org_id,
        period,
        visibility_mode=EvidenceVisibility.INTERNAL,
    )
    summary = facts.skill_coverage
    assert summary.requirement_count == 2
    assert summary.unavailable_requirement_count == 1
    assert summary.gap_requirement_count == 1
    assert summary.covered_requirement_count == 0
    assert summary.partial_requirement_count == 0
    assert (
        summary.covered_requirement_count
        + summary.partial_requirement_count
        + summary.gap_requirement_count
        + summary.unavailable_requirement_count
        == summary.requirement_count
    )
    unavailable = [row for row in facts.skill_requirements if row.coverage_status == "unavailable"]
    gap_rows = [row for row in facts.skill_requirements if row.coverage_status == "gap"]
    assert len(unavailable) == 1
    assert unavailable[0].available_headcount is None
    assert unavailable[0].available_sme_count is None
    assert len(gap_rows) == 1
    assert gap_rows[0].available_headcount == 0
    assert _workforce_issues(issues)["workforce_skill_coverage"] == DataQualityState.PARTIAL


@pytest.mark.asyncio
async def test_utilization_evidence_does_not_claim_roster_counts() -> None:
    org_id = uuid4()
    team_id = uuid4()
    period = resolve_reporting_period(date(2026, 6, 18))
    session = FakeSession(
        teams=[_team_row(team_id)],
        annotators=[_annotator_row(team_id=team_id)],
        utilization=[
            _util_row(
                team_id=team_id,
                snapshot_date=date(2026, 6, 10),
                allocated=10,
                available=20,
            )
        ],
    )
    _, evidence, _, _, _ = await load_workforce_evidence(
        session,
        uuid4(),
        org_id,
        period,
        visibility_mode=EvidenceVisibility.CLIENT_SAFE,
    )
    util_refs = [item for item in evidence if item.source_table == "utilization_snapshots"]
    assert util_refs
    for item in util_refs:
        assert set(item.claim_keys) == set(_UTILIZATION_CLAIM_KEYS)
        assert "active_team_count" not in item.claim_keys
        assert "active_worker_count" not in item.claim_keys
        assert "certified_sme_count" not in item.claim_keys
    assert all(item.source_table != "annotators" for item in evidence)
    assert all(item.source_table != "annotator_skills" for item in evidence)
    assert all(item.source_table != "training_records" for item in evidence)
