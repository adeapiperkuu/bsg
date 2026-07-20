"""Pure deterministic team-throughput bottleneck analytics."""

from __future__ import annotations

from collections import defaultdict
from datetime import date
from decimal import ROUND_HALF_UP, Decimal
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.agents.delivery.configuration import DeliveryBottleneckThresholds

DETECTOR_VERSION = "v1"
PERCENT = Decimal("100")
ZERO = Decimal("0")
SHARE_QUANTUM = Decimal("0.0001")
PERCENT_QUANTUM = Decimal("0.01")


class _FrozenModel(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class TeamThroughputObservation(_FrozenModel):
    team_id: UUID
    snapshot_date: date
    units_completed: Decimal = Field(ge=0)
    active_headcount: Decimal | None = Field(default=None, ge=0)


class TeamDailyShare(_FrozenModel):
    team_id: UUID
    snapshot_date: date
    team_units: Decimal
    project_units: Decimal
    throughput_share: Decimal
    active_headcount: Decimal | None


class BottleneckEvidencePoint(_FrozenModel):
    snapshot_date: date
    current_share: Decimal
    historical_share: Decimal
    decline_pct: Decimal
    headcount_change_pct: Decimal | None


class BottleneckDetectionSignal(_FrozenModel):
    organisation_id: UUID
    project_id: UUID
    team_id: UUID
    source_key: str
    detector_version: str = DETECTOR_VERSION
    severity: Literal["low", "medium", "high", "critical"]
    current_share: Decimal
    historical_share: Decimal
    decline_pct: Decimal
    headcount_change_pct: Decimal | None
    consecutive_days: int
    observation_window_days: int
    latest_observation_date: date
    evidence: tuple[BottleneckEvidencePoint, ...]


class BottleneckAnalysisSkip(_FrozenModel):
    reason: str
    team_id: UUID | None = None
    snapshot_date: date | None = None


class BottleneckAnalysisResult(_FrozenModel):
    signals: tuple[BottleneckDetectionSignal, ...] = ()
    recovered_team_ids: tuple[UUID, ...] = ()
    skipped_reasons: tuple[BottleneckAnalysisSkip, ...] = ()
    evaluated_teams: int = 0
    valid_observation_days: int = 0
    latest_valid_date: date | None = None


def stable_bottleneck_source_key(
    organisation_id: UUID,
    project_id: UUID,
    team_id: UUID,
) -> str:
    """Return the stable identity for one logical detector-generated issue."""
    return (
        f"delivery-team-throughput-bottleneck:{DETECTOR_VERSION}:"
        f"{organisation_id}:{project_id}:{team_id}"
    )


def calculate_daily_team_shares(
    observations: list[TeamThroughputObservation],
    *,
    expected_team_ids: set[UUID],
    minimum_project_units: int,
    as_of_date: date,
) -> tuple[list[TeamDailyShare], list[BottleneckAnalysisSkip]]:
    """Calculate shares only for complete, unique, non-future project dates."""
    skips: list[BottleneckAnalysisSkip] = []
    grouped: dict[date, dict[UUID, TeamThroughputObservation]] = defaultdict(dict)
    duplicate_dates: set[date] = set()

    for observation in sorted(
        observations,
        key=lambda item: (item.snapshot_date, str(item.team_id)),
    ):
        if observation.snapshot_date > as_of_date:
            skips.append(
                BottleneckAnalysisSkip(
                    reason="future_observation",
                    team_id=observation.team_id,
                    snapshot_date=observation.snapshot_date,
                )
            )
            continue
        if observation.team_id not in expected_team_ids:
            skips.append(
                BottleneckAnalysisSkip(
                    reason="unexpected_team",
                    team_id=observation.team_id,
                    snapshot_date=observation.snapshot_date,
                )
            )
            continue
        if observation.team_id in grouped[observation.snapshot_date]:
            duplicate_dates.add(observation.snapshot_date)
            continue
        grouped[observation.snapshot_date][observation.team_id] = observation

    shares: list[TeamDailyShare] = []
    for snapshot_date in sorted(grouped):
        if snapshot_date in duplicate_dates:
            skips.append(
                BottleneckAnalysisSkip(reason="duplicate_team_date", snapshot_date=snapshot_date)
            )
            continue
        daily = grouped[snapshot_date]
        if set(daily) != expected_team_ids:
            skips.append(
                BottleneckAnalysisSkip(
                    reason="incomplete_team_coverage",
                    snapshot_date=snapshot_date,
                )
            )
            continue
        project_units = sum(
            (observation.units_completed for observation in daily.values()),
            start=ZERO,
        )
        if project_units < Decimal(minimum_project_units):
            reason = "zero_project_throughput" if project_units == ZERO else "low_project_volume"
            skips.append(BottleneckAnalysisSkip(reason=reason, snapshot_date=snapshot_date))
            continue
        for team_id in sorted(daily, key=str):
            observation = daily[team_id]
            share = (observation.units_completed / project_units * PERCENT).quantize(
                SHARE_QUANTUM,
                rounding=ROUND_HALF_UP,
            )
            shares.append(
                TeamDailyShare(
                    team_id=team_id,
                    snapshot_date=snapshot_date,
                    team_units=observation.units_completed,
                    project_units=project_units,
                    throughput_share=share,
                    active_headcount=observation.active_headcount,
                )
            )
    return shares, skips


def analyze_team_bottlenecks(
    observations: list[TeamThroughputObservation],
    *,
    organisation_id: UUID,
    project_id: UUID,
    expected_team_ids: set[UUID],
    thresholds: DeliveryBottleneckThresholds,
    as_of_date: date,
) -> BottleneckAnalysisResult:
    """Detect sustained unexplained team-share declines and valid recovery windows."""
    if not expected_team_ids:
        return BottleneckAnalysisResult(
            skipped_reasons=(BottleneckAnalysisSkip(reason="no_active_teams"),)
        )

    shares, skips = calculate_daily_team_shares(
        observations,
        expected_team_ids=expected_team_ids,
        minimum_project_units=thresholds.minimum_project_units,
        as_of_date=as_of_date,
    )
    dates = sorted({item.snapshot_date for item in shares})
    if not dates:
        return BottleneckAnalysisResult(
            skipped_reasons=tuple(skips + [BottleneckAnalysisSkip(reason="no_valid_snapshots")]),
            evaluated_teams=len(expected_team_ids),
        )

    latest_date = dates[-1]
    if (as_of_date - latest_date).days > thresholds.stale_after_days:
        return BottleneckAnalysisResult(
            skipped_reasons=tuple(skips + [BottleneckAnalysisSkip(reason="stale_data")]),
            evaluated_teams=len(expected_team_ids),
            valid_observation_days=len(dates),
            latest_valid_date=latest_date,
        )

    shares_by_team: dict[UUID, list[TeamDailyShare]] = defaultdict(list)
    for item in shares:
        shares_by_team[item.team_id].append(item)

    signals: list[BottleneckDetectionSignal] = []
    recovered: list[UUID] = []
    for team_id in sorted(expected_team_ids, key=str):
        team_shares = shares_by_team.get(team_id, [])
        if len(team_shares) < thresholds.minimum_history_days + thresholds.observation_days:
            skips.append(BottleneckAnalysisSkip(reason="insufficient_history", team_id=team_id))
            continue

        current = team_shares[-thresholds.observation_days :]
        historical_candidates = team_shares[: -thresholds.observation_days]
        historical = historical_candidates[-thresholds.historical_window_days :]
        if len(historical) < thresholds.minimum_history_days:
            skips.append(BottleneckAnalysisSkip(reason="insufficient_history", team_id=team_id))
            continue

        historical_share = _average([item.throughput_share for item in historical])
        if historical_share <= ZERO:
            skips.append(BottleneckAnalysisSkip(reason="zero_historical_share", team_id=team_id))
            continue

        historical_headcount = _optional_average([item.active_headcount for item in historical])
        current_headcount = _optional_average([item.active_headcount for item in current])
        if thresholds.require_headcount and (
            historical_headcount is None
            or historical_headcount <= ZERO
            or current_headcount is None
        ):
            skips.append(BottleneckAnalysisSkip(reason="missing_headcount", team_id=team_id))
            continue

        headcount_change_pct = _headcount_change_pct(
            current=current_headcount,
            historical=historical_headcount,
        )
        evidence = tuple(
            BottleneckEvidencePoint(
                snapshot_date=item.snapshot_date,
                current_share=item.throughput_share,
                historical_share=historical_share,
                decline_pct=_decline_pct(historical_share, item.throughput_share),
                headcount_change_pct=headcount_change_pct,
            )
            for item in current
        )
        sustained = all(point.decline_pct >= thresholds.decline_threshold_pct for point in evidence)
        current_share = _average([item.throughput_share for item in current])
        aggregate_decline = _decline_pct(historical_share, current_share)
        explained = _decline_explained_by_headcount(
            aggregate_decline,
            headcount_change_pct,
            thresholds.headcount_tolerance_pct,
        )

        if sustained and not explained:
            signals.append(
                BottleneckDetectionSignal(
                    organisation_id=organisation_id,
                    project_id=project_id,
                    team_id=team_id,
                    source_key=stable_bottleneck_source_key(
                        organisation_id,
                        project_id,
                        team_id,
                    ),
                    severity=_severity(aggregate_decline, thresholds),
                    current_share=current_share,
                    historical_share=historical_share,
                    decline_pct=aggregate_decline,
                    headcount_change_pct=headcount_change_pct,
                    consecutive_days=len(current),
                    observation_window_days=thresholds.observation_days,
                    latest_observation_date=current[-1].snapshot_date,
                    evidence=evidence,
                )
            )
            continue

        recovery_points = evidence[-thresholds.recovery_days :]
        if len(recovery_points) == thresholds.recovery_days and all(
            point.decline_pct < thresholds.decline_threshold_pct for point in recovery_points
        ):
            recovered.append(team_id)
        elif explained:
            skips.append(
                BottleneckAnalysisSkip(reason="decline_explained_by_headcount", team_id=team_id)
            )
        else:
            skips.append(BottleneckAnalysisSkip(reason="decline_not_sustained", team_id=team_id))

    return BottleneckAnalysisResult(
        signals=tuple(signals),
        recovered_team_ids=tuple(sorted(recovered, key=str)),
        skipped_reasons=tuple(skips),
        evaluated_teams=len(expected_team_ids),
        valid_observation_days=len(dates),
        latest_valid_date=latest_date,
    )


def _average(values: list[Decimal]) -> Decimal:
    return (sum(values, start=ZERO) / Decimal(len(values))).quantize(
        SHARE_QUANTUM,
        rounding=ROUND_HALF_UP,
    )


def _optional_average(values: list[Decimal | None]) -> Decimal | None:
    if not values or any(value is None for value in values):
        return None
    complete = [value for value in values if value is not None]
    return _average(complete)


def _decline_pct(historical: Decimal, current: Decimal) -> Decimal:
    if historical <= ZERO:
        return ZERO
    return max(ZERO, (historical - current) / historical * PERCENT).quantize(
        PERCENT_QUANTUM,
        rounding=ROUND_HALF_UP,
    )


def _headcount_change_pct(
    *,
    current: Decimal | None,
    historical: Decimal | None,
) -> Decimal | None:
    if current is None or historical is None or historical <= ZERO:
        return None
    return ((current - historical) / historical * PERCENT).quantize(
        PERCENT_QUANTUM,
        rounding=ROUND_HALF_UP,
    )


def _decline_explained_by_headcount(
    share_decline_pct: Decimal,
    headcount_change_pct: Decimal | None,
    tolerance_pct: Decimal,
) -> bool:
    if headcount_change_pct is None or headcount_change_pct >= ZERO:
        return False
    headcount_decline_pct = abs(headcount_change_pct)
    return headcount_decline_pct + tolerance_pct >= share_decline_pct


def _severity(
    decline_pct: Decimal,
    thresholds: DeliveryBottleneckThresholds,
) -> Literal["low", "medium", "high", "critical"]:
    if decline_pct >= thresholds.severity_critical_pct:
        return "critical"
    if decline_pct >= thresholds.severity_high_pct:
        return "high"
    if decline_pct >= thresholds.severity_medium_pct:
        return "medium"
    return "low"
