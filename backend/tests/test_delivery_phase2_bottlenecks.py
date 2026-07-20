from __future__ import annotations

from contextlib import asynccontextmanager
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import UUID, uuid4

import pytest
from pydantic import ValidationError
from sqlalchemy import UniqueConstraint

from app.agents.delivery.analytics.bottlenecks import (
    BottleneckAnalysisResult,
    BottleneckDetectionSignal,
    BottleneckEvidencePoint,
    TeamThroughputObservation,
    analyze_team_bottlenecks,
    calculate_daily_team_shares,
    stable_bottleneck_source_key,
)
from app.agents.delivery.configuration import (
    DEFAULT_DELIVERY_SCORING_THRESHOLDS,
    DeliveryBottleneckThresholds,
)
from app.agents.delivery.schemas.operations import (
    BottleneckResolveRequest,
    TeamThroughputSnapshotCreate,
    TeamThroughputSnapshotUpdate,
)
from app.agents.delivery.services import bottleneck_service, team_throughput_service
from app.agents.delivery.services.bottleneck_service import (
    BottleneckDetectionResult,
    acknowledge_bottleneck,
    detect_project_bottlenecks,
    resolve_bottleneck,
)
from app.agents.delivery.services.scoring_service import (
    ScoringContext,
    compute_delivery_scores,
)
from app.agents.delivery.services.team_throughput_service import (
    correct_team_snapshot,
    create_or_update_team_snapshot,
)
from app.core.exceptions import ApiError
from app.db.models import (
    AlertStatus,
    AppRole,
    AuditLog,
    Bottleneck,
    BottleneckSourceType,
    Project,
    RiskTier,
    Team,
    TeamThroughputSnapshot,
    TeamThroughputSourceType,
    ThroughputSnapshot,
)
from tests.conftest import override_user

ORG_ID = UUID("11111111-1111-1111-1111-111111111111")
PROJECT_ID = UUID("22222222-2222-2222-2222-222222222222")
TEAM_A = UUID("33333333-3333-3333-3333-333333333333")
TEAM_B = UUID("44444444-4444-4444-4444-444444444444")
ACTOR_ID = UUID("55555555-5555-5555-5555-555555555555")
TODAY = date(2026, 7, 20)


class _Scalars:
    def __init__(self, items):
        self.items = items

    def all(self):
        return list(self.items)

    def __iter__(self):
        return iter(self.items)


class _Result:
    def __init__(self, items):
        self.items = items

    def scalars(self):
        return _Scalars(self.items)

    def scalar_one_or_none(self):
        return self.items[0] if self.items else None


class _Session:
    def __init__(self, results=()):
        self.results = list(results)
        self.execute_count = 0
        self.added = []
        self.flush_count = 0

    async def execute(self, _statement):
        self.execute_count += 1
        return _Result(self.results.pop(0) if self.results else [])

    def add(self, item):
        self.added.append(item)

    async def flush(self):
        self.flush_count += 1

    @asynccontextmanager
    async def begin_nested(self):
        yield


def _project() -> Project:
    return Project(
        id=PROJECT_ID,
        org_id=ORG_ID,
        name="Atlas",
        description=None,
        vertical="AI",
        status="active",
        start_date=TODAY,
        target_end_date=TODAY + timedelta(days=30),
        actual_end_date=None,
        daily_target_units=100,
    )


def _team(team_id: UUID, name: str = "Team") -> Team:
    return Team(
        id=team_id,
        project_id=PROJECT_ID,
        org_id=ORG_ID,
        name=name,
        site="kosovo",
        domain="general",
        is_active=True,
        deleted_at=None,
    )


def _actor(role: AppRole = AppRole.DELIVERY_MANAGER):
    return SimpleNamespace(
        id=ACTOR_ID,
        org_id=ORG_ID,
        email="manager@example.com",
        role=role,
        is_active=True,
    )


def _observations(
    history_days: int = 5,
    current_days: int = 5,
    *,
    current_a_units: int = 20,
    current_b_units: int = 80,
    current_a_headcount: int | None = 10,
    historical_headcount: int | None = 10,
) -> list[TeamThroughputObservation]:
    result: list[TeamThroughputObservation] = []
    start = TODAY - timedelta(days=history_days + current_days - 1)
    for index in range(history_days + current_days):
        current = index >= history_days
        snapshot_date = start + timedelta(days=index)
        result.extend(
            [
                TeamThroughputObservation(
                    team_id=TEAM_A,
                    snapshot_date=snapshot_date,
                    units_completed=current_a_units if current else 50,
                    active_headcount=(current_a_headcount if current else historical_headcount),
                ),
                TeamThroughputObservation(
                    team_id=TEAM_B,
                    snapshot_date=snapshot_date,
                    units_completed=current_b_units if current else 50,
                    active_headcount=10,
                ),
            ]
        )
    return result


def _analysis(
    observations: list[TeamThroughputObservation],
    thresholds: DeliveryBottleneckThresholds | None = None,
) -> BottleneckAnalysisResult:
    return analyze_team_bottlenecks(
        observations,
        organisation_id=ORG_ID,
        project_id=PROJECT_ID,
        expected_team_ids={TEAM_A, TEAM_B},
        thresholds=thresholds or DeliveryBottleneckThresholds(),
        as_of_date=TODAY,
    )


def _signal(*, latest: date = TODAY, decline: str = "60.00") -> BottleneckDetectionSignal:
    return BottleneckDetectionSignal(
        organisation_id=ORG_ID,
        project_id=PROJECT_ID,
        team_id=TEAM_A,
        source_key=stable_bottleneck_source_key(ORG_ID, PROJECT_ID, TEAM_A),
        severity="high",
        current_share=Decimal("20"),
        historical_share=Decimal("50"),
        decline_pct=Decimal(decline),
        headcount_change_pct=Decimal("0"),
        consecutive_days=5,
        observation_window_days=5,
        latest_observation_date=latest,
        evidence=(
            BottleneckEvidencePoint(
                snapshot_date=latest,
                current_share=Decimal("20"),
                historical_share=Decimal("50"),
                decline_pct=Decimal(decline),
                headcount_change_pct=Decimal("0"),
            ),
        ),
    )


def _bottleneck(status: AlertStatus = AlertStatus.OPEN) -> Bottleneck:
    now = datetime(2026, 7, 20, tzinfo=UTC)
    return Bottleneck(
        id=uuid4(),
        project_id=PROJECT_ID,
        org_id=ORG_ID,
        team_id=TEAM_A,
        title="Sustained decline",
        detail="Evidence",
        status=status,
        severity=RiskTier.HIGH,
        source_type=BottleneckSourceType.DETECTOR,
        source_key=stable_bottleneck_source_key(ORG_ID, PROJECT_ID, TEAM_A),
        detector_version="v1",
        evidence_json={"decline_pct": "60.00"},
        first_detected_at=now,
        last_detected_at=now,
        last_evidence_hash="old",
        occurrence_count=1,
        deleted_at=None,
    )


def test_phase2_model_contract_is_additive_and_tenant_safe() -> None:
    table = TeamThroughputSnapshot.__table__
    assert set(table.columns.keys()) >= {
        "org_id",
        "project_id",
        "team_id",
        "snapshot_date",
        "units_completed",
        "active_headcount",
        "source_type",
        "created_by",
        "updated_by",
    }
    unique = next(item for item in table.constraints if isinstance(item, UniqueConstraint))
    assert [column.name for column in unique.columns] == [
        "org_id",
        "project_id",
        "team_id",
        "snapshot_date",
    ]
    index_names = {index.name for index in table.indexes}
    assert "team_throughput_snapshots_org_project_date_idx" in index_names
    assert "team_throughput_snapshots_org_project_team_date_idx" in index_names
    assert "team_throughput_snapshots_org_date_idx" in index_names
    project_unique = next(
        item
        for item in ThroughputSnapshot.__table__.constraints
        if isinstance(item, UniqueConstraint)
    )
    assert [column.name for column in project_unique.columns] == [
        "project_id",
        "snapshot_date",
    ]


@pytest.mark.parametrize(
    "payload",
    [
        {"team_id": TEAM_A, "snapshot_date": TODAY, "units_completed": -1},
        {
            "team_id": TEAM_A,
            "snapshot_date": TODAY,
            "units_completed": 1,
            "active_headcount": -1,
        },
        {
            "team_id": TEAM_A,
            "snapshot_date": TODAY,
            "units_completed": 1,
            "source_reference": "x" * 501,
        },
        {
            "team_id": TEAM_A,
            "snapshot_date": TODAY,
            "units_completed": 1,
            "notes": "x" * 2001,
        },
    ],
)
def test_snapshot_schema_rejects_invalid_values(payload: dict) -> None:
    with pytest.raises(ValidationError):
        TeamThroughputSnapshotCreate.model_validate(payload)


def test_snapshot_schema_accepts_zero_output_and_missing_headcount() -> None:
    payload = TeamThroughputSnapshotCreate(
        team_id=TEAM_A,
        snapshot_date=TODAY,
        units_completed=0,
    )
    assert payload.units_completed == 0
    assert payload.active_headcount is None
    assert payload.source_type == TeamThroughputSourceType.MANUAL


def test_snapshot_update_rejects_explicit_null_units() -> None:
    with pytest.raises(ValidationError):
        TeamThroughputSnapshotUpdate(units_completed=None)


def test_bottleneck_config_defaults_and_relationship_validation() -> None:
    defaults = DEFAULT_DELIVERY_SCORING_THRESHOLDS.bottleneck
    assert defaults.observation_days == 5
    assert defaults.decline_threshold_pct == Decimal("20")
    assert defaults.recovery_days == 3
    assert defaults.minimum_history_days == 5
    assert defaults.require_headcount is True
    with pytest.raises(ValidationError):
        DeliveryBottleneckThresholds(recovery_days=6, observation_days=5)
    with pytest.raises(ValidationError):
        DeliveryBottleneckThresholds(minimum_history_days=15, historical_window_days=14)
    with pytest.raises(ValidationError):
        DeliveryBottleneckThresholds(severity_medium_pct=10)


def test_daily_share_math_excludes_zero_and_incomplete_dates() -> None:
    incomplete_date = TODAY - timedelta(days=2)
    zero_date = TODAY - timedelta(days=1)
    observations = [
        TeamThroughputObservation(
            team_id=TEAM_A,
            snapshot_date=incomplete_date,
            units_completed=10,
            active_headcount=1,
        ),
        TeamThroughputObservation(
            team_id=TEAM_A,
            snapshot_date=zero_date,
            units_completed=0,
            active_headcount=1,
        ),
        TeamThroughputObservation(
            team_id=TEAM_B,
            snapshot_date=zero_date,
            units_completed=0,
            active_headcount=1,
        ),
        TeamThroughputObservation(
            team_id=TEAM_A,
            snapshot_date=TODAY,
            units_completed=25,
            active_headcount=1,
        ),
        TeamThroughputObservation(
            team_id=TEAM_B,
            snapshot_date=TODAY,
            units_completed=75,
            active_headcount=1,
        ),
    ]
    shares, skips = calculate_daily_team_shares(
        observations,
        expected_team_ids={TEAM_A, TEAM_B},
        minimum_project_units=1,
        as_of_date=TODAY,
    )
    assert [(item.team_id, item.throughput_share) for item in shares] == [
        (TEAM_A, Decimal("25.0000")),
        (TEAM_B, Decimal("75.0000")),
    ]
    assert {item.reason for item in skips} == {
        "incomplete_team_coverage",
        "zero_project_throughput",
    }


def test_sustained_unexplained_decline_emits_high_signal() -> None:
    result = _analysis(_observations())
    assert len(result.signals) == 1
    signal = result.signals[0]
    assert signal.team_id == TEAM_A
    assert signal.current_share == Decimal("20.0000")
    assert signal.historical_share == Decimal("50.0000")
    assert signal.decline_pct == Decimal("60.00")
    assert signal.severity == "high"
    assert signal.consecutive_days == 5


def test_one_day_decline_is_not_sustained() -> None:
    observations = _observations(current_a_units=50, current_b_units=50)
    observations[-2] = observations[-2].model_copy(update={"units_completed": Decimal("20")})
    observations[-1] = observations[-1].model_copy(update={"units_completed": Decimal("80")})
    result = _analysis(observations)
    assert result.signals == ()
    assert "decline_not_sustained" in {item.reason for item in result.skipped_reasons}


def test_headcount_proportional_decline_is_explained() -> None:
    result = _analysis(
        _observations(current_a_headcount=4),
        DeliveryBottleneckThresholds(headcount_tolerance_pct=Decimal("5")),
    )
    assert result.signals == ()
    assert "decline_explained_by_headcount" in {item.reason for item in result.skipped_reasons}


def test_missing_headcount_is_insufficient_evidence_by_default() -> None:
    result = _analysis(_observations(current_a_headcount=None))
    assert result.signals == ()
    assert "missing_headcount" in {item.reason for item in result.skipped_reasons}


def test_missing_headcount_can_be_allowed_by_validated_configuration() -> None:
    result = _analysis(
        _observations(current_a_headcount=None, historical_headcount=None),
        DeliveryBottleneckThresholds(require_headcount=False),
    )
    assert len(result.signals) == 1
    assert result.signals[0].headcount_change_pct is None


def test_explicit_zero_team_output_is_evidence_but_missing_row_is_not() -> None:
    explicit_zero = _analysis(_observations(current_a_units=0, current_b_units=100))
    assert len(explicit_zero.signals) == 1
    assert explicit_zero.signals[0].current_share == Decimal("0.0000")

    missing = [
        item
        for item in _observations(current_a_units=0, current_b_units=100)
        if not (item.team_id == TEAM_A and item.snapshot_date == TODAY)
    ]
    incomplete = _analysis(missing)
    assert "incomplete_team_coverage" in {item.reason for item in incomplete.skipped_reasons}


def test_duplicate_team_date_is_excluded_and_custom_threshold_applies() -> None:
    observations = _observations()
    observations.append(observations[-2].model_copy())
    duplicate = _analysis(observations)
    assert "duplicate_team_date" in {item.reason for item in duplicate.skipped_reasons}

    strict = _analysis(
        _observations(),
        DeliveryBottleneckThresholds(
            decline_threshold_pct=Decimal("65"),
            severity_medium_pct=Decimal("70"),
            severity_high_pct=Decimal("80"),
            severity_critical_pct=Decimal("90"),
        ),
    )
    assert strict.signals == ()


def test_insufficient_and_stale_data_do_not_signal_or_recover() -> None:
    insufficient = _analysis(_observations(history_days=4))
    assert insufficient.signals == ()
    stale_observations = [
        item.model_copy(update={"snapshot_date": item.snapshot_date - timedelta(days=3)})
        for item in _observations()
    ]
    stale = _analysis(stale_observations)
    assert stale.signals == ()
    assert stale.recovered_team_ids == ()
    assert "stale_data" in {item.reason for item in stale.skipped_reasons}


def test_recovery_requires_configured_valid_days() -> None:
    observations = _observations()
    for offset in range(3):
        index = len(observations) - (offset + 1) * 2
        observations[index] = observations[index].model_copy(
            update={"units_completed": Decimal("50")}
        )
        observations[index + 1] = observations[index + 1].model_copy(
            update={"units_completed": Decimal("50")}
        )
    result = _analysis(observations)
    assert result.signals == ()
    assert TEAM_A in result.recovered_team_ids


def test_future_data_does_not_leak_into_analysis() -> None:
    observations = _observations()
    observations.extend(
        [
            TeamThroughputObservation(
                team_id=TEAM_A,
                snapshot_date=TODAY + timedelta(days=1),
                units_completed=0,
                active_headcount=10,
            ),
            TeamThroughputObservation(
                team_id=TEAM_B,
                snapshot_date=TODAY + timedelta(days=1),
                units_completed=100,
                active_headcount=10,
            ),
        ]
    )
    result = _analysis(observations)
    assert result.signals[0].latest_observation_date == TODAY
    assert "future_observation" in {item.reason for item in result.skipped_reasons}


def test_source_key_and_result_order_are_stable() -> None:
    assert stable_bottleneck_source_key(ORG_ID, PROJECT_ID, TEAM_A) == (
        f"delivery-team-throughput-bottleneck:v1:{ORG_ID}:{PROJECT_ID}:{TEAM_A}"
    )
    forward = _analysis(_observations())
    reverse = _analysis(list(reversed(_observations())))
    assert forward == reverse


def test_active_bottleneck_scoring_is_unchanged_and_resolved_rows_are_excluded() -> None:
    raw = {
        "as_of_date": TODAY,
        "project": {
            "id": PROJECT_ID,
            "name": "Atlas",
            "status": "active",
            "daily_target_units": 10,
            "target_end_date": TODAY + timedelta(days=30),
        },
        "throughput_snapshots": [
            {
                "snapshot_date": TODAY,
                "units_completed": 10,
                "rolling_7day_units": 70,
            }
        ],
        "milestones": [],
        "risks": [],
        "bottlenecks": [],
        "quality_snapshot": None,
    }
    without = compute_delivery_scores(ScoringContext.from_raw_data(raw))
    raw["bottlenecks"] = [{"status": AlertStatus.ACKNOWLEDGED.value}]
    active = compute_delivery_scores(ScoringContext.from_raw_data(raw))
    assert active.confidence == without.confidence
    assert active.risk == without.risk + Decimal("5.00")
    assert active.traffic_light == "yellow"
    # Resolved rows are filtered by the scoring input query and therefore are not
    # supplied to the pure context at all.
    raw["bottlenecks"] = []
    resolved = compute_delivery_scores(ScoringContext.from_raw_data(raw))
    assert resolved == without


@pytest.mark.asyncio
async def test_exact_duplicate_snapshot_is_idempotent(monkeypatch) -> None:
    team = _team(TEAM_A)
    existing = TeamThroughputSnapshot(
        id=uuid4(),
        org_id=ORG_ID,
        project_id=PROJECT_ID,
        team_id=TEAM_A,
        snapshot_date=TODAY,
        units_completed=0,
        active_headcount=None,
        source_type=TeamThroughputSourceType.MANUAL,
        source_reference=None,
        notes=None,
        created_by=ACTOR_ID,
        updated_by=ACTOR_ID,
    )
    session = _Session(results=[[team], [], [existing]])
    detector = AsyncMock()
    monkeypatch.setattr(team_throughput_service, "detect_project_bottlenecks", detector)
    result = await create_or_update_team_snapshot(
        session,
        project=_project(),
        actor=_actor(),
        payload=TeamThroughputSnapshotCreate(
            team_id=TEAM_A,
            snapshot_date=TODAY,
            units_completed=0,
        ),
    )
    assert result.snapshot is existing
    assert result.created is False
    assert result.corrected is False
    detector.assert_not_awaited()
    assert not any(isinstance(item, AuditLog) for item in session.added)


@pytest.mark.asyncio
async def test_changed_duplicate_is_audited_correction_and_triggers_once(monkeypatch) -> None:
    team = _team(TEAM_A)
    existing = TeamThroughputSnapshot(
        id=uuid4(),
        org_id=ORG_ID,
        project_id=PROJECT_ID,
        team_id=TEAM_A,
        snapshot_date=TODAY,
        units_completed=10,
        active_headcount=2,
        source_type=TeamThroughputSourceType.MANUAL,
        source_reference=None,
        notes=None,
        created_by=ACTOR_ID,
        updated_by=ACTOR_ID,
    )
    session = _Session(results=[[team], [], [existing]])
    detection = BottleneckDetectionResult(analysis=BottleneckAnalysisResult())
    detector = AsyncMock(return_value=detection)
    monkeypatch.setattr(team_throughput_service, "detect_project_bottlenecks", detector)
    result = await create_or_update_team_snapshot(
        session,
        project=_project(),
        actor=_actor(),
        payload=TeamThroughputSnapshotCreate(
            team_id=TEAM_A,
            snapshot_date=TODAY,
            units_completed=12,
            active_headcount=2,
        ),
    )
    assert result.corrected is True
    assert existing.units_completed == 12
    assert existing.source_type == TeamThroughputSourceType.CORRECTION
    detector.assert_awaited_once()
    audit = next(item for item in session.added if isinstance(item, AuditLog))
    assert audit.event_type == "team_throughput_snapshot_corrected"
    assert audit.payload["previous"]["units_completed"] == 10


@pytest.mark.asyncio
async def test_team_project_mismatch_is_rejected(monkeypatch) -> None:
    session = _Session(results=[[]])
    detector = AsyncMock()
    monkeypatch.setattr(team_throughput_service, "detect_project_bottlenecks", detector)
    with pytest.raises(ApiError) as exc:
        await create_or_update_team_snapshot(
            session,
            project=_project(),
            actor=_actor(),
            payload=TeamThroughputSnapshotCreate(
                team_id=TEAM_A,
                snapshot_date=TODAY,
                units_completed=1,
            ),
        )
    assert exc.value.status_code == 422
    assert exc.value.code == "TEAM_PROJECT_MISMATCH"
    detector.assert_not_awaited()


@pytest.mark.asyncio
async def test_future_snapshot_is_rejected_before_database_or_downstream_work(
    monkeypatch,
) -> None:
    session = _Session()
    detector = AsyncMock()
    monkeypatch.setattr(team_throughput_service, "detect_project_bottlenecks", detector)
    with pytest.raises(ApiError) as exc:
        await create_or_update_team_snapshot(
            session,
            project=_project(),
            actor=_actor(),
            payload=TeamThroughputSnapshotCreate(
                team_id=TEAM_A,
                snapshot_date=datetime.now(UTC).date() + timedelta(days=1),
                units_completed=1,
            ),
        )
    assert exc.value.code == "FUTURE_SNAPSHOT_DATE"
    assert session.execute_count == 0
    detector.assert_not_awaited()


@pytest.mark.asyncio
async def test_patch_correction_runs_detection_once(monkeypatch) -> None:
    snapshot = TeamThroughputSnapshot(
        id=uuid4(),
        org_id=ORG_ID,
        project_id=PROJECT_ID,
        team_id=TEAM_A,
        snapshot_date=TODAY,
        units_completed=10,
        active_headcount=2,
        source_type=TeamThroughputSourceType.MANUAL,
        source_reference=None,
        notes=None,
        created_by=ACTOR_ID,
        updated_by=ACTOR_ID,
    )
    session = _Session()
    detector = AsyncMock(
        return_value=BottleneckDetectionResult(analysis=BottleneckAnalysisResult())
    )
    monkeypatch.setattr(team_throughput_service, "detect_project_bottlenecks", detector)
    result = await correct_team_snapshot(
        session,
        project=_project(),
        snapshot=snapshot,
        actor=_actor(),
        payload=TeamThroughputSnapshotUpdate(units_completed=11),
    )
    assert result.corrected is True
    detector.assert_awaited_once()


@pytest.mark.asyncio
async def test_first_detection_creates_one_open_bottleneck_and_audit(monkeypatch) -> None:
    session = _Session(results=[[], [_team(TEAM_A, "Alpha")], [], []])
    analysis = BottleneckAnalysisResult(
        signals=(_signal(),),
        evaluated_teams=1,
        valid_observation_days=10,
        latest_valid_date=TODAY,
    )
    monkeypatch.setattr(
        bottleneck_service,
        "load_delivery_scoring_thresholds",
        AsyncMock(return_value=DEFAULT_DELIVERY_SCORING_THRESHOLDS),
    )
    monkeypatch.setattr(
        bottleneck_service,
        "analyze_team_bottlenecks",
        lambda *_args, **_kwargs: analysis,
    )
    notify = AsyncMock(return_value=1)
    monkeypatch.setattr(bottleneck_service, "_send_transition_notifications", notify)
    result = await detect_project_bottlenecks(
        session,
        project=_project(),
        as_of_date=TODAY,
        trigger_scoring=False,
    )
    assert result.created == 1
    created = next(item for item in session.added if isinstance(item, Bottleneck))
    assert created.status == AlertStatus.OPEN
    assert created.severity == RiskTier.HIGH
    assert created.source_key == stable_bottleneck_source_key(ORG_ID, PROJECT_ID, TEAM_A)
    assert sum(isinstance(item, Bottleneck) for item in session.added) == 1
    audit = next(item for item in session.added if isinstance(item, AuditLog))
    assert audit.event_type == "delivery_bottleneck_detected"
    transitions = notify.await_args.kwargs["transitions"]
    assert transitions == [("detected", created)]


@pytest.mark.asyncio
async def test_continuing_detection_updates_same_row_and_preserves_acknowledgement(
    monkeypatch,
) -> None:
    existing = _bottleneck(AlertStatus.ACKNOWLEDGED)
    existing.acknowledged_at = datetime.now(UTC)
    existing.acknowledged_by = ACTOR_ID
    session = _Session(results=[[], [_team(TEAM_A)], [], [existing]])
    analysis = BottleneckAnalysisResult(signals=(_signal(decline="65.00"),))
    monkeypatch.setattr(
        bottleneck_service,
        "load_delivery_scoring_thresholds",
        AsyncMock(return_value=DEFAULT_DELIVERY_SCORING_THRESHOLDS),
    )
    monkeypatch.setattr(
        bottleneck_service,
        "analyze_team_bottlenecks",
        lambda *_args, **_kwargs: analysis,
    )
    monkeypatch.setattr(
        bottleneck_service,
        "_send_transition_notifications",
        AsyncMock(return_value=0),
    )
    result = await detect_project_bottlenecks(
        session,
        project=_project(),
        as_of_date=TODAY,
        trigger_scoring=False,
    )
    assert result.updated == 1
    assert result.created == 0
    assert existing.status == AlertStatus.ACKNOWLEDGED
    assert existing.acknowledged_by == ACTOR_ID
    assert not any(isinstance(item, Bottleneck) for item in session.added)


@pytest.mark.asyncio
async def test_identical_continuing_detection_has_no_duplicate_audit_or_notification(
    monkeypatch,
) -> None:
    existing = _bottleneck()
    signal = _signal()
    existing.last_evidence_hash = bottleneck_service._evidence_hash(
        bottleneck_service._signal_evidence(signal)
    )
    existing.evidence_json = bottleneck_service._signal_evidence(signal)
    session = _Session(results=[[], [_team(TEAM_A)], [], [existing]])
    monkeypatch.setattr(
        bottleneck_service,
        "load_delivery_scoring_thresholds",
        AsyncMock(return_value=DEFAULT_DELIVERY_SCORING_THRESHOLDS),
    )
    monkeypatch.setattr(
        bottleneck_service,
        "analyze_team_bottlenecks",
        lambda *_args, **_kwargs: BottleneckAnalysisResult(signals=(signal,)),
    )
    notify = AsyncMock(return_value=0)
    monkeypatch.setattr(bottleneck_service, "_send_transition_notifications", notify)
    result = await detect_project_bottlenecks(
        session,
        project=_project(),
        as_of_date=TODAY,
        trigger_scoring=False,
    )
    assert result.updated == 0
    assert not any(isinstance(item, AuditLog) for item in session.added)
    assert notify.await_args.kwargs["transitions"] == []


@pytest.mark.asyncio
async def test_valid_recovery_auto_resolves_active_row(monkeypatch) -> None:
    existing = _bottleneck(AlertStatus.ACKNOWLEDGED)
    session = _Session(results=[[], [_team(TEAM_A)], [], [existing]])
    analysis = BottleneckAnalysisResult(recovered_team_ids=(TEAM_A,))
    monkeypatch.setattr(
        bottleneck_service,
        "load_delivery_scoring_thresholds",
        AsyncMock(return_value=DEFAULT_DELIVERY_SCORING_THRESHOLDS),
    )
    monkeypatch.setattr(
        bottleneck_service,
        "analyze_team_bottlenecks",
        lambda *_args, **_kwargs: analysis,
    )
    monkeypatch.setattr(
        bottleneck_service,
        "_send_transition_notifications",
        AsyncMock(return_value=0),
    )
    result = await detect_project_bottlenecks(
        session,
        project=_project(),
        as_of_date=TODAY,
        trigger_scoring=False,
    )
    assert result.resolved == 1
    assert existing.status == AlertStatus.RESOLVED
    assert existing.resolved_by is None
    assert "Automatically resolved" in existing.resolution_reason
    audit = next(item for item in session.added if isinstance(item, AuditLog))
    assert audit.event_type == "delivery_bottleneck_auto_resolved"


@pytest.mark.asyncio
async def test_later_genuine_recurrence_reopens_same_row(monkeypatch) -> None:
    existing = _bottleneck(AlertStatus.RESOLVED)
    existing.resolved_at = datetime(2026, 7, 19, tzinfo=UTC)
    existing.last_evidence_hash = "prior-window"
    session = _Session(results=[[], [_team(TEAM_A)], [], [existing]])
    analysis = BottleneckAnalysisResult(signals=(_signal(),))
    monkeypatch.setattr(
        bottleneck_service,
        "load_delivery_scoring_thresholds",
        AsyncMock(return_value=DEFAULT_DELIVERY_SCORING_THRESHOLDS),
    )
    monkeypatch.setattr(
        bottleneck_service,
        "analyze_team_bottlenecks",
        lambda *_args, **_kwargs: analysis,
    )
    notify = AsyncMock(return_value=1)
    monkeypatch.setattr(bottleneck_service, "_send_transition_notifications", notify)
    result = await detect_project_bottlenecks(
        session,
        project=_project(),
        as_of_date=TODAY,
        trigger_scoring=False,
    )
    assert result.reopened == 1
    assert result.created == 0
    assert existing.status == AlertStatus.OPEN
    assert existing.occurrence_count == 2
    assert existing.resolved_at is None
    assert notify.await_args.kwargs["transitions"] == [("reopened", existing)]


@pytest.mark.asyncio
async def test_detection_rescores_once_with_already_loaded_thresholds(monkeypatch) -> None:
    session = _Session(results=[[], [_team(TEAM_A)], [], []])
    thresholds = DEFAULT_DELIVERY_SCORING_THRESHOLDS
    monkeypatch.setattr(
        bottleneck_service,
        "load_delivery_scoring_thresholds",
        AsyncMock(return_value=thresholds),
    )
    monkeypatch.setattr(
        bottleneck_service,
        "analyze_team_bottlenecks",
        lambda *_args, **_kwargs: BottleneckAnalysisResult(signals=(_signal(),)),
    )
    monkeypatch.setattr(
        bottleneck_service,
        "_send_transition_notifications",
        AsyncMock(return_value=0),
    )
    scoring = SimpleNamespace(scoring_status="ok", scoring_error=None)
    score = AsyncMock(return_value=scoring)
    monkeypatch.setattr(bottleneck_service, "run_delivery_scoring", score)
    result = await detect_project_bottlenecks(
        session,
        project=_project(),
        as_of_date=TODAY,
        trigger_scoring=True,
    )
    assert result.scoring is scoring
    score.assert_awaited_once()
    assert score.await_args.kwargs["thresholds"] is thresholds


@pytest.mark.asyncio
async def test_acknowledgement_preserves_active_scoring_status() -> None:
    bottleneck = _bottleneck()
    session = _Session()
    changed = await acknowledge_bottleneck(
        session,
        bottleneck=bottleneck,
        actor=_actor(),
        note="Investigating",
    )
    assert changed is True
    assert bottleneck.status == AlertStatus.ACKNOWLEDGED
    assert bottleneck.resolved_at is None
    assert (
        await acknowledge_bottleneck(
            session,
            bottleneck=bottleneck,
            actor=_actor(),
            note="Repeated",
        )
        is False
    )


@pytest.mark.asyncio
async def test_manual_resolution_records_actor_and_rescores_once(monkeypatch) -> None:
    bottleneck = _bottleneck(AlertStatus.ACKNOWLEDGED)
    session = _Session()
    scoring = SimpleNamespace(scoring_status="ok", scoring_error=None)
    score = AsyncMock(return_value=scoring)
    notify = AsyncMock(return_value=0)
    monkeypatch.setattr(bottleneck_service, "run_delivery_scoring", score)
    monkeypatch.setattr(bottleneck_service, "_send_transition_notifications", notify)
    changed, returned = await resolve_bottleneck(
        session,
        project=_project(),
        bottleneck=bottleneck,
        actor=_actor(),
        reason="Throughput recovered after workflow repair.",
        as_of_date=TODAY,
    )
    assert changed is True
    assert returned is scoring
    assert bottleneck.status == AlertStatus.RESOLVED
    assert bottleneck.resolved_by == ACTOR_ID
    score.assert_awaited_once()


def test_manual_resolution_suppresses_unchanged_evidence_until_new_date() -> None:
    bottleneck = _bottleneck(AlertStatus.RESOLVED)
    bottleneck.resolved_at = datetime(2026, 7, 20, tzinfo=UTC)
    evidence = bottleneck_service._signal_evidence(_signal())
    evidence_hash = bottleneck_service._evidence_hash(evidence)
    bottleneck.last_evidence_hash = evidence_hash
    assert bottleneck_service._can_reopen(bottleneck, _signal(), evidence_hash) is False
    changed_signal = _signal(latest=TODAY + timedelta(days=1), decline="65.00")
    changed_hash = bottleneck_service._evidence_hash(
        bottleneck_service._signal_evidence(changed_signal)
    )
    assert (
        bottleneck_service._can_reopen(
            bottleneck,
            changed_signal,
            changed_hash,
        )
        is True
    )


@pytest.mark.parametrize("team_count", [1, 25, 100])
@pytest.mark.asyncio
async def test_detection_read_queries_are_constant(monkeypatch, team_count: int) -> None:
    teams = [_team(uuid4(), f"Team {index}") for index in range(team_count)]
    session = _Session(results=[[], teams, [], []])
    loader = AsyncMock(return_value=DEFAULT_DELIVERY_SCORING_THRESHOLDS)
    notify = AsyncMock(return_value=0)
    monkeypatch.setattr(bottleneck_service, "load_delivery_scoring_thresholds", loader)
    monkeypatch.setattr(bottleneck_service, "_send_transition_notifications", notify)
    result = await detect_project_bottlenecks(
        session,
        project=_project(),
        as_of_date=TODAY,
        trigger_scoring=False,
    )
    assert result.analysis.evaluated_teams == team_count
    assert session.execute_count == 4
    loader.assert_awaited_once()


@pytest.mark.asyncio
async def test_notification_failure_is_isolated() -> None:
    class BrokenSession(_Session):
        @asynccontextmanager
        async def begin_nested(self):
            raise RuntimeError("notification storage unavailable")
            yield

    sent = await bottleneck_service._send_transition_notifications(
        BrokenSession(),
        org_id=ORG_ID,
        project_name="Atlas",
        transitions=[("detected", _bottleneck())],
    )
    assert sent == 0


@pytest.mark.asyncio
async def test_clients_cannot_access_raw_phase2_endpoints(api_client, client_a) -> None:
    override_user(client_a)
    paths = [
        f"/api/v1/projects/{PROJECT_ID}/team-throughput",
        f"/api/v1/projects/{PROJECT_ID}/bottlenecks",
    ]
    for path in paths:
        response = await api_client.get(path)
        assert response.status_code == 403
    response = await api_client.post(
        f"/api/v1/projects/{PROJECT_ID}/bottlenecks/detect",
    )
    assert response.status_code == 403


@pytest.mark.asyncio
async def test_internal_role_can_reach_bounded_team_list(
    api_client,
    delivery_manager,
    monkeypatch,
) -> None:
    override_user(delivery_manager)
    project = _project()
    project.org_id = delivery_manager.org_id
    monkeypatch.setattr(
        "app.api.routes.delivery.get_visible_project",
        AsyncMock(return_value=project),
    )
    response = await api_client.get(f"/api/v1/projects/{PROJECT_ID}/team-throughput")
    assert response.status_code == 200
    assert response.json()["pagination"]["limit"] == 100


def test_phase2_migration_contains_constraints_rls_and_no_project_rewrite() -> None:
    sql = Path(
        "../supabase/migrations/20260720100000_delivery_team_throughput_bottlenecks.sql"
    ).read_text(encoding="utf-8")
    assert "CREATE TABLE team_throughput_snapshots" in sql
    assert "UNIQUE (org_id, project_id, team_id, snapshot_date)" in sql
    assert "team_throughput_snapshots_team_project_org_fkey" in sql
    assert "ENABLE ROW LEVEL SECURITY" in sql
    assert "team_throughput_snapshots_super_admin_all" in sql
    assert "bottlenecks_detector_source_active_uidx" in sql
    assert "ALTER TABLE throughput_snapshots" not in sql


def test_resolution_reason_is_required_and_bounded() -> None:
    with pytest.raises(ValidationError):
        BottleneckResolveRequest(reason="no")
    with pytest.raises(ValidationError):
        BottleneckResolveRequest(reason="x" * 1001)
