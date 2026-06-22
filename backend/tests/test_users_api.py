from app.db.models import AppRole


def test_only_super_admin_role_value() -> None:
    assert AppRole.SUPER_ADMIN.value == "super_admin"


def test_delivery_manager_cannot_be_super_admin() -> None:
    assert AppRole.DELIVERY_MANAGER != AppRole.SUPER_ADMIN
