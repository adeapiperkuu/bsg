"""Injected Delivery Trend deviation policy contract.

No production default materiality threshold is defined. Policies classify
verified deviation candidates only — never a ClientEvidencePack or ORM row.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from app.agents.client_intelligence.delivery_trend_contracts import (
    DeliveryTrendDeviationCandidateContext,
    DeliveryTrendDeviationPolicyDecision,
)


@runtime_checkable
class DeliveryTrendDeviationPolicy(Protocol):
    """Deterministic, side-effect-free deviation materiality policy."""

    @property
    def rules_version(self) -> str:
        """Non-empty policy version identifier."""

    def evaluate(
        self,
        candidates: DeliveryTrendDeviationCandidateContext,
    ) -> DeliveryTrendDeviationPolicyDecision:
        """Classify verified deviation candidates only."""
