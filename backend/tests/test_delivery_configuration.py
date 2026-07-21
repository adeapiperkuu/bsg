"""Phase 1 configurable Delivery scoring thresholds."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import ANY, AsyncMock, MagicMock
from uuid import UUID, uuid4

import pytest
from pydantic import ValidationError

from app.agents.delivery.analytics.confidence import (
    ON_TRACK_THRESHOLD,
    classify_confidence_status,
)
from app.agents.delivery.analytics.risk import classify_risk_tier
from app.agents.delivery.analytics.status import calculate_status
from app.agents.delivery.configuration import (
    CONFIGURATION_CACHE_TTL,
    DEFAULT_DELIVERY_SCORING_THRESHOLDS,
    DeliveryBottleneckThresholds,
    DeliveryConfidenceThresholds,
    DeliveryMetricKey,
    DeliveryRiskThresholds,
    DeliveryScoringThresholds,
    DeliveryTrafficLightRules,
    _CacheEntry,
    _threshold_cache,
    invalidate_delivery_scoring_thresholds_cache,
    load_delivery_scoring_thresholds,
    load_delivery_scoring_thresholds_for_organisations,
    validate_delivery_metric_threshold_config,
)
from app.agents.delivery.events.domain_events import DeliveryScoredEvent
from app.agents.delivery.services import dashboard_service, scoring_service
from app.agents.delivery.services.dashboard_service import get_portfolio_data
from app.agents.delivery.services.scoring_service import ScoringContext, compute_delivery_scores
from app.api.routes import metrics as metrics_routes
from app.api.routes.metrics import list_metrics
from app.core.security import CurrentUser
from app.db.models import AppRole, MetricConfiguration, Project
from app.schemas.domain import MetricConfigurationUpdate
from tests.conftest import override_user


@pytest.fixture(autouse=True)
def _clear_threshold_cache() -> None:
    invalidate_delivery_scoring_thresholds_cache()


def _row(
    metric_key: DeliveryMetricKey,
    payload: object,
    *,
    org_id: UUID | None = None,
) -> SimpleNamespace:
    return SimpleNamespace(
        org_id=org_id,
        metric_key=metric_key.value,
        threshold_config=payload,
    )


def _session(rows: list[SimpleNamespace]) -> AsyncMock:
    session = AsyncMock()
    result = MagicMock()
    result.scalars.return_value.all.return_value = rows
    session.execute.return_value = result
    return session


def _raw_data(*, rolling_units: int = 49, bottlenecks: int = 0) -> dict:
    return {
        "as_of_date": date(2026, 7, 17),
        "project": {"daily_target_units": 10},
        "milestones": [],
        "throughput_snapshots": [
            {"rolling_7day_units": rolling_units, "units_completed": rolling_units}
        ],
        "risks": [],
        "bottlenecks": [{} for _ in range(bottlenecks)],
        "quality_snapshot": None,
    }


def _project(org_id: UUID, index: int = 0) -> Project:
    return Project(
        id=uuid4(),
        org_id=org_id,
        name=f"Project {index}",
        description=None,
        vertical="test",
        status="active",
        start_date=date(2026, 1, 1),
        target_end_date=date(2026, 12, 31),
        actual_end_date=None,
        daily_target_units=10,
        updated_at=datetime(2026, 7, 17, tzinfo=UTC),
    )


def test_default_model_matches_previous_constants_and_is_immutable() -> None:
    defaults = DEFAULT_DELIVERY_SCORING_THRESHOLDS

    assert defaults.confidence.on_track == ON_TRACK_THRESHOLD == Decimal("80.00")
    assert defaults.confidence.critical == Decimal("50.00")
    assert defaults.risk.medium == Decimal("30.00")
    assert defaults.risk.high == Decimal("60.00")
    assert defaults.risk.critical == Decimal("85.00")
    assert defaults.risk.trend_tolerance == Decimal("5.00")
    assert defaults.risk.throughput_decline_tolerance == Decimal("0.00")
    assert defaults.risk.milestone_warning_window_days == 14
    with pytest.raises(ValidationError):
        defaults.confidence.on_track = Decimal("70")


@pytest.mark.parametrize(
    ("model", "payload"),
    [
        (DeliveryConfidenceThresholds, {"critical": -1}),
        (DeliveryConfidenceThresholds, {"critical": 90, "on_track": 80}),
        (DeliveryRiskThresholds, {"medium": 70, "high": 60}),
        (DeliveryRiskThresholds, {"critical": 101}),
        (DeliveryRiskThresholds, {"trend_tolerance": "NaN"}),
        (DeliveryRiskThresholds, {"trend_tolerance": float("nan")}),
        (DeliveryRiskThresholds, {"critical": float("inf")}),
        (DeliveryRiskThresholds, {"medium": "30"}),
        (DeliveryRiskThresholds, {"milestone_warning_window_days": "14"}),
        (DeliveryBottleneckThresholds, {"observation_days": 0}),
        (DeliveryBottleneckThresholds, {"decline_threshold_pct": 0}),
        (DeliveryBottleneckThresholds, {"recovery_days": 366}),
        (DeliveryTrafficLightRules, {"red_on_critical_risk": "true"}),
    ],
)
def test_typed_sections_reject_invalid_ranges_and_order(model: type, payload: dict) -> None:
    with pytest.raises(ValidationError):
        model.model_validate(payload)


def test_write_validation_rejects_unknown_fields_and_allows_unrelated_metrics() -> None:
    with pytest.raises(ValueError):
        validate_delivery_metric_threshold_config(
            DeliveryMetricKey.CONFIDENCE.value,
            {"on_track": 80, "unknown": 1},
        )
    validate_delivery_metric_threshold_config("quality_accuracy", None)


def test_metric_configuration_supports_global_and_org_scoped_active_uniqueness() -> None:
    table = MetricConfiguration.__table__
    index_names = {index.name for index in table.indexes if index.unique}

    assert "org_id" in table.c
    assert "metric_configurations_global_key_active_uidx" in index_names
    assert "metric_configurations_org_key_active_uidx" in index_names


@pytest.mark.asyncio
async def test_no_rows_returns_defaults_with_one_query() -> None:
    org_id = uuid4()
    session = _session([])

    thresholds = await load_delivery_scoring_thresholds(session, org_id)

    assert thresholds == DEFAULT_DELIVERY_SCORING_THRESHOLDS
    session.execute.assert_awaited_once()


@pytest.mark.asyncio
async def test_org_rows_override_global_rows_and_partial_fields_merge() -> None:
    org_id = uuid4()
    session = _session(
        [
            _row(DeliveryMetricKey.CONFIDENCE, {"on_track": 75, "critical": 45}),
            _row(DeliveryMetricKey.CONFIDENCE, {"on_track": 70}, org_id=org_id),
            _row(
                DeliveryMetricKey.RISK,
                {
                    "medium": 25,
                    "high": 55,
                    "critical": 80,
                    "trend_tolerance": 3,
                    "throughput_decline_tolerance": 2,
                    "milestone_warning_window_days": 21,
                },
                org_id=org_id,
            ),
        ]
    )

    thresholds = await load_delivery_scoring_thresholds(session, org_id)

    assert thresholds.confidence.on_track == Decimal("70")
    assert thresholds.confidence.critical == Decimal("50.00")
    assert thresholds.risk.critical == Decimal("80")
    assert thresholds.risk.throughput_decline_tolerance == Decimal("2")
    assert thresholds.risk.milestone_warning_window_days == 21


@pytest.mark.asyncio
async def test_invalid_section_falls_back_without_discarding_valid_section(
    caplog: pytest.LogCaptureFixture,
) -> None:
    org_id = uuid4()
    session = _session(
        [
            _row(
                DeliveryMetricKey.CONFIDENCE,
                {"on_track": 40, "critical": 80},
                org_id=org_id,
            ),
            _row(
                DeliveryMetricKey.RISK,
                {"medium": 20, "high": 50, "critical": 75},
                org_id=org_id,
            ),
            _row(DeliveryMetricKey.TRAFFIC_LIGHT, ["malformed"], org_id=org_id),
        ]
    )

    with caplog.at_level("WARNING"):
        thresholds = await load_delivery_scoring_thresholds(session, org_id)

    assert thresholds.confidence == DEFAULT_DELIVERY_SCORING_THRESHOLDS.confidence
    assert thresholds.risk.medium == Decimal("20")
    assert thresholds.traffic_light == DEFAULT_DELIVERY_SCORING_THRESHOLDS.traffic_light
    assert "event=delivery_scoring_thresholds_invalid" in caplog.text
    assert str(org_id) in caplog.text
    assert "malformed" not in caplog.text


@pytest.mark.asyncio
async def test_unknown_field_falls_back_to_complete_section() -> None:
    org_id = uuid4()
    session = _session(
        [_row(DeliveryMetricKey.CONFIDENCE, {"on_track": 65, "surprise": 1}, org_id=org_id)]
    )

    thresholds = await load_delivery_scoring_thresholds(session, org_id)

    assert thresholds.confidence == DEFAULT_DELIVERY_SCORING_THRESHOLDS.confidence


@pytest.mark.asyncio
async def test_database_failure_falls_back_and_does_not_break_scoring() -> None:
    org_id = uuid4()
    session = AsyncMock()
    session.execute.side_effect = RuntimeError("configuration unavailable")

    thresholds = await load_delivery_scoring_thresholds(session, org_id)
    scores = compute_delivery_scores(
        ScoringContext.from_raw_data(_raw_data(), thresholds=thresholds)
    )

    assert thresholds == DEFAULT_DELIVERY_SCORING_THRESHOLDS
    assert scores.traffic_light == "yellow"


@pytest.mark.asyncio
async def test_cache_hit_is_zero_queries_and_invalidation_reloads() -> None:
    org_id = uuid4()
    first_session = _session([])
    second_session = _session([])

    first = await load_delivery_scoring_thresholds(first_session, org_id)
    second = await load_delivery_scoring_thresholds(second_session, org_id)
    assert first is second
    second_session.execute.assert_not_awaited()

    assert invalidate_delivery_scoring_thresholds_cache(org_id) == 1
    await load_delivery_scoring_thresholds(second_session, org_id)
    second_session.execute.assert_awaited_once()


@pytest.mark.asyncio
async def test_cache_isolated_by_organisation_and_ttl_expiry_reloads() -> None:
    org_a = uuid4()
    org_b = uuid4()
    session = _session([_row(DeliveryMetricKey.CONFIDENCE, {"on_track": 70}, org_id=org_a)])

    thresholds = await load_delivery_scoring_thresholds_for_organisations(
        session,
        {org_a, org_b},
    )
    assert thresholds[org_a].confidence.on_track == Decimal("70")
    assert thresholds[org_b].confidence.on_track == Decimal("80.00")
    assert _threshold_cache[org_a].thresholds is not _threshold_cache[org_b].thresholds

    _threshold_cache[org_a] = _CacheEntry(
        loaded_at=datetime.now(UTC) - CONFIGURATION_CACHE_TTL - timedelta(seconds=1),
        thresholds=thresholds[org_a],
    )
    reload_session = _session([])
    reloaded = await load_delivery_scoring_thresholds(reload_session, org_a)
    assert reloaded == DEFAULT_DELIVERY_SCORING_THRESHOLDS
    reload_session.execute.assert_awaited_once()


@pytest.mark.asyncio
async def test_metric_list_query_scopes_non_admin_to_global_and_own_org() -> None:
    org_id = uuid4()
    user = CurrentUser(
        id=uuid4(),
        org_id=org_id,
        email="dm@example.com",
        role=AppRole.DELIVERY_MANAGER,
        is_active=True,
    )
    session = _session([])

    await list_metrics(session, user)

    statement = session.execute.await_args.args[0]
    compiled = str(statement.compile(compile_kwargs={"literal_binds": True}))
    assert "metric_configurations.org_id IS NULL" in compiled
    assert str(org_id).replace("-", "") in compiled


@pytest.mark.asyncio
async def test_client_cannot_create_cross_org_metric_override(api_client, client_a) -> None:
    override_user(client_a)

    response = await api_client.post(
        "/api/v1/metric-configurations",
        json={
            "org_id": str(uuid4()),
            "metric_key": DeliveryMetricKey.CONFIDENCE.value,
            "display_label": "Attempted override",
            "threshold_config": {"on_track": 1},
        },
    )

    assert response.status_code == 403


@pytest.mark.asyncio
async def test_super_admin_receives_422_for_invalid_delivery_override(
    api_client,
    super_admin,
) -> None:
    override_user(super_admin)

    response = await api_client.post(
        "/api/v1/metric-configurations",
        json={
            "org_id": str(uuid4()),
            "metric_key": DeliveryMetricKey.CONFIDENCE.value,
            "display_label": "Invalid override",
            "threshold_config": {"on_track": 40, "critical": 80},
        },
    )

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "INVALID_DELIVERY_THRESHOLDS"


@pytest.mark.asyncio
async def test_successful_metric_update_invalidates_threshold_and_portfolio_caches(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    org_id = uuid4()
    metric = MetricConfiguration(
        id=uuid4(),
        org_id=org_id,
        metric_key=DeliveryMetricKey.CONFIDENCE.value,
        display_label="Delivery confidence",
        is_client_visible=False,
        display_order=100,
        description=None,
        threshold_config={"on_track": 80, "critical": 50},
    )
    session = AsyncMock()
    result = MagicMock()
    result.scalar_one_or_none.return_value = metric
    session.execute.return_value = result
    threshold_invalidation = MagicMock()
    portfolio_invalidation = MagicMock()
    monkeypatch.setattr(
        metrics_routes,
        "invalidate_delivery_scoring_thresholds_cache",
        threshold_invalidation,
    )
    monkeypatch.setattr(
        metrics_routes,
        "clear_delivery_portfolio_cache",
        portfolio_invalidation,
    )
    actor = CurrentUser(
        id=uuid4(),
        org_id=org_id,
        email="admin@example.com",
        role=AppRole.SUPER_ADMIN,
        is_active=True,
    )

    await metrics_routes.update_metric(
        metric.id,
        MetricConfigurationUpdate(threshold_config={"on_track": 70}),
        session,
        actor,
    )

    session.commit.assert_awaited_once()
    threshold_invalidation.assert_called_once_with(org_id)
    portfolio_invalidation.assert_called_once_with(org_id=org_id)


def test_default_scoring_regression_and_custom_classification() -> None:
    raw_data = _raw_data()
    legacy = compute_delivery_scores(ScoringContext.from_raw_data(raw_data))
    explicit_defaults = compute_delivery_scores(
        ScoringContext.from_raw_data(
            raw_data,
            thresholds=DEFAULT_DELIVERY_SCORING_THRESHOLDS,
        )
    )
    custom = DeliveryScoringThresholds(
        confidence=DeliveryConfidenceThresholds(on_track=60, critical=40)
    )
    customized = compute_delivery_scores(ScoringContext.from_raw_data(raw_data, thresholds=custom))

    assert explicit_defaults == legacy
    assert legacy.confidence == customized.confidence == Decimal("70.00")
    assert legacy.risk == Decimal("12.50")
    assert customized.risk == Decimal("0.00")
    assert legacy.traffic_light == "yellow"
    assert customized.traffic_light == "green"


def test_custom_decline_tolerance_changes_only_decline_classification() -> None:
    raw_data = _raw_data()
    raw_data["throughput_snapshots"] = [
        {"rolling_7day_units": 68, "units_completed": 10},
        {"rolling_7day_units": 70, "units_completed": 10},
    ]
    defaults = ScoringContext.from_raw_data(raw_data)
    custom_thresholds = DeliveryScoringThresholds(
        risk=DeliveryRiskThresholds(throughput_decline_tolerance=5)
    )
    custom = ScoringContext.from_raw_data(raw_data, thresholds=custom_thresholds)

    assert defaults.throughput_decline_pct == custom.throughput_decline_pct == Decimal("2.86")
    assert defaults.is_throughput_declining is True
    assert custom.is_throughput_declining is False
    assert (
        compute_delivery_scores(defaults).confidence == compute_delivery_scores(custom).confidence
    )
    assert compute_delivery_scores(defaults).risk > compute_delivery_scores(custom).risk


def test_configured_boundaries_are_inclusive_and_preserve_red_below_semantics() -> None:
    assert classify_confidence_status(Decimal("79.99")) == "at_risk"
    assert classify_confidence_status(Decimal("80.00")) == "on_track"
    assert classify_confidence_status(Decimal("80.01")) == "on_track"
    assert classify_risk_tier(Decimal("29.99")) == "low"
    assert classify_risk_tier(Decimal("30.00")) == "medium"
    assert classify_risk_tier(Decimal("30.01")) == "medium"
    assert calculate_status(confidence=Decimal("49.99"), risk_score=Decimal("0")) == "red"
    assert calculate_status(confidence=Decimal("50.00"), risk_score=Decimal("0")) == "yellow"
    assert calculate_status(confidence=Decimal("80.00"), risk_score=Decimal("30")) == "yellow"
    assert calculate_status(confidence=Decimal("100"), risk_score=Decimal("85")) == "red"


def test_existing_bottleneck_rows_still_affect_scoring() -> None:
    no_bottleneck = compute_delivery_scores(
        ScoringContext.from_raw_data(_raw_data(rolling_units=70))
    )
    with_bottleneck = compute_delivery_scores(
        ScoringContext.from_raw_data(_raw_data(rolling_units=70, bottlenecks=1))
    )

    assert no_bottleneck.traffic_light == "green"
    assert with_bottleneck.risk > no_bottleneck.risk
    assert with_bottleneck.traffic_light == "yellow"


@pytest.mark.asyncio
async def test_direct_scoring_loads_thresholds_once_and_still_builds_event(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    org_id = uuid4()
    project = _project(org_id)
    loader = AsyncMock(return_value=DEFAULT_DELIVERY_SCORING_THRESHOLDS)
    inputs = SimpleNamespace(
        raw_data=_raw_data(),
        current_milestone=None,
        latest_confidence_by_milestone={},
        open_risk_alerts=[],
    )
    monkeypatch.setattr(scoring_service, "load_delivery_scoring_thresholds", loader)
    monkeypatch.setattr(
        dashboard_service,
        "load_project_scoring_inputs",
        AsyncMock(return_value=inputs),
    )

    computed = await scoring_service._compute_scoring_event(
        AsyncMock(),
        project_id=project.id,
        as_of_date=date(2026, 7, 17),
        project=project,
    )

    loader.assert_awaited_once_with(ANY, org_id)
    assert isinstance(computed.event, DeliveryScoredEvent)


@pytest.mark.asyncio
@pytest.mark.parametrize("project_count", [1, 100])
async def test_portfolio_configuration_query_count_is_constant(
    project_count: int,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    org_id = uuid4()
    projects = [_project(org_id, index) for index in range(project_count)]
    session = _session([])
    input_loader = AsyncMock(
        return_value={
            "milestones": {},
            "throughput_snapshots": {},
            "risks": {},
            "bottlenecks": {},
            "quality_snapshots": {},
        }
    )

    async def _run_inline(function, *args):
        return function(*args)

    monkeypatch.setattr(dashboard_service, "_fetch_delivery_inputs_by_project", input_loader)
    monkeypatch.setattr(dashboard_service, "run_in_threadpool", _run_inline)

    result = await get_portfolio_data(
        session=session,
        current_user=SimpleNamespace(),
        projects=projects,
    )

    assert len(result["projects"]) == project_count
    session.execute.assert_awaited_once()
    input_loader.assert_awaited_once()
