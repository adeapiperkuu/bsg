"""Client Intelligence QualitySnapshot evidence adapter tests."""

from __future__ import annotations

import re
from datetime import UTC, date, datetime
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest

from app.agents.client_intelligence import (
    ClientVisibilityPolicy,
    ClientVisibleMetric,
    DataQualityState,
    EvidenceVisibility,
    build_client_evidence_pack,
    load_quality_evidence,
    resolve_reporting_period,
)
from app.agents.client_intelligence.quality_adapter import iso_periods_for_reporting
from app.core.security import CurrentUser
from app.db.models import AppRole, MilestoneStatus, ProjectStatus


class FakeScalars:
    def __init__(self, items: list[object] | None = None) -> None:
        self._items = items or []

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
        metrics: list[object] | None = None,
        milestones: list[object] | None = None,
        throughput: object | None = None,
        confidence: object | None = None,
        quality_snapshots: list[object] | None = None,
        risks: list[object] | None = None,
        bottlenecks: list[object] | None = None,
    ) -> None:
        self.metrics = metrics or []
        self.milestones = milestones or []
        self.throughput = throughput
        self.confidence = confidence
        self.quality_snapshots = quality_snapshots or []
        self.risks = risks or []
        self.bottlenecks = bottlenecks or []
        self.statements: list[str] = []

    async def execute(self, stmt) -> FakeResult:
        compiled = str(stmt.compile(compile_kwargs={"literal_binds": True}))
        self.statements.append(compiled)
        if "FROM metric_configurations" in compiled:
            visible = [row for row in self.metrics if getattr(row, "is_client_visible", False)]
            return FakeResult(None, visible)
        if "FROM milestones" in compiled:
            return FakeResult(None, self.milestones)
        if "FROM throughput_snapshots" in compiled:
            upper = compiled.upper()
            if "SNAPSHOT_DATE ASC" in upper and "LIMIT" not in upper:
                rows = getattr(self, "throughput_series", None)
                if rows is None and getattr(self, "throughput", None) is not None:
                    rows = [self.throughput]
                return FakeResult(None, rows or [])
            assert "LIMIT" in upper or "limit" in compiled
            return FakeResult(self.throughput)
        if "FROM delivery_confidence_scores" in compiled:
            return FakeResult(self.confidence)
        if "FROM quality_snapshots" in compiled:
            assert "LIMIT" in compiled.upper() or "limit" in compiled
            assert "ORDER BY" in compiled.upper() or "order by" in compiled
            assert "quality_error" not in compiled.lower()
            assert "reviewer" not in compiled.lower()
            assert "root_cause" not in compiled.lower()
            assert "drift_alert_detail" not in compiled.lower()
            return FakeResult(None, self.quality_snapshots)
        if "FROM risk_alerts" in compiled:
            return FakeResult(None, self.risks)
        if "FROM bottlenecks" in compiled:
            return FakeResult(None, self.bottlenecks)
        if "FROM teams" in compiled:
            assert "LIMIT" in compiled.upper() or "limit" in compiled
            return FakeResult(None, [])
        if "FROM annotators" in compiled:
            assert "full_name" not in compiled.lower()
            return FakeResult(None, [])
        if "FROM utilization_snapshots" in compiled:
            assert "notes" not in compiled.lower()
            return FakeResult(None, [])
        if "FROM project_skill_requirements" in compiled:
            return FakeResult(None, [])
        if "FROM skills" in compiled:
            return FakeResult(None, [])
        if "FROM annotator_skills" in compiled:
            return FakeResult(None, [])
        if "FROM training_programs" in compiled:
            return FakeResult(None, [])
        if "FROM training_records" in compiled:
            assert "score_pct" not in compiled.lower()
            return FakeResult(None, [])
        if "FROM capability_gaps" in compiled:
            assert "title" not in compiled.lower()
            assert "detail" not in compiled.lower()
            assert "evidence" not in compiled.lower()
            return FakeResult(None, [])
        if "FROM knowledge_documents" in compiled:
            assert "extracted_text" not in compiled.lower()
            return FakeResult(None, [])
        if (
            re.search(r"\bselect\s+1\b", compiled, re.IGNORECASE)
            or (
                "knowledge_document_chunks" in compiled.lower()
                and "chunk_text" not in compiled.lower()
            )
        ):
            return FakeResult(None, [])
        if "FROM knowledge_document_versions" in compiled:
            assert "file_name" not in compiled.lower()
            assert "file_url" not in compiled.lower()
            assert "storage_path" not in compiled.lower()
            assert "uploaded_by" not in compiled.lower()
            assert "approved_by" not in compiled.lower()
            return FakeResult(None, [])
        if "FROM knowledge_document_chunks" in compiled or "knowledge_document_chunks" in compiled:
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
        email="ci-quality@example.com",
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


def _metric(key: str, *, visible: bool = True, order: int = 1) -> SimpleNamespace:
    return SimpleNamespace(
        id=uuid4(),
        metric_key=key,
        is_client_visible=visible,
        display_order=order,
        deleted_at=None,
    )


def _milestone(project_id) -> SimpleNamespace:
    return SimpleNamespace(
        id=uuid4(),
        project_id=project_id,
        name="Batch 14 QA",
        description=None,
        planned_date=date(2026, 6, 24),
        actual_date=None,
        status=MilestoneStatus.ON_TRACK,
        deleted_at=None,
        updated_at=datetime(2026, 6, 17, tzinfo=UTC),
    )


def _snap(
    project_id,
    *,
    iso_year: int,
    iso_week: int,
    team_id=None,
    **kwargs,
) -> SimpleNamespace:
    data = {
        "id": uuid4(),
        "project_id": project_id,
        "team_id": team_id or uuid4(),
        "org_id": uuid4(),
        "iso_year": iso_year,
        "iso_week": iso_week,
        "gold_set_accuracy_pct": Decimal("96.50"),
        "iaa_krippendorff_alpha": Decimal("0.910"),
        "rework_rate_pct": Decimal("3.20"),
        "evaluated_item_count": 55,
        "has_drift_alert": True,
        "drift_alert_detail": "SECRET_DRIFT_DETAIL",
        "root_cause": {"cause": "SECRET_ROOT_CAUSE"},
        "confidence_level": "high",
        "created_at": datetime(2026, 6, 17, 12, 0, tzinfo=UTC),
    }
    data.update(kwargs)
    return SimpleNamespace(**data)


# ---------------------------------------------------------------------------
# ISO period mapping
# ---------------------------------------------------------------------------


def test_iso_periods_from_reporting_period() -> None:
    period = resolve_reporting_period(date(2026, 6, 17))
    (cy, cw), (py, pw) = iso_periods_for_reporting(period)
    assert (cy, cw) == (2026, 25)
    assert (py, pw) == (2026, 24)


def test_iso_periods_year_boundary() -> None:
    period = resolve_reporting_period(date(2026, 1, 1))
    (cy, cw), (py, pw) = iso_periods_for_reporting(period)
    assert (cy, cw) == (2026, 1)
    assert (py, pw) == (2025, 52)


# ---------------------------------------------------------------------------
# Adapter unit tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_internal_includes_aggregates_excludes_root_cause_and_drift_detail() -> None:
    project_id = uuid4()
    team_id = uuid4()
    period = resolve_reporting_period(date(2026, 6, 17))
    (cy, cw), (py, pw) = iso_periods_for_reporting(period)
    snap = _snap(project_id, iso_year=cy, iso_week=cw, team_id=team_id)
    session = FakeSession(quality_snapshots=[snap])
    facts, evidence, issues, vis, _ = await load_quality_evidence(
        session,
        project_id,
        period,
        visibility_mode=EvidenceVisibility.INTERNAL,
        policy=None,
    )
    assert len(facts.current_period) == 1
    row = facts.current_period[0]
    assert row.team_id == team_id
    assert row.gold_set_accuracy_pct == Decimal("96.50")
    assert row.rework_rate_pct == Decimal("3.20")
    assert row.iaa_krippendorff_alpha == Decimal("0.910")
    assert row.evaluated_item_count == 55
    assert row.has_drift_alert is True
    assert row.confidence_level == "high"
    dump = row.model_dump(mode="json")
    assert "root_cause" not in dump
    assert "drift_alert_detail" not in dump
    assert evidence[0].visibility == EvidenceVisibility.INTERNAL
    assert str(team_id) not in evidence[0].description
    assert "96.5" not in evidence[0].description
    assert "SECRET" not in evidence[0].description
    assert issues[0].state == DataQualityState.PARTIAL  # previous missing
    assert vis == []


@pytest.mark.asyncio
async def test_client_safe_no_metrics_skips_query() -> None:
    project_id = uuid4()
    period = resolve_reporting_period(date(2026, 6, 17))
    session = FakeSession(
        quality_snapshots=[_snap(project_id, iso_year=2026, iso_week=25)],
    )
    policy = ClientVisibilityPolicy(visible_metrics=frozenset())
    facts, evidence, issues, vis, _ = await load_quality_evidence(
        session,
        project_id,
        period,
        visibility_mode=EvidenceVisibility.CLIENT_SAFE,
        policy=policy,
    )
    assert facts.current_period == []
    assert facts.previous_period == []
    assert evidence == []
    assert issues == []
    assert any(item.reason == "not_configured" for item in vis)
    assert not any("FROM quality_snapshots" in stmt for stmt in session.statements)


@pytest.mark.asyncio
async def test_client_safe_metric_gating() -> None:
    project_id = uuid4()
    period = resolve_reporting_period(date(2026, 6, 17))
    (cy, cw), (py, pw) = iso_periods_for_reporting(period)
    snap = _snap(project_id, iso_year=cy, iso_week=cw)
    session = FakeSession(quality_snapshots=[snap])
    policy = ClientVisibilityPolicy(
        visible_metrics=frozenset({ClientVisibleMetric.GOLD_SET_ACCURACY})
    )
    facts, evidence, issues, vis, _ = await load_quality_evidence(
        session,
        project_id,
        period,
        visibility_mode=EvidenceVisibility.CLIENT_SAFE,
        policy=policy,
    )
    row = facts.current_period[0]
    assert row.gold_set_accuracy_pct == Decimal("96.50")
    assert row.rework_rate_pct is None
    assert row.iaa_krippendorff_alpha is None
    assert row.team_id is None
    assert row.evaluated_item_count is None
    assert row.has_drift_alert is None
    assert row.confidence_level is None
    assert evidence[0].claim_keys == [
        "iso_year",
        "iso_week",
        "gold_set_accuracy_pct",
    ]
    assert "rework_rate_pct" not in evidence[0].claim_keys
    blob = str(facts.model_dump(mode="json"))
    assert str(snap.team_id) not in blob
    assert "SECRET" not in blob
    assert "0.910" not in blob


@pytest.mark.asyncio
async def test_data_quality_both_periods_complete() -> None:
    project_id = uuid4()
    period = resolve_reporting_period(date(2026, 6, 17))
    (cy, cw), (py, pw) = iso_periods_for_reporting(period)
    session = FakeSession(
        quality_snapshots=[
            _snap(project_id, iso_year=cy, iso_week=cw),
            _snap(project_id, iso_year=py, iso_week=pw),
        ]
    )
    facts, _, issues, _, _ = await load_quality_evidence(
        session,
        project_id,
        period,
        visibility_mode=EvidenceVisibility.INTERNAL,
        policy=None,
    )
    assert len(facts.current_period) == 1
    assert len(facts.previous_period) == 1
    assert issues[0].state == DataQualityState.COMPLETE


@pytest.mark.asyncio
async def test_data_quality_previous_only_unavailable() -> None:
    project_id = uuid4()
    period = resolve_reporting_period(date(2026, 6, 17))
    (_, _), (py, pw) = iso_periods_for_reporting(period)
    session = FakeSession(
        quality_snapshots=[_snap(project_id, iso_year=py, iso_week=pw)],
    )
    facts, _, issues, _, limitations = await load_quality_evidence(
        session,
        project_id,
        period,
        visibility_mode=EvidenceVisibility.INTERNAL,
        policy=None,
    )
    assert facts.current_period == []
    assert len(facts.previous_period) == 1
    assert issues[0].state == DataQualityState.UNAVAILABLE
    assert any("current-period" in item.lower() for item in limitations)


@pytest.mark.asyncio
async def test_data_quality_none_and_null_metric() -> None:
    project_id = uuid4()
    period = resolve_reporting_period(date(2026, 6, 17))
    empty_session = FakeSession(quality_snapshots=[])
    _, _, issues, _, _ = await load_quality_evidence(
        empty_session,
        project_id,
        period,
        visibility_mode=EvidenceVisibility.INTERNAL,
        policy=None,
    )
    assert issues[0].state == DataQualityState.UNAVAILABLE

    (cy, cw), (py, pw) = iso_periods_for_reporting(period)
    null_session = FakeSession(
        quality_snapshots=[
            _snap(
                project_id,
                iso_year=cy,
                iso_week=cw,
                gold_set_accuracy_pct=None,
                rework_rate_pct=None,
                iaa_krippendorff_alpha=None,
            ),
            _snap(project_id, iso_year=py, iso_week=pw),
        ]
    )
    _, _, null_issues, _, _ = await load_quality_evidence(
        null_session,
        project_id,
        period,
        visibility_mode=EvidenceVisibility.INTERNAL,
        policy=None,
    )
    assert any(issue.state == DataQualityState.PARTIAL for issue in null_issues)


@pytest.mark.asyncio
async def test_internal_missing_evaluated_count_is_partial() -> None:
    project_id = uuid4()
    period = resolve_reporting_period(date(2026, 6, 17))
    (cy, cw), (py, pw) = iso_periods_for_reporting(period)
    session = FakeSession(
        quality_snapshots=[
            _snap(project_id, iso_year=cy, iso_week=cw, evaluated_item_count=None),
            _snap(project_id, iso_year=py, iso_week=pw),
        ]
    )
    _, _, issues, _, _ = await load_quality_evidence(
        session,
        project_id,
        period,
        visibility_mode=EvidenceVisibility.INTERNAL,
        policy=None,
    )
    assert any(issue.state == DataQualityState.PARTIAL for issue in issues)


@pytest.mark.asyncio
async def test_query_bounded_only_two_periods() -> None:
    project_id = uuid4()
    period = resolve_reporting_period(date(2026, 6, 17))
    (cy, cw), (py, pw) = iso_periods_for_reporting(period)
    session = FakeSession(
        quality_snapshots=[
            _snap(project_id, iso_year=cy, iso_week=cw),
            _snap(project_id, iso_year=py, iso_week=pw),
            _snap(project_id, iso_year=2026, iso_week=1),  # should still be returned by fake
        ]
    )
    # FakeSession returns all rows; adapter filters by period in memory.
    facts, _, _, _, _ = await load_quality_evidence(
        session,
        project_id,
        period,
        visibility_mode=EvidenceVisibility.INTERNAL,
        policy=None,
    )
    assert all(
        (row.iso_year, row.iso_week) in {(cy, cw), (py, pw)}
        for row in [*facts.current_period, *facts.previous_period]
    )
    sql = session.statements[0]
    assert str(project_id) in sql or "quality_snapshots" in sql
    assert "LIMIT" in sql.upper()


# ---------------------------------------------------------------------------
# Pack integration / fingerprint
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_pack_integration_and_fingerprint_behavior() -> None:
    project = _project()
    milestone = _milestone(project.id)
    period = resolve_reporting_period(date(2026, 6, 17))
    (cy, cw), (py, pw) = iso_periods_for_reporting(period)
    snap = _snap(project.id, iso_year=cy, iso_week=cw)
    metrics = [_metric("gold_set_accuracy", visible=True)]

    session_with = FakeSession(
        metrics=metrics,
        milestones=[milestone],
        quality_snapshots=[snap],
    )
    session_without = FakeSession(
        metrics=metrics,
        milestones=[milestone],
        quality_snapshots=[],
    )
    # Hidden quality (no metric) must not change fingerprint when rows exist vs not.
    session_hidden_a = FakeSession(
        metrics=[],
        milestones=[milestone],
        quality_snapshots=[snap],
    )
    session_hidden_b = FakeSession(
        metrics=[],
        milestones=[milestone],
        quality_snapshots=[],
    )
    user = _user(AppRole.CLIENT, project.org_id)
    with patch(
        "app.agents.client_intelligence.evidence_pack.get_visible_project",
        new=AsyncMock(return_value=project),
    ):
        visible_a = await build_client_evidence_pack(
            session_with, user, project.id, as_of=date(2026, 6, 17)
        )
        visible_b = await build_client_evidence_pack(
            session_without, user, project.id, as_of=date(2026, 6, 17)
        )
        hidden_a = await build_client_evidence_pack(
            session_hidden_a, user, project.id, as_of=date(2026, 6, 17)
        )
        hidden_b = await build_client_evidence_pack(
            session_hidden_b, user, project.id, as_of=date(2026, 6, 17)
        )

    assert visible_a.quality.current_period
    assert visible_a.source_fingerprint != visible_b.source_fingerprint
    assert hidden_a.source_fingerprint == hidden_b.source_fingerprint
    assert not any("FROM quality_snapshots" in stmt for stmt in session_hidden_a.statements)
    blob = str(visible_a.model_dump(mode="json"))
    assert "SECRET" not in blob
    assert "client_narrative" not in blob
    assert str(snap.team_id) not in blob


@pytest.mark.asyncio
async def test_internal_pack_includes_quality_without_metric_config() -> None:
    project = _project()
    milestone = _milestone(project.id)
    period = resolve_reporting_period(date(2026, 6, 17))
    (cy, cw), _ = iso_periods_for_reporting(period)
    snap = _snap(project.id, iso_year=cy, iso_week=cw)
    session = FakeSession(milestones=[milestone], quality_snapshots=[snap])
    user = _user(AppRole.DELIVERY_MANAGER, project.org_id)
    with patch(
        "app.agents.client_intelligence.evidence_pack.get_visible_project",
        new=AsyncMock(return_value=project),
    ):
        pack = await build_client_evidence_pack(
            session,
            user,
            project.id,
            as_of=date(2026, 6, 17),
            visibility_mode=EvidenceVisibility.INTERNAL,
        )
    assert pack.quality.current_period
    assert pack.quality.current_period[0].team_id == snap.team_id
    assert pack.policy_fingerprint is None
    assert not any("FROM metric_configurations" in stmt for stmt in session.statements)
    assert any(item.source_table == "quality_snapshots" for item in pack.evidence)


@pytest.mark.asyncio
async def test_scoping_before_quality_query() -> None:
    project = _project()
    session = FakeSession(
        quality_snapshots=[_snap(project.id, iso_year=2026, iso_week=25)],
    )
    from app.core.exceptions import ApiError

    with (
        patch(
            "app.agents.client_intelligence.evidence_pack.get_visible_project",
            new=AsyncMock(side_effect=ApiError(403, "FORBIDDEN", "no")),
        ),
        pytest.raises(ApiError),
    ):
        await build_client_evidence_pack(
            session,
            _user(AppRole.CLIENT, project.org_id),
            project.id,
            as_of=date(2026, 6, 17),
        )
    assert session.statements == []
