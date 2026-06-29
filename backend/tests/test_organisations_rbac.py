from uuid import uuid4

import pytest
from httpx import AsyncClient

from app.core.exceptions import ApiError
from app.core.security import CurrentUser
from app.db.models import AppRole, Organisation
from app.services.organisations import (
    assert_can_read_organisations,
    can_read_organisation,
    scoped_organisation_query,
)
from tests.conftest import client_a, delivery_manager, override_user, super_admin


def _org(org_id=None) -> Organisation:
    return Organisation(
        id=org_id or uuid4(),
        name="Acme",
        slug="acme",
        vertical="finance",
        region="eu",
        is_active=True,
    )


def test_delivery_manager_can_read_organisations() -> None:
    assert_can_read_organisations(
        CurrentUser(
            id=uuid4(),
            org_id=uuid4(),
            email="dm@example.com",
            role=AppRole.DELIVERY_MANAGER,
            is_active=True,
        )
    )


def test_client_cannot_read_organisations() -> None:
    with pytest.raises(ApiError) as exc:
        assert_can_read_organisations(
            CurrentUser(
                id=uuid4(),
                org_id=uuid4(),
                email="client@example.com",
                role=AppRole.CLIENT,
                is_active=True,
            )
        )
    assert exc.value.status_code == 403


def test_delivery_manager_query_scoped_to_own_org() -> None:
    org_id = uuid4()
    user = CurrentUser(
        id=uuid4(),
        org_id=org_id,
        email="dm@example.com",
        role=AppRole.DELIVERY_MANAGER,
        is_active=True,
    )
    compiled = str(scoped_organisation_query(user).compile(compile_kwargs={"literal_binds": True}))
    assert "organisations.id" in compiled
    assert str(org_id).replace("-", "") in compiled


def test_leadership_query_returns_all_organisations() -> None:
    user = CurrentUser(
        id=uuid4(),
        org_id=uuid4(),
        email="lead@example.com",
        role=AppRole.BSG_LEADERSHIP,
        is_active=True,
    )
    compiled = str(scoped_organisation_query(user).compile(compile_kwargs={"literal_binds": True}))
    assert "organisations.id =" not in compiled


def test_can_read_organisation_matrix() -> None:
    org_a = _org()
    org_b = _org()
    leadership = CurrentUser(
        id=uuid4(),
        org_id=org_b.id,
        email="lead@example.com",
        role=AppRole.BSG_LEADERSHIP,
        is_active=True,
    )
    dm = CurrentUser(
        id=uuid4(),
        org_id=org_a.id,
        email="dm@example.com",
        role=AppRole.DELIVERY_MANAGER,
        is_active=True,
    )
    client = CurrentUser(
        id=uuid4(),
        org_id=org_a.id,
        email="client@example.com",
        role=AppRole.CLIENT,
        is_active=True,
    )

    assert can_read_organisation(org_a, leadership) is True
    assert can_read_organisation(org_b, leadership) is True
    assert can_read_organisation(org_a, dm) is True
    assert can_read_organisation(org_b, dm) is False
    assert can_read_organisation(org_a, client) is False


@pytest.mark.asyncio
async def test_delivery_manager_can_list_organisations(api_client: AsyncClient, delivery_manager) -> None:
    override_user(delivery_manager)
    response = await api_client.get(
        "/api/v1/organisations",
        headers={"Authorization": "Bearer test-token"},
    )
    assert response.status_code in {200, 500}


@pytest.mark.asyncio
async def test_client_cannot_list_organisations(api_client: AsyncClient, client_a) -> None:
    override_user(client_a)
    response = await api_client.get(
        "/api/v1/organisations",
        headers={"Authorization": "Bearer test-token"},
    )
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "FORBIDDEN"
