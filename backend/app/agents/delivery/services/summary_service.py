"""Deterministic structured delivery summary assembly for dashboard responses."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from app.agents.delivery.analytics.summary import build_structured_summary


def build_structured_summary_payload(
    context: Any,
    scores: Any,
    *,
    generated_at: datetime | None = None,
) -> dict[str, Any]:
    """Assemble structured_summary from already-scored delivery context.

    Side-effect free: no DB access, no AI, and no mutation of context/scores.
    ``context`` and ``scores`` are the dashboard scoring dataclasses; typed as
    ``Any`` to avoid an import cycle with ``scoring_service``.
    """
    snapshots = context.throughput_snapshots
    latest = snapshots[0] if snapshots else None
    previous = snapshots[1] if len(snapshots) > 1 else None
    return build_structured_summary(
        as_of_date=context.as_of_date,
        traffic_light=scores.traffic_light,
        confidence=scores.confidence,
        risk_score=scores.risk,
        risk_tier=scores.risk_tier,
        rolling_windows=context.rolling_windows,
        flat_tolerance_pct=context.thresholds.risk.trend_tolerance,
        latest_throughput=latest,
        previous_throughput=previous,
        daily_target_units=context.project.get("daily_target_units"),
        milestones=context.milestones,
        risks=context.risks,
        bottlenecks=context.bottlenecks,
        has_sufficient_data=scores.has_sufficient_data,
        quality_snapshot=context.quality_snapshot,
        milestone_warning_window_days=context.thresholds.risk.milestone_warning_window_days,
        stale_after_days=context.thresholds.bottleneck.stale_after_days,
        generated_at=generated_at,
    )
