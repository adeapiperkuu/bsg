"""Centralized field-level authorization for API response shaping.

Role gates (``require_role``) control *endpoint* access. This module controls
which *fields* within an authorized response a role may receive. Unauthorized
fields are stripped on the backend and never sent to the frontend.

Policy summary (platform domains):

- **client** — project confidence, milestones, risks (client-safe surfaces)
- **delivery_manager** — staffing, utilization, delivery metrics
- **bsg_leadership** — profitability, internal staffing, performance, escalation
- **super_admin** — full access
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from pydantic import BaseModel

from app.db.models import AppRole

FieldDomain = str

# Field allow-lists keyed by domain → role → frozenset of field names.
# SUPER_ADMIN is omitted from each domain map and always receives full access.
# An empty frozenset means the role may not receive any fields in that domain.
FIELD_PERMISSIONS: dict[str, dict[AppRole, frozenset[str]]] = {
    "project_health": {
        AppRole.CLIENT: frozenset(
            {
                "project_id",
                "project_name",
                "confidence_score",
                "milestones",
                "risks",
                "status",
                "summary",
            },
        ),
        AppRole.DELIVERY_MANAGER: frozenset(
            {
                "project_id",
                "project_name",
                "confidence_score",
                "milestones",
                "risks",
                "status",
                "summary",
                "staffing",
                "utilization",
                "delivery_metrics",
                "throughput",
                "capacity",
            },
        ),
        AppRole.BSG_LEADERSHIP: frozenset(
            {
                "project_id",
                "project_name",
                "confidence_score",
                "milestones",
                "risks",
                "status",
                "summary",
                "staffing",
                "utilization",
                "delivery_metrics",
                "throughput",
                "capacity",
                "profitability",
                "internal_staffing",
                "performance_metrics",
                "escalation_history",
                "margin",
                "cost",
            },
        ),
    },
    "workforce": {
        AppRole.CLIENT: frozenset(),
        AppRole.DELIVERY_MANAGER: frozenset(
            {
                "project_id",
                "summary",
                "utilization",
                "skill_matrix",
                "training_gaps",
                "capability_gaps",
                "recommendations",
                "optimization",
            },
        ),
        AppRole.BSG_LEADERSHIP: frozenset(
            {
                "project_id",
                "summary",
                "utilization",
                "skill_matrix",
                "training_gaps",
                "capability_gaps",
                "recommendations",
                "optimization",
            },
        ),
    },
    "workforce_optimization": {
        AppRole.CLIENT: frozenset(),
        AppRole.DELIVERY_MANAGER: frozenset(
            {
                "project_id",
                "generated_at",
                "skill_matches",
                "rebalancing",
                "resource_planning",
                "sme_coverage",
                "utilization_forecast",
                "skill_shortages",
                "insights",
                "priority_actions",
            },
        ),
        AppRole.BSG_LEADERSHIP: frozenset(
            {
                "project_id",
                "generated_at",
                "skill_matches",
                "rebalancing",
                "resource_planning",
                "sme_coverage",
                "utilization_forecast",
                "skill_shortages",
                "insights",
                "priority_actions",
            },
        ),
    },
}


def resolve_allowed_fields(domain: FieldDomain, role: AppRole) -> frozenset[str] | None:
    """Return allowed field names, or ``None`` when the role has full access.

    An empty frozenset means the role may not receive any fields in this domain.
    Unknown domains return ``None`` (no filtering) for backwards compatibility.
    """
    domain_policy = FIELD_PERMISSIONS.get(domain)
    if domain_policy is None:
        return None
    if role == AppRole.SUPER_ADMIN:
        return None
    return domain_policy.get(role, frozenset())


def filter_dict_fields(
    data: Mapping[str, Any],
    role: AppRole,
    *,
    domain: FieldDomain,
) -> dict[str, Any]:
    """Return a copy of ``data`` containing only fields the role may see."""
    allowed = resolve_allowed_fields(domain, role)
    if allowed is None:
        return dict(data)
    return {key: value for key, value in data.items() if key in allowed}


def filter_model_fields(
    model: BaseModel,
    role: AppRole,
    *,
    domain: FieldDomain,
) -> dict[str, Any]:
    """Serialize a Pydantic model and strip unauthorized fields."""
    payload = model.model_dump(mode="json")
    return filter_dict_fields(payload, role, domain=domain)


def authorize_fields(
    payload: BaseModel | Mapping[str, Any],
    role: AppRole,
    *,
    domain: FieldDomain,
) -> dict[str, Any]:
    """Public entry point used by services/routes to shape responses."""
    if isinstance(payload, BaseModel):
        return filter_model_fields(payload, role, domain=domain)
    return filter_dict_fields(payload, role, domain=domain)


def role_can_access_field(role: AppRole, domain: FieldDomain, field_name: str) -> bool:
    """Return True when ``role`` may receive ``field_name`` in ``domain``."""
    allowed = resolve_allowed_fields(domain, role)
    if allowed is None:
        return True
    return field_name in allowed
