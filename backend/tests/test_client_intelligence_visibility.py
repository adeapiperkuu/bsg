"""Client Intelligence deny-by-default visibility policy tests."""

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
    load_client_visibility_policy,
)
from app.agents.client_intelligence.visibility import empty_client_visibility_policy
from app.core.security import CurrentUser
from app.db.models import (
    AlertStatus,
    AlertType,
    AppRole,
    MilestoneStatus,
    ProjectStatus,
    RiskTier,
)


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
        risks: list[object] | None = None,
        bottlenecks: list[object] | None = None,
    ) -> None:
        self.metrics = metrics or []
        self.milestones = milestones or []
        self.throughput = throughput
        self.confidence = confidence
        self.risks = risks or []
        self.bottlenecks = bottlenecks or []
        self.statements: list[str] = []

    async def execute(self, stmt) -> FakeResult:
        compiled = str(stmt.compile(compile_kwargs={"literal_binds": True}))
        self.statements.append(compiled)
        if "FROM metric_configurations" in compiled:
            assert "LIMIT" in compiled.upper() or "limit" in compiled
            assert "ORDER BY" in compiled.upper() or "order by" in compiled
            assert "is_client_visible" in compiled
            # Mirror SQL filter: only client-visible rows are returned.
            visible_rows = [row for row in self.metrics if getattr(row, "is_client_visible", False)]
            return FakeResult(None, visible_rows)
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
                "knowledge_documents" in compiled.lower()
                and "knowledge_document_versions" in compiled.lower()
                and "chunk_text" not in compiled.lower()
            )
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
        email="ci-visibility@example.com",
        role=role,
        is_active=True,
    )


def _project(org_id=None) -> SimpleNamespace:
    return SimpleNamespace(
        id=uuid4(),
        org_id=org_id or uuid4(),
        name="Aurora Labeling",
        status=ProjectStatus.ACTIVE,
        description="INTERNAL NOTE",
    )


def _metric(key: str, *, visible: bool, order: int = 1) -> SimpleNamespace:
    return SimpleNamespace(
        id=uuid4(),
        metric_key=key,
        display_label=key,
        is_client_visible=visible,
        display_order=order,
        deleted_at=None,
    )


def _milestone(project_id) -> SimpleNamespace:
    return SimpleNamespace(
        id=uuid4(),
        project_id=project_id,
        name="Batch 14 QA",
        description="Internal note",
        planned_date=date(2026, 6, 24),
        actual_date=None,
        status=MilestoneStatus.ON_TRACK,
        deleted_at=None,
        updated_at=datetime(2026, 6, 17, tzinfo=UTC),
    )


def _throughput(project_id) -> SimpleNamespace:
    return SimpleNamespace(
        id=uuid4(),
        project_id=project_id,
        snapshot_date=date(2026, 6, 18),
        units_completed=120,
        units_forecast=130,
        rolling_7day_units=80,
    )


def _confidence(project_id, milestone_id) -> SimpleNamespace:
    return SimpleNamespace(
        id=uuid4(),
        project_id=project_id,
        milestone_id=milestone_id,
        score_pct=Decimal("92.50"),
        status=MilestoneStatus.ON_TRACK,
        forecast_completion_date=date(2026, 6, 24),
        model_version="delivery-v1-secret",
        created_at=datetime(2026, 6, 18, 12, 0, tzinfo=UTC),
    )


def _risk(project_id) -> SimpleNamespace:
    return SimpleNamespace(
        id=uuid4(),
        project_id=project_id,
        milestone_id=None,
        alert_type=AlertType.DELIVERY_RISK,
        risk_tier=RiskTier.HIGH,
        title="SECRET_RISK_TITLE",
        detail="SECRET_RISK_DETAIL annotator fatigue",
        contributing_causes={"reviewer_id": str(uuid4())},
        status=AlertStatus.OPEN,
        created_at=datetime(2026, 6, 17, tzinfo=UTC),
        deleted_at=None,
    )


def _bottleneck(project_id) -> SimpleNamespace:
    return SimpleNamespace(
        id=uuid4(),
        project_id=project_id,
        team_id=uuid4(),
        title="SECRET_BOTTLENECK_TITLE",
        detail="SECRET_BOTTLENECK_DETAIL reviewer Alice",
        status=AlertStatus.OPEN,
        created_at=datetime(2026, 6, 16, tzinfo=UTC),
        deleted_at=None,
        resolved_by=uuid4(),
    )


# ---------------------------------------------------------------------------
# Policy loader
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_loader_only_known_client_visible_keys() -> None:
    session = FakeSession(
        metrics=[
            _metric("delivery_confidence", visible=True, order=1),
            _metric("throughput_rolling_7d", visible=True, order=2),
            _metric("iaa_krippendorff_alpha", visible=False, order=5),
            _metric("mystery_metric", visible=True, order=9),
            _metric("gold_set_accuracy", visible=True, order=3),
        ]
    )
    policy = await load_client_visibility_policy(session)
    assert policy.visible_metrics == frozenset(
        {
            ClientVisibleMetric.DELIVERY_CONFIDENCE,
            ClientVisibleMetric.THROUGHPUT_ROLLING_7D,
            ClientVisibleMetric.GOLD_SET_ACCURACY,
        }
    )
    assert ClientVisibleMetric.REWORK_RATE not in policy.visible_metrics
    assert not policy.risk_summary_visible
    assert not policy.bottleneck_summary_visible


@pytest.mark.asyncio
async def test_loader_false_and_missing_config_deny_by_default() -> None:
    false_only = await load_client_visibility_policy(
        FakeSession(metrics=[_metric("delivery_confidence", visible=False)])
    )
    assert false_only.visible_metrics == frozenset()

    empty = await load_client_visibility_policy(FakeSession(metrics=[]))
    assert empty.visible_metrics == frozenset()
    assert empty.fingerprint() == empty_client_visibility_policy().fingerprint()


@pytest.mark.asyncio
async def test_loader_query_bounded_and_ordered() -> None:
    session = FakeSession(metrics=[_metric("rework_rate", visible=True, order=4)])
    await load_client_visibility_policy(session)
    assert len(session.statements) == 1
    sql = session.statements[0].upper()
    assert "LIMIT" in sql
    assert "ORDER BY" in sql


def test_policy_fingerprint_deterministic() -> None:
    left = ClientVisibilityPolicy(
        visible_metrics=frozenset(
            {
                ClientVisibleMetric.REWORK_RATE,
                ClientVisibleMetric.DELIVERY_CONFIDENCE,
            }
        )
    )
    right = ClientVisibilityPolicy(
        visible_metrics=frozenset(
            {
                ClientVisibleMetric.DELIVERY_CONFIDENCE,
                ClientVisibleMetric.REWORK_RATE,
            }
        )
    )
    assert left.fingerprint() == right.fingerprint()


# ---------------------------------------------------------------------------
# Client-safe pack projection
# ---------------------------------------------------------------------------


async def _build_pack(
    *,
    role: AppRole,
    metrics: list[object],
    visibility_mode: EvidenceVisibility | None = None,
    as_of: date = date(2026, 6, 18),
):
    project = _project()
    milestone = _milestone(project.id)
    session = FakeSession(
        metrics=metrics,
        milestones=[milestone],
        throughput=_throughput(project.id),
        confidence=_confidence(project.id, milestone.id),
        risks=[_risk(project.id)],
        bottlenecks=[_bottleneck(project.id)],
    )
    user = _user(role, project.org_id)
    with patch(
        "app.agents.client_intelligence.evidence_pack.get_visible_project",
        new=AsyncMock(return_value=project),
    ):
        pack = await build_client_evidence_pack(
            session,
            user,
            project.id,
            as_of=as_of,
            visibility_mode=visibility_mode,
        )
    return pack, session, project, milestone


@pytest.mark.asyncio
async def test_client_safe_excludes_risks_and_bottlenecks_completely() -> None:
    pack, session, _, _ = await _build_pack(role=AppRole.CLIENT, metrics=[])
    assert pack.delivery.open_risks == []
    assert pack.delivery.open_bottlenecks == []
    assert not any(item.source_table == "risk_alerts" for item in pack.evidence)
    assert not any(item.source_table == "bottlenecks" for item in pack.evidence)
    assert not any("FROM risk_alerts" in stmt for stmt in session.statements)
    assert not any("FROM bottlenecks" in stmt for stmt in session.statements)
    blob = str(pack.model_dump(mode="json"))
    assert "SECRET_RISK_TITLE" not in blob
    assert "SECRET_RISK_DETAIL" not in blob
    assert "SECRET_BOTTLENECK_TITLE" not in blob
    assert "SECRET_BOTTLENECK_DETAIL" not in blob
    assert "annotator" not in blob.lower()
    assert "alice" not in blob.lower()


@pytest.mark.asyncio
async def test_delivery_confidence_gated_by_metric_config() -> None:
    absent, _, _, _ = await _build_pack(role=AppRole.CLIENT, metrics=[])
    assert absent.delivery.latest_delivery_confidence is None
    assert not any(item.source_table == "delivery_confidence_scores" for item in absent.evidence)
    assert any(
        item.source == "delivery_confidence_scores" and item.reason == "not_configured"
        for item in absent.visibility_limitations
    )
    # Redaction is not unavailable data quality.
    assert not any(
        issue.source == "delivery_confidence_scores" and issue.state == DataQualityState.UNAVAILABLE
        for issue in absent.data_quality
    )

    present, _, _, _ = await _build_pack(
        role=AppRole.CLIENT,
        metrics=[_metric("delivery_confidence", visible=True)],
    )
    assert present.delivery.latest_delivery_confidence is not None
    assert present.delivery.latest_delivery_confidence.score_pct == Decimal("92.50")
    assert present.delivery.latest_delivery_confidence.model_version is None
    blob = str(present.model_dump(mode="json"))
    assert "delivery-v1-secret" not in blob


@pytest.mark.asyncio
async def test_throughput_rolling_gated_and_unauthorized_fields_absent() -> None:
    absent, _, _, _ = await _build_pack(role=AppRole.CLIENT, metrics=[])
    assert absent.delivery.latest_throughput is None

    present, _, _, _ = await _build_pack(
        role=AppRole.CLIENT,
        metrics=[_metric("throughput_rolling_7d", visible=True)],
    )
    assert present.delivery.latest_throughput is not None
    assert present.delivery.latest_throughput.rolling_7day_units == 80
    assert present.delivery.latest_throughput.units_completed is None
    assert present.delivery.latest_throughput.units_forecast is None
    evidence = next(
        item for item in present.evidence if item.source_table == "throughput_snapshots"
    )
    assert "units_completed" not in evidence.claim_keys
    assert "units_forecast" not in evidence.claim_keys
    assert "rolling_7day_units" in evidence.claim_keys


@pytest.mark.asyncio
async def test_hidden_facts_do_not_affect_client_safe_fingerprint() -> None:
    project = _project()
    milestone = _milestone(project.id)
    metrics = [_metric("delivery_confidence", visible=True)]
    shared_throughput = _throughput(project.id)
    shared_confidence = _confidence(project.id, milestone.id)
    session_a = FakeSession(
        metrics=metrics,
        milestones=[milestone],
        throughput=shared_throughput,
        confidence=shared_confidence,
    )
    session_b = FakeSession(
        metrics=metrics,
        milestones=[milestone],
        throughput=shared_throughput,
        confidence=shared_confidence,
        risks=[_risk(project.id)],
        bottlenecks=[_bottleneck(project.id)],
    )
    user = _user(AppRole.CLIENT, project.org_id)
    with patch(
        "app.agents.client_intelligence.evidence_pack.get_visible_project",
        new=AsyncMock(return_value=project),
    ):
        pack_a = await build_client_evidence_pack(
            session_a, user, project.id, as_of=date(2026, 6, 18)
        )
        pack_b = await build_client_evidence_pack(
            session_b, user, project.id, as_of=date(2026, 6, 18)
        )
    assert pack_a.source_fingerprint == pack_b.source_fingerprint
    assert pack_a.policy_fingerprint == pack_b.policy_fingerprint


@pytest.mark.asyncio
async def test_internal_user_requesting_client_safe_matches_client() -> None:
    metrics = [
        _metric("delivery_confidence", visible=True),
        _metric("throughput_rolling_7d", visible=True),
    ]
    project = _project()
    milestone = _milestone(project.id)
    throughput = _throughput(project.id)
    confidence = _confidence(project.id, milestone.id)

    def _session() -> FakeSession:
        return FakeSession(
            metrics=metrics,
            milestones=[milestone],
            throughput=throughput,
            confidence=confidence,
            risks=[_risk(project.id)],
            bottlenecks=[_bottleneck(project.id)],
        )

    with patch(
        "app.agents.client_intelligence.evidence_pack.get_visible_project",
        new=AsyncMock(return_value=project),
    ):
        client_pack = await build_client_evidence_pack(
            _session(),
            _user(AppRole.CLIENT, project.org_id),
            project.id,
            as_of=date(2026, 6, 18),
        )
        dm_pack = await build_client_evidence_pack(
            _session(),
            _user(AppRole.DELIVERY_MANAGER, project.org_id),
            project.id,
            as_of=date(2026, 6, 18),
            visibility_mode=EvidenceVisibility.CLIENT_SAFE,
        )
    assert client_pack.visibility_mode == dm_pack.visibility_mode == EvidenceVisibility.CLIENT_SAFE
    assert client_pack.source_fingerprint == dm_pack.source_fingerprint
    assert client_pack.policy_fingerprint == dm_pack.policy_fingerprint
    assert client_pack.delivery.model_dump() == dm_pack.delivery.model_dump()
    assert client_pack.delivery.open_risks == []
    assert dm_pack.delivery.latest_delivery_confidence is not None
    assert dm_pack.delivery.latest_delivery_confidence.model_version is None


@pytest.mark.asyncio
async def test_internal_pack_retains_risk_detail_and_skips_metric_config() -> None:
    pack, session, _, _ = await _build_pack(
        role=AppRole.DELIVERY_MANAGER,
        metrics=[_metric("delivery_confidence", visible=True)],
        visibility_mode=EvidenceVisibility.INTERNAL,
    )
    assert pack.visibility_mode == EvidenceVisibility.INTERNAL
    assert pack.policy_fingerprint is None
    assert pack.delivery.open_risks[0].title == "SECRET_RISK_TITLE"
    assert pack.delivery.open_risks[0].detail is not None
    assert pack.delivery.latest_delivery_confidence is not None
    assert pack.delivery.latest_delivery_confidence.model_version == "delivery-v1-secret"
    assert not any("FROM metric_configurations" in stmt for stmt in session.statements)


@pytest.mark.asyncio
async def test_visibility_redaction_distinct_from_missing_data() -> None:
    project = _project()
    milestone = _milestone(project.id)
    session = FakeSession(
        metrics=[],
        milestones=[milestone],
        throughput=None,
        confidence=None,
        risks=[_risk(project.id)],
    )
    user = _user(AppRole.CLIENT, project.org_id)
    with patch(
        "app.agents.client_intelligence.evidence_pack.get_visible_project",
        new=AsyncMock(return_value=project),
    ):
        pack = await build_client_evidence_pack(session, user, project.id, as_of=date(2026, 6, 18))
    # Confidence/throughput never queried when not configured visible — redaction only.
    assert not any("FROM throughput_snapshots" in stmt for stmt in session.statements)
    assert not any("FROM delivery_confidence_scores" in stmt for stmt in session.statements)
    assert any(item.reason == "not_configured" for item in pack.visibility_limitations)
    assert not any(
        issue.source in {"throughput_snapshots", "delivery_confidence_scores"}
        and issue.state == DataQualityState.UNAVAILABLE
        for issue in pack.data_quality
    )
