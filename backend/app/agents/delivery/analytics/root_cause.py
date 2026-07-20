"""Pure root-cause analytics for the Delivery Performance Agent."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal
from typing import Any, Literal

from app.agents.delivery.configuration import ROOT_CAUSE_FACTOR_KEYS

SeverityBand = Literal["low", "medium", "high", "critical"]
TrendDirection = Literal["up", "down", "flat", "insufficient_data"]

PERCENT = Decimal("100")
ZERO = Decimal("0")
MODEL_VERSION = "delivery_root_cause_v1"

FACTOR_LABELS: dict[str, str] = {
    "review_turnaround": "Review turnaround",
    "rework": "Rework",
    "capacity": "Capacity shortage",
    "absenteeism": "Absenteeism",
    "queue": "Backlog congestion",
    "blocked_work": "Aging blockers",
    "dependency_delays": "Dependency delays",
    "milestone_slippage": "Milestone slippage",
    "quality_regression": "Quality regression",
    "scope_volatility": "Scope volatility",
}

# Client-safe factors (no internal staffing metrics).
CLIENT_VISIBLE_FACTORS: frozenset[str] = frozenset(
    {
        "review_turnaround",
        "rework",
        "queue",
        "blocked_work",
        "dependency_delays",
        "milestone_slippage",
        "quality_regression",
        "scope_volatility",
    }
)

STAFFING_FACTORS: frozenset[str] = frozenset({"capacity", "absenteeism"})

REVIEW_KEYWORDS = ("review", "queue", "approval", "turnaround")


@dataclass(frozen=True, slots=True)
class FactorSignal:
    """Deterministic severity input for one root-cause factor."""

    factor: str
    severity_signal: Decimal
    data_available: bool
    why: str
    calculation: str
    affected_kpis: tuple[str, ...]
    inputs: dict[str, Any]


@dataclass(frozen=True, slots=True)
class AllocatedFactor:
    """Normalized confidence-loss contribution for one factor."""

    factor: str
    impact_percent: Decimal
    impact_points: Decimal
    severity: SeverityBand
    explanation: str
    evidence_json: dict[str, Any]


@dataclass(frozen=True, slots=True)
class RootCauseBreakdown:
    """Complete deterministic root-cause result for one project/day."""

    overall_confidence: Decimal
    confidence_loss: Decimal
    factors: tuple[AllocatedFactor, ...]
    model_version: str = MODEL_VERSION


def quantize_pct(value: Decimal) -> Decimal:
    return value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def clamp_pct(value: Decimal) -> Decimal:
    return quantize_pct(max(ZERO, min(PERCENT, value)))


def confidence_loss(
    overall_confidence: Decimal,
    *,
    on_track_threshold: Decimal,
) -> Decimal:
    """Points of confidence below the on-track band."""
    if overall_confidence >= on_track_threshold:
        return ZERO
    return quantize_pct(on_track_threshold - overall_confidence)


def classify_impact_severity(
    abs_impact_points: Decimal,
    *,
    medium: Decimal,
    high: Decimal,
    critical: Decimal,
) -> SeverityBand:
    if abs_impact_points >= critical:
        return "critical"
    if abs_impact_points >= high:
        return "high"
    if abs_impact_points >= medium:
        return "medium"
    return "low"


def _unavailable(factor: str, reason: str) -> FactorSignal:
    return FactorSignal(
        factor=factor,
        severity_signal=ZERO,
        data_available=False,
        why=reason,
        calculation="No severity signal; awaiting Phase 15.2 operational source.",
        affected_kpis=(),
        inputs={"data_available": False},
    )


def signal_review_turnaround(
    *,
    bottlenecks: list[dict[str, Any]],
) -> FactorSignal:
    review_items = [
        item
        for item in bottlenecks
        if any(keyword in str(item.get("title", "")).lower() for keyword in REVIEW_KEYWORDS)
        or any(
            keyword in str(item.get("source_key", "")).lower() for keyword in REVIEW_KEYWORDS
        )
    ]
    if not bottlenecks:
        return _unavailable(
            "review_turnaround",
            "No active bottlenecks; review-queue metrics arrive in Phase 15.2.",
        )
    if not review_items:
        return FactorSignal(
            factor="review_turnaround",
            severity_signal=ZERO,
            data_available=True,
            why="Active bottlenecks exist but none match review/queue keywords.",
            calculation="severity = 0 when no review-titled bottlenecks are open.",
            affected_kpis=("confidence", "risk"),
            inputs={"active_bottlenecks": len(bottlenecks), "review_matched": 0},
        )
    severity = min(PERCENT, Decimal(len(review_items)) * Decimal("25"))
    return FactorSignal(
        factor="review_turnaround",
        severity_signal=severity,
        data_available=True,
        why=f"{len(review_items)} active review/queue bottleneck(s) detected.",
        calculation="min(100, review_bottleneck_count × 25)",
        affected_kpis=("confidence", "risk", "throughput"),
        inputs={
            "review_matched": len(review_items),
            "active_bottlenecks": len(bottlenecks),
        },
    )


def signal_rework(*, rework_rate_pct: Decimal | None) -> FactorSignal:
    if rework_rate_pct is None:
        return _unavailable("rework", "No quality rework rate available for this project.")
    severity = clamp_pct(rework_rate_pct * Decimal("2"))
    return FactorSignal(
        factor="rework",
        severity_signal=severity,
        data_available=True,
        why=f"Rework rate is {quantize_pct(rework_rate_pct)}%.",
        calculation="min(100, rework_rate_pct × 2)",
        affected_kpis=("confidence", "quality", "risk"),
        inputs={"rework_rate_pct": float(quantize_pct(rework_rate_pct))},
    )


def signal_capacity(
    *,
    headcount_decline_pct: Decimal | None,
    throughput_decline_pct: Decimal = ZERO,
) -> FactorSignal:
    if headcount_decline_pct is None:
        return _unavailable(
            "capacity",
            "Insufficient team headcount history; capacity snapshots arrive in Phase 15.2.",
        )
    # Capacity pressure rises when headcount drops and throughput also softens.
    combined = max(ZERO, headcount_decline_pct) + max(ZERO, throughput_decline_pct) * Decimal(
        "0.5"
    )
    severity = clamp_pct(combined)
    return FactorSignal(
        factor="capacity",
        severity_signal=severity,
        data_available=True,
        why=(
            f"Headcount declined {quantize_pct(max(ZERO, headcount_decline_pct))}%"
            f" with throughput decline {quantize_pct(max(ZERO, throughput_decline_pct))}%."
        ),
        calculation="min(100, max(0, headcount_decline_pct) + 0.5 × max(0, throughput_decline_pct))",
        affected_kpis=("confidence", "throughput", "capacity"),
        inputs={
            "headcount_decline_pct": float(quantize_pct(headcount_decline_pct)),
            "throughput_decline_pct": float(quantize_pct(throughput_decline_pct)),
        },
    )


def signal_absenteeism() -> FactorSignal:
    return _unavailable(
        "absenteeism",
        "Absenteeism time series is not modeled until Phase 15.2.",
    )


def signal_queue(
    *,
    open_bottleneck_count: int,
    throughput_shortfall_pct: Decimal | None,
) -> FactorSignal:
    if open_bottleneck_count <= 0 and throughput_shortfall_pct is None:
        return _unavailable(
            "queue",
            "No bottleneck or target-shortfall evidence for backlog congestion.",
        )
    bottleneck_part = min(Decimal("60"), Decimal(max(0, open_bottleneck_count)) * Decimal("15"))
    shortfall_part = ZERO
    if throughput_shortfall_pct is not None:
        shortfall_part = min(Decimal("40"), max(ZERO, throughput_shortfall_pct) * Decimal("0.4"))
    severity = clamp_pct(bottleneck_part + shortfall_part)
    return FactorSignal(
        factor="queue",
        severity_signal=severity,
        data_available=True,
        why=(
            f"{open_bottleneck_count} open bottleneck(s)"
            + (
                f" and {quantize_pct(throughput_shortfall_pct)}% target shortfall"
                if throughput_shortfall_pct is not None
                else ""
            )
            + "."
        ),
        calculation="min(100, min(60, bottlenecks×15) + min(40, shortfall×0.4))",
        affected_kpis=("confidence", "throughput", "risk"),
        inputs={
            "open_bottleneck_count": open_bottleneck_count,
            "throughput_shortfall_pct": (
                float(quantize_pct(throughput_shortfall_pct))
                if throughput_shortfall_pct is not None
                else None
            ),
        },
    )


def signal_blocked_work(*, bottlenecks: list[dict[str, Any]]) -> FactorSignal:
    if not bottlenecks:
        return FactorSignal(
            factor="blocked_work",
            severity_signal=ZERO,
            data_available=True,
            why="No open or acknowledged blockers.",
            calculation="severity = 0 when no active bottlenecks.",
            affected_kpis=("confidence", "risk"),
            inputs={"active_bottlenecks": 0},
        )
    severity_rank = {"low": 1, "medium": 2, "high": 3, "critical": 4}
    weighted = ZERO
    for item in bottlenecks:
        rank = Decimal(severity_rank.get(str(item.get("severity", "medium")), 2))
        weighted += rank * Decimal("12.5")
    severity = clamp_pct(weighted)
    return FactorSignal(
        factor="blocked_work",
        severity_signal=severity,
        data_available=True,
        why=f"{len(bottlenecks)} aging blocker(s) remain active.",
        calculation="min(100, sum(severity_rank × 12.5))",
        affected_kpis=("confidence", "risk", "milestones"),
        inputs={"active_bottlenecks": len(bottlenecks)},
    )


def signal_dependency_delays() -> FactorSignal:
    return _unavailable(
        "dependency_delays",
        "Dependency graph signals are not modeled until Phase 15.2.",
    )


def signal_milestone_slippage(
    *,
    days_until_milestone: int | None,
    overdue_milestone_count: int = 0,
    warning_window_days: int = 14,
) -> FactorSignal:
    if days_until_milestone is None and overdue_milestone_count <= 0:
        return FactorSignal(
            factor="milestone_slippage",
            severity_signal=ZERO,
            data_available=True,
            why="No current milestone urgency or overdue milestones.",
            calculation="severity = 0 without milestone pressure.",
            affected_kpis=("confidence", "milestones"),
            inputs={"days_until_milestone": None, "overdue_milestone_count": 0},
        )
    overdue_part = min(Decimal("60"), Decimal(max(0, overdue_milestone_count)) * Decimal("30"))
    urgency_part = ZERO
    if days_until_milestone is not None:
        if days_until_milestone < 0:
            urgency_part = Decimal("40")
        elif warning_window_days > 0 and days_until_milestone <= warning_window_days:
            ratio = Decimal(warning_window_days - days_until_milestone) / Decimal(
                warning_window_days
            )
            urgency_part = ratio * Decimal("40")
    severity = clamp_pct(overdue_part + urgency_part)
    return FactorSignal(
        factor="milestone_slippage",
        severity_signal=severity,
        data_available=True,
        why=(
            f"{overdue_milestone_count} overdue milestone(s); "
            f"days until current milestone={days_until_milestone}."
        ),
        calculation="min(100, min(60, overdue×30) + urgency_up_to_40)",
        affected_kpis=("confidence", "milestones", "risk"),
        inputs={
            "days_until_milestone": days_until_milestone,
            "overdue_milestone_count": overdue_milestone_count,
            "warning_window_days": warning_window_days,
        },
    )


def signal_quality_regression(
    *,
    has_quality_drift: bool,
    rework_rate_pct: Decimal | None,
) -> FactorSignal:
    if not has_quality_drift and rework_rate_pct is None:
        return FactorSignal(
            factor="quality_regression",
            severity_signal=ZERO,
            data_available=True,
            why="No quality drift or rework signal.",
            calculation="severity = 0 without quality pressure.",
            affected_kpis=("confidence", "quality"),
            inputs={"has_quality_drift": False, "rework_rate_pct": None},
        )
    severity = ZERO
    if has_quality_drift:
        severity += Decimal("50")
    if rework_rate_pct is not None and rework_rate_pct > Decimal("10"):
        severity += min(Decimal("50"), (rework_rate_pct - Decimal("10")) * Decimal("2"))
    return FactorSignal(
        factor="quality_regression",
        severity_signal=clamp_pct(severity),
        data_available=True,
        why=(
            "Quality drift alert active"
            if has_quality_drift
            else "Elevated rework indicates quality regression pressure."
        ),
        calculation="50 if drift else 0 + min(50, max(0, rework-10)×2)",
        affected_kpis=("confidence", "quality", "risk"),
        inputs={
            "has_quality_drift": has_quality_drift,
            "rework_rate_pct": (
                float(quantize_pct(rework_rate_pct)) if rework_rate_pct is not None else None
            ),
        },
    )


def signal_scope_volatility() -> FactorSignal:
    return _unavailable(
        "scope_volatility",
        "Scope-change events are not modeled until Phase 15.2.",
    )


def build_factor_signals(
    *,
    bottlenecks: list[dict[str, Any]],
    rework_rate_pct: Decimal | None,
    headcount_decline_pct: Decimal | None,
    throughput_decline_pct: Decimal,
    throughput_shortfall_pct: Decimal | None,
    days_until_milestone: int | None,
    overdue_milestone_count: int,
    has_quality_drift: bool,
    warning_window_days: int,
    absenteeism_signal: Decimal | None = None,
    dependency_signal: Decimal | None = None,
    scope_signal: Decimal | None = None,
) -> tuple[FactorSignal, ...]:
    """Build one signal per configured factor key (stable order)."""
    signals = {
        "review_turnaround": signal_review_turnaround(bottlenecks=bottlenecks),
        "rework": signal_rework(rework_rate_pct=rework_rate_pct),
        "capacity": signal_capacity(
            headcount_decline_pct=headcount_decline_pct,
            throughput_decline_pct=throughput_decline_pct,
        ),
        "absenteeism": (
            FactorSignal(
                factor="absenteeism",
                severity_signal=clamp_pct(absenteeism_signal),
                data_available=True,
                why="Absenteeism operational signal provided.",
                calculation="severity = clamp(absenteeism_signal)",
                affected_kpis=("confidence", "capacity"),
                inputs={"absenteeism_signal": float(quantize_pct(absenteeism_signal))},
            )
            if absenteeism_signal is not None
            else signal_absenteeism()
        ),
        "queue": signal_queue(
            open_bottleneck_count=len(bottlenecks),
            throughput_shortfall_pct=throughput_shortfall_pct,
        ),
        "blocked_work": signal_blocked_work(bottlenecks=bottlenecks),
        "dependency_delays": (
            FactorSignal(
                factor="dependency_delays",
                severity_signal=clamp_pct(dependency_signal),
                data_available=True,
                why="Dependency operational signal provided.",
                calculation="severity = clamp(dependency_signal)",
                affected_kpis=("confidence", "milestones"),
                inputs={"dependency_signal": float(quantize_pct(dependency_signal))},
            )
            if dependency_signal is not None
            else signal_dependency_delays()
        ),
        "milestone_slippage": signal_milestone_slippage(
            days_until_milestone=days_until_milestone,
            overdue_milestone_count=overdue_milestone_count,
            warning_window_days=warning_window_days,
        ),
        "quality_regression": signal_quality_regression(
            has_quality_drift=has_quality_drift,
            rework_rate_pct=rework_rate_pct,
        ),
        "scope_volatility": (
            FactorSignal(
                factor="scope_volatility",
                severity_signal=clamp_pct(scope_signal),
                data_available=True,
                why="Scope volatility operational signal provided.",
                calculation="severity = clamp(scope_signal)",
                affected_kpis=("confidence", "milestones"),
                inputs={"scope_signal": float(quantize_pct(scope_signal))},
            )
            if scope_signal is not None
            else signal_scope_volatility()
        ),
    }
    return tuple(signals[key] for key in ROOT_CAUSE_FACTOR_KEYS)


def allocate_confidence_loss(
    *,
    overall_confidence: Decimal,
    on_track_threshold: Decimal,
    weights: dict[str, Decimal],
    signals: tuple[FactorSignal, ...],
    severity_medium_points: Decimal,
    severity_high_points: Decimal,
    severity_critical_points: Decimal,
) -> RootCauseBreakdown:
    """Allocate confidence loss across weighted available factor signals."""
    loss = confidence_loss(overall_confidence, on_track_threshold=on_track_threshold)
    signal_by_factor = {item.factor: item for item in signals}

    raw_scores: dict[str, Decimal] = {}
    for key in ROOT_CAUSE_FACTOR_KEYS:
        signal = signal_by_factor[key]
        weight = weights.get(key, ZERO)
        if signal.data_available and signal.severity_signal > ZERO and weight > ZERO:
            raw_scores[key] = weight * signal.severity_signal
        else:
            raw_scores[key] = ZERO

    raw_total = sum(raw_scores.values(), ZERO)
    factors: list[AllocatedFactor] = []
    for key in ROOT_CAUSE_FACTOR_KEYS:
        signal = signal_by_factor[key]
        if loss == ZERO or raw_total == ZERO or raw_scores[key] == ZERO:
            impact_points = ZERO
            impact_percent = ZERO
        else:
            share = raw_scores[key] / raw_total
            impact_points = quantize_pct(-(loss * share))
            impact_percent = quantize_pct(PERCENT * (-impact_points) / loss)

        severity = classify_impact_severity(
            abs(impact_points),
            medium=severity_medium_points,
            high=severity_high_points,
            critical=severity_critical_points,
        )
        label = FACTOR_LABELS.get(key, key)
        if not signal.data_available:
            explanation = signal.why
        elif impact_points == ZERO:
            explanation = f"{label} did not contribute to confidence loss."
        else:
            explanation = (
                f"{label} accounts for {impact_percent}% of the "
                f"{loss}-point confidence shortfall ({impact_points} points)."
            )
        evidence = {
            "why": signal.why,
            "calculation": signal.calculation,
            "affected_kpis": list(signal.affected_kpis),
            "inputs": signal.inputs,
            "data_available": signal.data_available,
            "severity_signal": float(quantize_pct(signal.severity_signal)),
            "weight": float(weights.get(key, ZERO)),
            "confidence_impact": float(impact_points),
        }
        factors.append(
            AllocatedFactor(
                factor=key,
                impact_percent=impact_percent,
                impact_points=impact_points,
                severity=severity,
                explanation=explanation,
                evidence_json=evidence,
            )
        )

    # Reconcile rounding so impact_percent of contributing factors sums to 100 when loss > 0.
    if loss > ZERO and raw_total > ZERO:
        contributing = [f for f in factors if f.impact_points < ZERO]
        if contributing:
            pct_sum = sum((f.impact_percent for f in contributing), ZERO)
            drift = PERCENT - pct_sum
            if drift != ZERO:
                top = max(contributing, key=lambda f: abs(f.impact_points))
                idx = factors.index(top)
                factors[idx] = AllocatedFactor(
                    factor=top.factor,
                    impact_percent=quantize_pct(top.impact_percent + drift),
                    impact_points=top.impact_points,
                    severity=top.severity,
                    explanation=top.explanation,
                    evidence_json=top.evidence_json,
                )

    return RootCauseBreakdown(
        overall_confidence=quantize_pct(overall_confidence),
        confidence_loss=loss,
        factors=tuple(factors),
    )


def trend_direction(
    current: Decimal | None,
    previous: Decimal | None,
    *,
    flat_tolerance: Decimal = Decimal("1.00"),
) -> TrendDirection:
    if current is None or previous is None:
        return "insufficient_data"
    delta = current - previous
    if abs(delta) <= flat_tolerance:
        return "flat"
    return "up" if delta > ZERO else "down"


def root_cause_summary_for_ai(breakdown: RootCauseBreakdown, *, limit: int = 3) -> dict[str, Any]:
    """Compact deterministic summary for AI grounding (no invented causes)."""
    ranked = sorted(
        [f for f in breakdown.factors if f.impact_percent > ZERO],
        key=lambda f: f.impact_percent,
        reverse=True,
    )[:limit]
    return {
        "overall_confidence": float(breakdown.overall_confidence),
        "confidence_loss": float(breakdown.confidence_loss),
        "top_causes": [
            {
                "factor": item.factor,
                "label": FACTOR_LABELS.get(item.factor, item.factor),
                "impact_percent": float(item.impact_percent),
                "impact_points": float(item.impact_points),
                "explanation": item.explanation,
            }
            for item in ranked
        ],
        "model_version": breakdown.model_version,
    }
