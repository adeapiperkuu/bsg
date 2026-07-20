"""Root-cause calculation, persistence, trends, and analytics."""

from __future__ import annotations

import logging
from collections import defaultdict
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from time import perf_counter
from typing import Any
from uuid import UUID

from sqlalchemy import Select, delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.delivery.analytics.root_cause import (
    CLIENT_VISIBLE_FACTORS,
    FACTOR_LABELS,
    MODEL_VERSION,
    STAFFING_FACTORS,
    RootCauseBreakdown,
    allocate_confidence_loss,
    build_factor_signals,
    quantize_pct,
    root_cause_summary_for_ai,
    trend_direction,
)
from app.agents.delivery.configuration import (
    load_delivery_root_cause_weights,
    load_delivery_scoring_thresholds,
)
from app.agents.delivery.services.dashboard_service import (
    clear_delivery_portfolio_cache,
    load_project_scoring_inputs,
)
from app.agents.delivery.services.operational_signals import (
    DEFAULT_OPERATIONAL_SIGNAL_PROVIDER,
    OperationalSignalProvider,
)
from app.agents.delivery.services.scoring_service import ScoringContext, compute_delivery_scores
from app.core.security import CurrentUser
from app.db.models import (
    AppRole,
    DeliveryRootCauseFactor,
    DeliveryRootCauseSnapshot,
    MilestoneStatus,
    Project,
    RiskTier,
    TeamThroughputSnapshot,
)

logger = logging.getLogger(__name__)

ANALYTICS_CACHE_TTL = timedelta(seconds=60)
ANALYTICS_CACHE_MAX_ENTRIES = 256
ZERO = Decimal("0")

_analytics_cache: dict[str, tuple[datetime, dict[str, Any]]] = {}


def clear_root_cause_analytics_cache(*, org_id: UUID | None = None) -> int:
    """Invalidate cached org analytics payloads."""
    if org_id is None:
        count = len(_analytics_cache)
        _analytics_cache.clear()
        return count
    prefix = f"{org_id}:"
    keys = [key for key in _analytics_cache if key.startswith(prefix)]
    for key in keys:
        _analytics_cache.pop(key, None)
    return len(keys)


async def recalculate_root_causes(
    session: AsyncSession,
    *,
    project_id: UUID,
    org_id: UUID,
    snapshot_date: date | None = None,
    overall_confidence: Decimal | None = None,
    signal_provider: OperationalSignalProvider = DEFAULT_OPERATIONAL_SIGNAL_PROVIDER,
) -> DeliveryRootCauseSnapshot:
    """Compute and upsert today's root-cause snapshot for a project."""
    as_of = snapshot_date or date.today()
    project = await session.get(Project, project_id)
    if project is None or project.deleted_at is not None:
        raise ValueError(f"Project {project_id} not found")

    thresholds = await load_delivery_scoring_thresholds(session, org_id)
    weights_cfg = await load_delivery_root_cause_weights(session, org_id)
    inputs = await load_project_scoring_inputs(session, project, as_of_date=as_of)
    context = ScoringContext.from_raw_data(inputs.raw_data, thresholds=thresholds)
    scores = compute_delivery_scores(context)
    confidence = overall_confidence if overall_confidence is not None else scores.confidence

    bottlenecks = [
        {
            "id": str(b.id),
            "title": b.title,
            "detail": b.detail,
            "status": b.status.value if hasattr(b.status, "value") else str(b.status),
            "severity": b.severity.value if hasattr(b.severity, "value") else str(b.severity),
            "source_key": getattr(b, "source_key", None),
        }
        for b in inputs.bottlenecks
    ]
    quality = inputs.raw_data.get("quality_snapshot") or {}
    rework_rate = context.rework_rate_pct
    headcount_decline = await _headcount_decline_pct(session, project_id=project_id, as_of=as_of)
    shortfall = _throughput_shortfall_pct(inputs.raw_data)
    overdue_count = _overdue_milestone_count(inputs.raw_data.get("milestones") or [], as_of)

    absenteeism = await signal_provider.get_absenteeism_signal(session, project_id=project_id)
    dependency = await signal_provider.get_dependency_delay_signal(session, project_id=project_id)
    scope = await signal_provider.get_scope_volatility_signal(session, project_id=project_id)

    signals = build_factor_signals(
        bottlenecks=bottlenecks,
        rework_rate_pct=rework_rate,
        headcount_decline_pct=headcount_decline,
        throughput_decline_pct=context.throughput_decline_pct,
        throughput_shortfall_pct=shortfall,
        days_until_milestone=context.days_until_milestone,
        overdue_milestone_count=overdue_count,
        has_quality_drift=bool(quality.get("has_drift_alert")),
        warning_window_days=int(thresholds.risk.milestone_warning_window_days),
        absenteeism_signal=absenteeism.value if absenteeism else None,
        dependency_signal=dependency.value if dependency else None,
        scope_signal=scope.value if scope else None,
    )
    breakdown = allocate_confidence_loss(
        overall_confidence=confidence,
        on_track_threshold=thresholds.confidence.on_track,
        weights=weights_cfg.weights,
        signals=signals,
        severity_medium_points=weights_cfg.severity_medium_points,
        severity_high_points=weights_cfg.severity_high_points,
        severity_critical_points=weights_cfg.severity_critical_points,
    )
    snapshot = await _upsert_snapshot(
        session,
        org_id=org_id,
        project_id=project_id,
        snapshot_date=as_of,
        breakdown=breakdown,
    )
    clear_root_cause_analytics_cache(org_id=org_id)
    clear_delivery_portfolio_cache(org_id=org_id)
    return snapshot


async def get_project_root_causes(
    session: AsyncSession,
    *,
    project_id: UUID,
    as_of: date | None = None,
    history_days: int = 30,
    current_user: CurrentUser | None = None,
) -> dict[str, Any]:
    """Return latest snapshot (and optional history) with role-aware shaping."""
    target = as_of or date.today()
    snapshot = await _latest_snapshot(session, project_id=project_id, on_or_before=target)
    history = await _list_snapshots(
        session,
        project_id=project_id,
        date_from=target - timedelta(days=max(0, history_days - 1)),
        date_to=target,
    )
    client_mode = current_user is not None and current_user.role == AppRole.CLIENT
    return {
        "project_id": str(project_id),
        "as_of": target.isoformat(),
        "latest": _snapshot_payload(snapshot, client_mode=client_mode) if snapshot else None,
        "history": [_snapshot_payload(item, client_mode=client_mode) for item in history],
        "root_cause_summary": (
            root_cause_summary_for_ai(_breakdown_from_snapshot(snapshot))
            if snapshot is not None and not client_mode
            else (
                _client_summary(snapshot)
                if snapshot is not None and client_mode
                else None
            )
        ),
    }


async def get_root_cause_trends(
    session: AsyncSession,
    *,
    org_id: UUID | None,
    project_id: UUID | None = None,
    current_user: CurrentUser,
) -> dict[str, Any]:
    """Compare today / last week / last month impact per factor."""
    today = date.today()
    windows = {
        "today": today,
        "last_week": today - timedelta(days=7),
        "last_month": today - timedelta(days=30),
    }
    scoped_org = _resolve_org_scope(current_user, org_id)
    factor_series: dict[str, dict[str, Decimal | None]] = {
        key: {label: None for label in windows} for key in FACTOR_LABELS
    }

    for label, as_of in windows.items():
        rows = await _factor_impacts_as_of(
            session,
            org_id=scoped_org,
            project_id=project_id,
            as_of=as_of,
            current_user=current_user,
        )
        for factor, impact in rows.items():
            if factor in factor_series:
                factor_series[factor][label] = impact

    trends = []
    for factor, series in factor_series.items():
        trends.append(
            {
                "factor": factor,
                "label": FACTOR_LABELS[factor],
                "today": _float_or_none(series["today"]),
                "last_week": _float_or_none(series["last_week"]),
                "last_month": _float_or_none(series["last_month"]),
                "trend_direction": trend_direction(series["today"], series["last_week"]),
            }
        )
    trends.sort(key=lambda item: item["today"] or 0, reverse=True)
    return {
        "as_of": today.isoformat(),
        "project_id": str(project_id) if project_id else None,
        "org_id": str(scoped_org) if scoped_org else None,
        "factors": trends,
    }


async def get_org_root_cause_analytics(
    session: AsyncSession,
    *,
    org_id: UUID | None,
    current_user: CurrentUser,
    lookback_days: int = 30,
) -> dict[str, Any]:
    """Portfolio analytics: frequency, average impact, worst projects."""
    scoped_org = _resolve_org_scope(current_user, org_id)
    cache_key = f"{scoped_org or 'all'}:{lookback_days}:{current_user.role.value}"
    cached = _analytics_cache.get(cache_key)
    now = datetime.now(UTC)
    if cached is not None and now - cached[0] < ANALYTICS_CACHE_TTL:
        return cached[1]

    started = perf_counter()
    since = date.today() - timedelta(days=max(1, lookback_days) - 1)
    stmt = (
        select(DeliveryRootCauseSnapshot, DeliveryRootCauseFactor, Project.name)
        .join(
            DeliveryRootCauseFactor,
            DeliveryRootCauseFactor.snapshot_id == DeliveryRootCauseSnapshot.id,
        )
        .join(Project, Project.id == DeliveryRootCauseSnapshot.project_id)
        .where(
            DeliveryRootCauseSnapshot.snapshot_date >= since,
            Project.deleted_at.is_(None),
        )
    )
    stmt = _apply_org_filter(stmt, scoped_org, current_user)
    rows = (await session.execute(stmt)).all()

    factor_stats: dict[str, dict[str, Any]] = {
        key: {"factor": key, "label": FACTOR_LABELS[key], "occurrences": 0, "impact_sum": ZERO}
        for key in FACTOR_LABELS
    }
    project_loss: dict[UUID, dict[str, Any]] = {}
    for snapshot, factor, project_name in rows:
        if current_user.role == AppRole.CLIENT and factor.factor in STAFFING_FACTORS:
            continue
        if factor.impact_percent > ZERO:
            stats = factor_stats[factor.factor]
            stats["occurrences"] += 1
            stats["impact_sum"] += factor.impact_percent
        entry = project_loss.setdefault(
            snapshot.project_id,
            {
                "project_id": str(snapshot.project_id),
                "project_name": project_name,
                "confidence_loss": ZERO,
                "overall_confidence": snapshot.overall_confidence,
                "snapshot_date": snapshot.snapshot_date.isoformat(),
            },
        )
        # Keep the latest snapshot's loss for ranking.
        if snapshot.snapshot_date.isoformat() >= entry["snapshot_date"]:
            entry["confidence_loss"] = snapshot.confidence_loss
            entry["overall_confidence"] = snapshot.overall_confidence
            entry["snapshot_date"] = snapshot.snapshot_date.isoformat()

    top_causes = []
    for key, stats in factor_stats.items():
        occurrences = int(stats["occurrences"])
        avg_impact = (
            quantize_pct(stats["impact_sum"] / Decimal(occurrences)) if occurrences else ZERO
        )
        top_causes.append(
            {
                "factor": key,
                "label": stats["label"],
                "frequency": occurrences,
                "average_impact_percent": float(avg_impact),
                "confidence_impact": float(avg_impact),
            }
        )
    top_causes.sort(key=lambda item: (item["frequency"], item["average_impact_percent"]), reverse=True)

    worst_projects = sorted(
        [
            {
                **entry,
                "confidence_loss": float(quantize_pct(entry["confidence_loss"])),
                "overall_confidence": float(quantize_pct(entry["overall_confidence"])),
            }
            for entry in project_loss.values()
        ],
        key=lambda item: item["confidence_loss"],
        reverse=True,
    )[:10]

    payload = {
        "lookback_days": lookback_days,
        "org_id": str(scoped_org) if scoped_org else None,
        "top_recurring_causes": top_causes,
        "worst_projects": worst_projects,
        "generated_at": now.isoformat(),
        "duration_ms": round((perf_counter() - started) * 1000, 2),
    }
    if len(_analytics_cache) >= ANALYTICS_CACHE_MAX_ENTRIES:
        oldest = min(_analytics_cache, key=lambda key: _analytics_cache[key][0])
        _analytics_cache.pop(oldest, None)
    _analytics_cache[cache_key] = (now, payload)
    return payload


async def safe_recalculate_after_scoring(
    session: AsyncSession,
    *,
    project_id: UUID,
    org_id: UUID,
    snapshot_date: date,
    overall_confidence: Decimal,
) -> None:
    """Best-effort hook used by scoring handlers; never raises to callers."""
    try:
        await recalculate_root_causes(
            session,
            project_id=project_id,
            org_id=org_id,
            snapshot_date=snapshot_date,
            overall_confidence=overall_confidence,
        )
    except Exception:
        logger.exception(
            "event=delivery_root_cause_recalculate_failed project_id=%s org_id=%s snapshot_date=%s",
            project_id,
            org_id,
            snapshot_date.isoformat(),
        )


def _throughput_shortfall_pct(raw_data: dict[str, Any]) -> Decimal | None:
    project = raw_data.get("project") or {}
    target = project.get("daily_target_units")
    snapshots = raw_data.get("throughput_snapshots") or []
    if target is None or not snapshots:
        return None
    latest = snapshots[0] if isinstance(snapshots[0], dict) else None
    if latest is None:
        return None
    units = latest.get("units_completed")
    if units is None:
        return None
    target_dec = Decimal(str(target))
    if target_dec <= 0:
        return None
    units_dec = Decimal(str(units))
    if units_dec >= target_dec:
        return ZERO
    return quantize_pct((target_dec - units_dec) / target_dec * Decimal("100"))


def _overdue_milestone_count(milestones: list[dict[str, Any]], as_of: date) -> int:
    count = 0
    for milestone in milestones:
        status = str(milestone.get("status", ""))
        planned = milestone.get("planned_date")
        if status == MilestoneStatus.MISSED.value:
            count += 1
            continue
        if planned is None or status == MilestoneStatus.COMPLETED.value:
            continue
        planned_date = planned if isinstance(planned, date) else date.fromisoformat(str(planned))
        if planned_date < as_of:
            count += 1
    return count


async def _headcount_decline_pct(
    session: AsyncSession,
    *,
    project_id: UUID,
    as_of: date,
) -> Decimal | None:
    rows = (
        (
            await session.execute(
                select(TeamThroughputSnapshot)
                .where(
                    TeamThroughputSnapshot.project_id == project_id,
                    TeamThroughputSnapshot.snapshot_date <= as_of,
                    TeamThroughputSnapshot.active_headcount.is_not(None),
                )
                .order_by(TeamThroughputSnapshot.snapshot_date.desc())
                .limit(40)
            )
        )
        .scalars()
        .all()
    )
    if not rows:
        return None

    by_date: dict[date, list[int]] = defaultdict(list)
    for row in rows:
        if row.active_headcount is not None:
            by_date[row.snapshot_date].append(int(row.active_headcount))
    if len(by_date) < 2:
        return None

    ordered_dates = sorted(by_date.keys(), reverse=True)
    current = Decimal(sum(by_date[ordered_dates[0]]))
    baseline_dates = ordered_dates[1:6]
    if not baseline_dates:
        return None
    baseline = Decimal(sum(sum(by_date[d]) for d in baseline_dates)) / Decimal(len(baseline_dates))
    if baseline <= 0:
        return None
    decline = (baseline - current) / baseline * Decimal("100")
    return quantize_pct(decline)


async def _upsert_snapshot(
    session: AsyncSession,
    *,
    org_id: UUID,
    project_id: UUID,
    snapshot_date: date,
    breakdown: RootCauseBreakdown,
) -> DeliveryRootCauseSnapshot:
    existing = (
        await session.execute(
            select(DeliveryRootCauseSnapshot).where(
                DeliveryRootCauseSnapshot.project_id == project_id,
                DeliveryRootCauseSnapshot.snapshot_date == snapshot_date,
            )
        )
    ).scalar_one_or_none()

    now = datetime.now(UTC)
    if existing is None:
        snapshot = DeliveryRootCauseSnapshot(
            org_id=org_id,
            project_id=project_id,
            snapshot_date=snapshot_date,
            overall_confidence=breakdown.overall_confidence,
            confidence_loss=breakdown.confidence_loss,
            model_version=breakdown.model_version,
            generated_at=now,
        )
        session.add(snapshot)
        await session.flush()
    else:
        snapshot = existing
        snapshot.overall_confidence = breakdown.overall_confidence
        snapshot.confidence_loss = breakdown.confidence_loss
        snapshot.model_version = breakdown.model_version
        snapshot.generated_at = now
        await session.execute(
            delete(DeliveryRootCauseFactor).where(
                DeliveryRootCauseFactor.snapshot_id == snapshot.id
            )
        )
        await session.flush()

    for factor in breakdown.factors:
        session.add(
            DeliveryRootCauseFactor(
                snapshot_id=snapshot.id,
                factor=factor.factor,
                impact_percent=factor.impact_percent,
                impact_points=factor.impact_points,
                severity=RiskTier(factor.severity),
                explanation=factor.explanation,
                evidence_json=factor.evidence_json,
            )
        )
    await session.flush()
    await session.refresh(snapshot, attribute_names=["id"])
    # Reload factors for payload helpers.
    await session.refresh(snapshot)
    factors = (
        (
            await session.execute(
                select(DeliveryRootCauseFactor).where(
                    DeliveryRootCauseFactor.snapshot_id == snapshot.id
                )
            )
        )
        .scalars()
        .all()
    )
    snapshot._loaded_factors = list(factors)  # type: ignore[attr-defined]
    return snapshot


async def _latest_snapshot(
    session: AsyncSession,
    *,
    project_id: UUID,
    on_or_before: date,
) -> DeliveryRootCauseSnapshot | None:
    snapshot = (
        await session.execute(
            select(DeliveryRootCauseSnapshot)
            .where(
                DeliveryRootCauseSnapshot.project_id == project_id,
                DeliveryRootCauseSnapshot.snapshot_date <= on_or_before,
            )
            .order_by(DeliveryRootCauseSnapshot.snapshot_date.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    if snapshot is not None:
        await _attach_factors(session, snapshot)
    return snapshot


async def _list_snapshots(
    session: AsyncSession,
    *,
    project_id: UUID,
    date_from: date,
    date_to: date,
) -> list[DeliveryRootCauseSnapshot]:
    rows = (
        (
            await session.execute(
                select(DeliveryRootCauseSnapshot)
                .where(
                    DeliveryRootCauseSnapshot.project_id == project_id,
                    DeliveryRootCauseSnapshot.snapshot_date >= date_from,
                    DeliveryRootCauseSnapshot.snapshot_date <= date_to,
                )
                .order_by(DeliveryRootCauseSnapshot.snapshot_date.desc())
            )
        )
        .scalars()
        .all()
    )
    for snapshot in rows:
        await _attach_factors(session, snapshot)
    return list(rows)


async def _attach_factors(session: AsyncSession, snapshot: DeliveryRootCauseSnapshot) -> None:
    factors = (
        (
            await session.execute(
                select(DeliveryRootCauseFactor)
                .where(DeliveryRootCauseFactor.snapshot_id == snapshot.id)
                .order_by(DeliveryRootCauseFactor.impact_percent.desc())
            )
        )
        .scalars()
        .all()
    )
    snapshot._loaded_factors = list(factors)  # type: ignore[attr-defined]


async def _factor_impacts_as_of(
    session: AsyncSession,
    *,
    org_id: UUID | None,
    project_id: UUID | None,
    as_of: date,
    current_user: CurrentUser,
) -> dict[str, Decimal]:
    """Average impact_percent per factor for the latest snapshot on/before as_of."""
    if project_id is not None:
        snapshot = await _latest_snapshot(session, project_id=project_id, on_or_before=as_of)
        if snapshot is None:
            return {}
        factors = getattr(snapshot, "_loaded_factors", [])
        return {f.factor: f.impact_percent for f in factors}

    # Portfolio: latest snapshot per project on/before as_of, then average impacts.
    stmt = select(DeliveryRootCauseSnapshot).where(
        DeliveryRootCauseSnapshot.snapshot_date <= as_of,
    )
    stmt = _apply_org_filter(stmt, org_id, current_user)
    snapshots = (await session.execute(stmt)).scalars().all()
    latest_by_project: dict[UUID, DeliveryRootCauseSnapshot] = {}
    for snap in snapshots:
        current = latest_by_project.get(snap.project_id)
        if current is None or snap.snapshot_date > current.snapshot_date:
            latest_by_project[snap.project_id] = snap
    if not latest_by_project:
        return {}

    totals: dict[str, Decimal] = defaultdict(lambda: ZERO)
    counts: dict[str, int] = defaultdict(int)
    for snap in latest_by_project.values():
        await _attach_factors(session, snap)
        for factor in getattr(snap, "_loaded_factors", []):
            if current_user.role == AppRole.CLIENT and factor.factor in STAFFING_FACTORS:
                continue
            totals[factor.factor] += factor.impact_percent
            counts[factor.factor] += 1
    return {
        key: quantize_pct(totals[key] / Decimal(counts[key]))
        for key in totals
        if counts[key] > 0
    }


def _apply_org_filter(
    stmt: Select[Any],
    org_id: UUID | None,
    current_user: CurrentUser,
) -> Select[Any]:
    if current_user.role == AppRole.SUPER_ADMIN:
        if org_id is not None:
            return stmt.where(DeliveryRootCauseSnapshot.org_id == org_id)
        return stmt
    # DM / leadership / client: own org only.
    return stmt.where(DeliveryRootCauseSnapshot.org_id == current_user.org_id)


def _resolve_org_scope(current_user: CurrentUser, org_id: UUID | None) -> UUID | None:
    if current_user.role == AppRole.SUPER_ADMIN:
        return org_id
    return current_user.org_id


def _snapshot_payload(
    snapshot: DeliveryRootCauseSnapshot,
    *,
    client_mode: bool,
) -> dict[str, Any]:
    factors = getattr(snapshot, "_loaded_factors", None)
    if factors is None:
        factors = []
    factor_payloads = []
    for factor in factors:
        if client_mode and (
            factor.factor in STAFFING_FACTORS or factor.factor not in CLIENT_VISIBLE_FACTORS
        ):
            continue
        if client_mode and factor.impact_percent <= ZERO:
            continue
        item = {
            "factor": factor.factor,
            "label": FACTOR_LABELS.get(factor.factor, factor.factor),
            "impact_percent": float(factor.impact_percent),
            "impact_points": float(factor.impact_points),
            "severity": factor.severity.value if hasattr(factor.severity, "value") else factor.severity,
            "explanation": factor.explanation,
        }
        if not client_mode:
            item["evidence_json"] = factor.evidence_json
        factor_payloads.append(item)

    if client_mode:
        factor_payloads = sorted(
            factor_payloads, key=lambda item: item["impact_percent"], reverse=True
        )[:3]
        # Collapse remainder into Other for high-level client view.
        # (top 3 only — no Other bucket needed when already capped)

    return {
        "id": str(snapshot.id),
        "project_id": str(snapshot.project_id),
        "org_id": str(snapshot.org_id),
        "snapshot_date": snapshot.snapshot_date.isoformat(),
        "overall_confidence": float(snapshot.overall_confidence),
        "confidence_loss": float(snapshot.confidence_loss),
        "model_version": snapshot.model_version,
        "generated_at": snapshot.generated_at.isoformat() if snapshot.generated_at else None,
        "factors": factor_payloads,
        "main_contributors": _main_contributors(factor_payloads, client_mode=client_mode),
    }


def _main_contributors(
    factors: list[dict[str, Any]],
    *,
    client_mode: bool,
    limit: int = 4,
) -> list[dict[str, Any]]:
    ranked = sorted(
        [f for f in factors if f["impact_percent"] > 0],
        key=lambda item: item["impact_percent"],
        reverse=True,
    )
    top = ranked[:limit]
    remainder = ranked[limit:]
    contributors = [
        {
            "factor": item["factor"],
            "label": item["label"],
            "impact_percent": item["impact_percent"],
        }
        for item in top
    ]
    if remainder and not client_mode:
        other_pct = sum(item["impact_percent"] for item in remainder)
        contributors.append(
            {
                "factor": "other",
                "label": "Other",
                "impact_percent": float(quantize_pct(Decimal(str(other_pct)))),
            }
        )
    return contributors


def _client_summary(snapshot: DeliveryRootCauseSnapshot) -> dict[str, Any]:
    payload = _snapshot_payload(snapshot, client_mode=True)
    return {
        "overall_confidence": payload["overall_confidence"],
        "confidence_loss": payload["confidence_loss"],
        "top_causes": payload["main_contributors"],
    }


def _breakdown_from_snapshot(snapshot: DeliveryRootCauseSnapshot) -> RootCauseBreakdown:
    from app.agents.delivery.analytics.root_cause import AllocatedFactor

    factors = getattr(snapshot, "_loaded_factors", []) or []
    return RootCauseBreakdown(
        overall_confidence=snapshot.overall_confidence,
        confidence_loss=snapshot.confidence_loss,
        factors=tuple(
            AllocatedFactor(
                factor=f.factor,
                impact_percent=f.impact_percent,
                impact_points=f.impact_points,
                severity=f.severity.value if hasattr(f.severity, "value") else str(f.severity),  # type: ignore[arg-type]
                explanation=f.explanation,
                evidence_json=f.evidence_json or {},
            )
            for f in factors
        ),
        model_version=snapshot.model_version or MODEL_VERSION,
    )


def _float_or_none(value: Decimal | None) -> float | None:
    return float(value) if value is not None else None
