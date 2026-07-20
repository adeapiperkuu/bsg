"""Injected Delivery Confidence explanation policy contract.

No production default explanation policy is defined. Core Delivery score, band,
milestone, forecast, quality, and trend remain engine-owned.

The policy receives only an isolated verified candidate context — never a
ClientEvidencePack or raw source objects.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from app.agents.client_intelligence.delivery_confidence_contracts import (
    DeliveryConfidenceCandidateContext,
    DeliveryConfidenceExplanationDecision,
)


@runtime_checkable
class DeliveryConfidenceExplanationPolicy(Protocol):
    """Deterministic, side-effect-free explanation policy.

    Implementations must not access the database, network, LLM, wall clock,
    or random sources. They must not modify Delivery-owned core facts.
    """

    @property
    def rules_version(self) -> str:
        """Non-empty policy version identifier."""

    def evaluate(
        self,
        candidates: DeliveryConfidenceCandidateContext,
    ) -> DeliveryConfidenceExplanationDecision:
        """Select verified drivers only. Must be pure and deterministic."""
