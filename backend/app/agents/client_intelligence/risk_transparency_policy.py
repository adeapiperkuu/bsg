"""Injected Risk Transparency policy contract.

No production default materiality or client-visibility policy is defined.
Business impact (CI-DQ09) and mitigation authoring remain unavailable.

The policy receives only an isolated verified candidate context — never a
ClientEvidencePack, ORM model, or internal detail text.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from app.agents.client_intelligence.risk_transparency_contracts import (
    RiskTransparencyCandidateContext,
    RiskTransparencyPolicyDecision,
)


@runtime_checkable
class RiskTransparencyPolicy(Protocol):
    """Deterministic, side-effect-free risk selection policy.

    Implementations must not access the database, network, LLM, wall clock,
    or random sources. They must not invent business impact or mitigation.
    """

    @property
    def rules_version(self) -> str:
        """Non-empty policy version identifier."""

    def evaluate(
        self,
        candidates: RiskTransparencyCandidateContext,
    ) -> RiskTransparencyPolicyDecision:
        """Select verified candidates only. Must be pure and deterministic."""
