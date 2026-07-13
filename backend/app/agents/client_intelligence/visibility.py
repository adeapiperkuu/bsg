"""Client-safe visibility policy for Client Intelligence evidence packs.

Deny-by-default (CI-DQ04 interim): optional metrics are client-visible only when an
active ``metric_configurations`` row has ``is_client_visible=true`` and the key is
a known ``ClientVisibleMetric``. Seed SQL is not authoritative at runtime.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from enum import StrEnum

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import MetricConfiguration

_MAX_METRIC_CONFIG_ROWS = 100


class ClientVisibleMetric(StrEnum):
    """Metric keys Client Intelligence knows how to authorize.

    Unknown DB keys with ``is_client_visible=true`` are ignored and never grant access.
    """

    DELIVERY_CONFIDENCE = "delivery_confidence"
    THROUGHPUT_ROLLING_7D = "throughput_rolling_7d"
    GOLD_SET_ACCURACY = "gold_set_accuracy"
    REWORK_RATE = "rework_rate"


_KNOWN_METRIC_KEYS: frozenset[str] = frozenset(metric.value for metric in ClientVisibleMetric)


@dataclass(frozen=True, slots=True)
class ClientVisibilityPolicy:
    """Immutable client-safe visibility contract for one pack build."""

    visible_metrics: frozenset[ClientVisibleMetric]
    project_identity_visible: bool = True
    milestone_core_fields_visible: bool = True
    risk_summary_visible: bool = False
    bottleneck_summary_visible: bool = False

    def allows(self, metric: ClientVisibleMetric) -> bool:
        return metric in self.visible_metrics

    def allows_any_throughput(self) -> bool:
        return self.allows(ClientVisibleMetric.THROUGHPUT_ROLLING_7D)

    def allows_any_quality(self) -> bool:
        return self.allows(ClientVisibleMetric.GOLD_SET_ACCURACY) or self.allows(
            ClientVisibleMetric.REWORK_RATE
        )

    def fingerprint(self) -> str:
        """Deterministic fingerprint of authorizing metric keys only."""
        keys = sorted(metric.value for metric in self.visible_metrics)
        flags = (
            f"project={int(self.project_identity_visible)}",
            f"milestones={int(self.milestone_core_fields_visible)}",
            f"risks={int(self.risk_summary_visible)}",
            f"bottlenecks={int(self.bottleneck_summary_visible)}",
        )
        payload = "|".join([*flags, *keys])
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def empty_client_visibility_policy() -> ClientVisibilityPolicy:
    """Policy with no optional metrics visible (deny-by-default)."""
    return ClientVisibilityPolicy(visible_metrics=frozenset())


async def load_client_visibility_policy(
    session: AsyncSession,
) -> ClientVisibilityPolicy:
    """Load client-visible metrics from runtime ``metric_configurations``.

    Only known keys with ``is_client_visible=true`` authorize fields. Risk and
    bottleneck summaries remain disabled until a dedicated policy is approved.
    """
    rows = list(
        (
            await session.execute(
                select(MetricConfiguration)
                .where(
                    MetricConfiguration.deleted_at.is_(None),
                    MetricConfiguration.is_client_visible.is_(True),
                )
                .order_by(
                    MetricConfiguration.display_order.asc(),
                    MetricConfiguration.metric_key.asc(),
                )
                .limit(_MAX_METRIC_CONFIG_ROWS)
            )
        ).scalars()
    )

    visible: set[ClientVisibleMetric] = set()
    for row in rows:
        key = row.metric_key
        if key not in _KNOWN_METRIC_KEYS:
            continue
        visible.add(ClientVisibleMetric(key))

    return ClientVisibilityPolicy(visible_metrics=frozenset(visible))
