from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Annotator, QualityErrorEntry, QualitySnapshot, RiskTier
from app.services.quality_thresholds import (
    ThresholdConfig,
    classify_value_severity,
    classify_wow_change,
    load_thresholds,
    max_tier,
)

MIN_EVALUATED_ITEMS = 30
GUIDELINE_AMBIGUITY_CATEGORIES = {"guideline_ambiguity", "ERR-04", "Guideline ambiguity"}
ONBOARDING_WINDOW_DAYS = 14


@dataclass(frozen=True)
class DriftResult:
    has_drift: bool
    severity: RiskTier
    data_gap: bool = False
    data_gap_message: str | None = None
    contributing_causes: dict[str, float] | None = None
    detail: str | None = None
    trend_alert: bool = False


def prior_iso_week(iso_year: int, iso_week: int) -> tuple[int, int]:
    if iso_week > 1:
        return iso_year, iso_week - 1
    return iso_year - 1, 52


async def fetch_prior_snapshot(
    session: AsyncSession,
    snapshot: QualitySnapshot,
) -> QualitySnapshot | None:
    py, pw = prior_iso_week(snapshot.iso_year, snapshot.iso_week)
    return (
        await session.execute(
            select(QualitySnapshot).where(
                QualitySnapshot.project_id == snapshot.project_id,
                QualitySnapshot.team_id == snapshot.team_id,
                QualitySnapshot.iso_year == py,
                QualitySnapshot.iso_week == pw,
            )
        )
    ).scalar_one_or_none()


async def fetch_recent_snapshots(
    session: AsyncSession,
    snapshot: QualitySnapshot,
    limit: int = 6,
) -> list[QualitySnapshot]:
    rows = (
        await session.execute(
            select(QualitySnapshot)
            .where(
                QualitySnapshot.project_id == snapshot.project_id,
                QualitySnapshot.team_id == snapshot.team_id,
            )
            .order_by(QualitySnapshot.iso_year.desc(), QualitySnapshot.iso_week.desc())
            .limit(limit)
        )
    ).scalars()
    return list(rows)


def detect_three_week_declining_trend(snapshots: list[QualitySnapshot]) -> bool:
    accuracies = [
        float(s.gold_set_accuracy_pct)
        for s in reversed(snapshots[:3])
        if s.gold_set_accuracy_pct is not None
    ]
    if len(accuracies) < 3:
        return False
    return accuracies[0] > accuracies[1] > accuracies[2]


async def evaluate_drift(
    session: AsyncSession,
    snapshot: QualitySnapshot,
    *,
    thresholds: dict[str, ThresholdConfig] | None = None,
) -> DriftResult:
    if snapshot.evaluated_item_count is not None and snapshot.evaluated_item_count < MIN_EVALUATED_ITEMS:
        return DriftResult(
            has_drift=False,
            severity=RiskTier.LOW,
            data_gap=True,
            data_gap_message=(
                f"Insufficient sample size for conclusive analysis. "
                f"{snapshot.evaluated_item_count} items evaluated; minimum is {MIN_EVALUATED_ITEMS}."
            ),
        )

    configs = thresholds or await load_thresholds(session)
    prior = await fetch_prior_snapshot(session, snapshot)
    recent = await fetch_recent_snapshots(session, snapshot)

    tiers: list[RiskTier] = []
    causes: dict[str, float] = {}

    acc_cfg = configs["gold_set_accuracy"]
    acc_tier = classify_value_severity(acc_cfg, snapshot.gold_set_accuracy_pct)
    tiers.append(acc_tier)
    if prior and snapshot.gold_set_accuracy_pct is not None and prior.gold_set_accuracy_pct is not None:
        wow_tier = classify_wow_change(acc_cfg, snapshot.gold_set_accuracy_pct, prior.gold_set_accuracy_pct)
        tiers.append(wow_tier)
        causes["gold_set_accuracy_wow_delta"] = float(snapshot.gold_set_accuracy_pct - prior.gold_set_accuracy_pct)

    iaa_cfg = configs["iaa_krippendorff_alpha"]
    iaa_tier = classify_value_severity(iaa_cfg, snapshot.iaa_krippendorff_alpha)
    tiers.append(iaa_tier)
    if prior and snapshot.iaa_krippendorff_alpha is not None and prior.iaa_krippendorff_alpha is not None:
        tiers.append(classify_wow_change(iaa_cfg, snapshot.iaa_krippendorff_alpha, prior.iaa_krippendorff_alpha))

    rework_cfg = configs["rework_rate"]
    rework_tier = classify_value_severity(rework_cfg, snapshot.rework_rate_pct)
    tiers.append(rework_tier)
    if prior and snapshot.rework_rate_pct is not None and prior.rework_rate_pct is not None:
        tiers.append(classify_wow_change(rework_cfg, snapshot.rework_rate_pct, prior.rework_rate_pct))

    trend_alert = detect_three_week_declining_trend(recent)
    if trend_alert:
        tiers.append(RiskTier.MEDIUM)

    severity = max_tier(*tiers) if tiers else RiskTier.LOW
    has_drift = severity in {RiskTier.MEDIUM, RiskTier.HIGH, RiskTier.CRITICAL}

    detail_parts: list[str] = []
    if snapshot.gold_set_accuracy_pct is not None:
        detail_parts.append(f"Gold-set accuracy {snapshot.gold_set_accuracy_pct}%")
    if prior and prior.gold_set_accuracy_pct is not None and snapshot.gold_set_accuracy_pct is not None:
        detail_parts.append(f"W{snapshot.iso_week - 1 if snapshot.iso_week > 1 else 52}→W{snapshot.iso_week}")
    if trend_alert:
        detail_parts.append("3-week declining accuracy trend")

    return DriftResult(
        has_drift=has_drift,
        severity=severity,
        contributing_causes=causes or None,
        detail="; ".join(detail_parts) if detail_parts else None,
        trend_alert=trend_alert,
    )


async def fetch_error_entries(session: AsyncSession, snapshot_id) -> list[QualityErrorEntry]:
    return list(
        (
            await session.execute(
                select(QualityErrorEntry).where(QualityErrorEntry.quality_snapshot_id == snapshot_id)
            )
        ).scalars()
    )


async def count_recent_annotators(session: AsyncSession, team_id, *, days: int = ONBOARDING_WINDOW_DAYS) -> int:
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    rows = (
        await session.execute(
            select(Annotator).where(
                Annotator.team_id == team_id,
                Annotator.deleted_at.is_(None),
                Annotator.created_at >= cutoff,
            )
        )
    ).scalars()
    return len(list(rows))


def has_quality_drift(
    *,
    gold_set_accuracy_pct: Decimal | None,
    iaa_krippendorff_alpha: Decimal | None,
    rework_rate_pct: Decimal | None,
) -> bool:
    """Legacy helper retained for compatibility."""
    return (
        (gold_set_accuracy_pct is not None and gold_set_accuracy_pct < Decimal("95.00"))
        or (iaa_krippendorff_alpha is not None and iaa_krippendorff_alpha < Decimal("0.850"))
        or (rework_rate_pct is not None and rework_rate_pct > Decimal("5.00"))
    )
