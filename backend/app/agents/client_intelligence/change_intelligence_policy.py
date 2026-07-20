"""Injected Change Intelligence materiality policy contract.

No production default materiality threshold or business-meaning rule is defined.
Policies classify verified change candidates only — never a ClientEvidencePack.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from app.agents.client_intelligence.change_intelligence_contracts import (
    ChangeCandidateContext,
    ChangeMaterialityPolicyDecision,
)


@runtime_checkable
class ChangeMaterialityPolicy(Protocol):
    """Deterministic, side-effect-free change materiality policy."""

    @property
    def rules_version(self) -> str:
        """Non-empty policy version identifier."""

    def evaluate(
        self,
        candidates: ChangeCandidateContext,
    ) -> ChangeMaterialityPolicyDecision:
        """Classify verified change candidates only."""
