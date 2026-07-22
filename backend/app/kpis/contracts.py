"""Immutable contracts for the KPI semantic layer."""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from typing import Any, Protocol
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import CurrentUser


@dataclass(frozen=True, slots=True)
class KpiDependencySpec:
    depends_on_kpi_key: str
    depends_on_version: str | None = None
    dependency_type: str = "input"


@dataclass(frozen=True, slots=True)
class RegisteredKpi:
    """In-code KPI registration (calculator + semantic metadata)."""

    kpi_key: str
    version: str
    name: str
    description: str
    owner_agent: str
    scope: str
    calculator_key: str
    unit: str = "count"
    trend_direction: str = "higher_is_better"
    refresh_frequency: str = "on_demand"
    formula_description: str | None = None
    source_fields: tuple[str, ...] = ()
    default_thresholds: Mapping[str, Any] = field(default_factory=dict)
    explainability: Mapping[str, Any] = field(default_factory=dict)
    allowed_roles: tuple[str, ...] = (
        "super_admin",
        "bsg_leadership",
        "delivery_manager",
    )
    is_client_visible: bool = False
    compatibility_status: str = "current"
    dependencies: tuple[KpiDependencySpec, ...] = ()
    metric_config_key: str | None = None


@dataclass(frozen=True, slots=True)
class EvaluationContext:
    current_user: CurrentUser
    org_id: UUID | None
    project_id: UUID | None = None
    as_of: datetime | None = None
    version: str | None = None
    inputs: Mapping[str, Any] = field(default_factory=dict)
    include_explainability: bool = True
    session: AsyncSession | None = None


@dataclass(frozen=True, slots=True)
class CalculatorResult:
    status: str = "ok"
    numeric_value: Decimal | None = None
    text_value: str | None = None
    provenance: Mapping[str, Any] = field(default_factory=dict)
    explainability: Mapping[str, Any] = field(default_factory=dict)


class KpiCalculator(Protocol):
    calculator_key: str

    def __call__(self, context: EvaluationContext) -> CalculatorResult | Awaitable[CalculatorResult]:
        ...


CalculatorFn = Callable[[EvaluationContext], CalculatorResult | Awaitable[CalculatorResult]]
