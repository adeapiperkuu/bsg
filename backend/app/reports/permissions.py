"""Role and lifecycle checks for reports."""

from __future__ import annotations

from app.core.security import CurrentUser
from app.db.models import AppRole, ReportInstance, ReportTemplate


def _role(user: CurrentUser) -> str:
    return user.role.value if isinstance(user.role, AppRole) else str(user.role)


def _same_org(user: CurrentUser, org_id) -> bool:
    return user.role == AppRole.SUPER_ADMIN or user.org_id == org_id


def can_view_template(template: ReportTemplate, current_user: CurrentUser) -> bool:
    if not _same_org(current_user, template.org_id or current_user.org_id):
        return False
    role = _role(current_user)
    if role == AppRole.CLIENT.value:
        return (
            template.status == "active"
            and template.is_client_visible
            and template.audience == "client"
            and role in (template.allowed_roles or [])
        )
    return role in (template.allowed_roles or []) or current_user.role == AppRole.SUPER_ADMIN


def can_view_report(report: ReportInstance, current_user: CurrentUser) -> bool:
    if not _same_org(current_user, report.org_id):
        return False
    if current_user.role == AppRole.CLIENT:
        return report.status == "distributed" and report.audience == "client"
    return current_user.role in {
        AppRole.DELIVERY_MANAGER,
        AppRole.BSG_LEADERSHIP,
        AppRole.SUPER_ADMIN,
    }


def can_mutate_report(report: ReportInstance, current_user: CurrentUser) -> bool:
    return (
        _same_org(current_user, report.org_id)
        and current_user.role in {AppRole.DELIVERY_MANAGER, AppRole.SUPER_ADMIN}
        and report.status not in {"distributed", "cancelled"}
    )


def can_approve_report(report: ReportInstance, current_user: CurrentUser) -> bool:
    return (
        _same_org(current_user, report.org_id)
        and current_user.role
        in {AppRole.DELIVERY_MANAGER, AppRole.BSG_LEADERSHIP, AppRole.SUPER_ADMIN}
        and report.status == "in_review"
    )
