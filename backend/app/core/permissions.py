from app.db.models import AppRole
from app.schemas.domain import MePermissions


def permissions_for_role(role: AppRole) -> MePermissions:
    return MePermissions(
        can_manage_projects=role in {AppRole.DELIVERY_MANAGER, AppRole.SUPER_ADMIN},
        can_approve_communications=role in {AppRole.DELIVERY_MANAGER, AppRole.SUPER_ADMIN},
        can_manage_metric_configurations=role == AppRole.SUPER_ADMIN,
        can_view_cross_client_portfolio=role in {AppRole.BSG_LEADERSHIP, AppRole.SUPER_ADMIN},
        can_manage_users=role == AppRole.SUPER_ADMIN,
        can_manage_organisations=role == AppRole.SUPER_ADMIN,
    )
