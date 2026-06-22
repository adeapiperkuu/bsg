from app.core.permissions import permissions_for_role
from app.db.models import AppRole
from app.schemas.domain import MePermissions, MeRead, OrganisationSummary
from uuid import uuid4


def test_me_read_shape() -> None:
    org_id = uuid4()
    user_id = uuid4()
    me = MeRead(
        id=user_id,
        org_id=org_id,
        email="user@example.com",
        full_name="Test User",
        role=AppRole.DELIVERY_MANAGER,
        is_active=True,
        organisation=OrganisationSummary(id=org_id, name="Acme", vertical="finance", region="eu"),
        permissions=permissions_for_role(AppRole.DELIVERY_MANAGER),
    )
    assert me.permissions.can_manage_projects is True
    assert isinstance(me.permissions, MePermissions)
    assert me.organisation is not None
    assert me.organisation.name == "Acme"
