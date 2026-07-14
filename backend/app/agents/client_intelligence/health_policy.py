"""Injected Project Health classification policy contract.

No production default policy is defined. CI-DQ07 remains unresolved.
Test fixture policies may live in tests only.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from app.agents.client_intelligence.contracts import ClientEvidencePack
from app.agents.client_intelligence.health_contracts import ProjectHealthPolicyDecision


@runtime_checkable
class ProjectHealthPolicy(Protocol):
    """Deterministic, side-effect-free health classification policy.

    Implementations must not access the database, network, LLM, wall clock,
    or random sources. They consume only the provided ClientEvidencePack.
    """

    @property
    def rules_version(self) -> str:
        """Non-empty policy version identifier."""

    def required_signal_keys(self) -> frozenset[str]:
        """Critical signal keys that the engine treats as required."""

    def evaluate(self, pack: ClientEvidencePack) -> ProjectHealthPolicyDecision:
        """Classify the pack once. Must be pure and deterministic."""
