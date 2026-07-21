"""Deterministic reporting-period resolution for Client Intelligence."""

from __future__ import annotations

from datetime import date, timedelta

from app.agents.client_intelligence.contracts import ReportingPeriod


def resolve_reporting_period(as_of: date) -> ReportingPeriod:
    """Resolve the Monday–Sunday week containing ``as_of`` and the prior week.

    Pure function: does not read the system clock.
    """
    start_date = as_of - timedelta(days=as_of.weekday())
    end_date = start_date + timedelta(days=6)
    previous_start_date = start_date - timedelta(days=7)
    previous_end_date = start_date - timedelta(days=1)
    return ReportingPeriod(
        start_date=start_date,
        end_date=end_date,
        previous_start_date=previous_start_date,
        previous_end_date=previous_end_date,
        as_of=as_of,
    )
