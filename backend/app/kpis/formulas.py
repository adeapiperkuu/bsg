"""Reusable pure KPI formulas shared by providers and agent adapters."""

from __future__ import annotations

from collections.abc import Callable, Iterable, Sequence
from decimal import Decimal
from typing import TypeVar

T = TypeVar("T")


def average_numeric(values: Iterable[Decimal | float | int | None]) -> Decimal | None:
    """Return the arithmetic mean of non-null numeric values, or None if empty."""
    cleaned = [Decimal(str(value)) for value in values if value is not None]
    if not cleaned:
        return None
    return sum(cleaned, Decimal("0")) / Decimal(len(cleaned))


def average_by_getter(
    items: Sequence[T], getter: Callable[[T], Decimal | float | int | None]
) -> Decimal | None:
    """Average a mapped field across items, ignoring nulls."""
    return average_numeric(getter(item) for item in items)


def average_utilization_pct(values: Sequence[Decimal | float | int | None]) -> str | None:
    """Match Workforce dashboard formatting: one-decimal string mean, treating null as 0."""
    if not values:
        return None
    total = sum(float(value or 0) for value in values)
    return str(round(total / len(values), 1))


def count_truthy(flags: Iterable[bool]) -> int:
    return sum(1 for flag in flags if flag)


def sla_adherence_from_counts(on_time: int, total: int) -> float:
    """SQL-path compatible SLA percentage used by Governance bootstrap KPIs."""
    if total == 0:
        return 100.0
    return round((on_time / total) * 100.0, 1)


def mean_optional_floats(values: Sequence[float | None]) -> float | None:
    cleaned = [value for value in values if value is not None]
    if not cleaned:
        return None
    return sum(cleaned) / len(cleaned)


def summary_metric_availability(
    *,
    has_evidence: bool,
    has_score: bool,
    is_partial: bool = False,
) -> str:
    """Client Intelligence availability without inventing scores."""
    if has_score and is_partial:
        return "partial"
    if has_score:
        return "available"
    if is_partial:
        return "partial"
    if has_evidence:
        return "no_data"
    return "unavailable"
