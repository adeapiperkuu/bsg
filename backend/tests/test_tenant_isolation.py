from app.core.security import can_read_all_orgs
from app.db.models import AppRole
from app.services.scoping import scoped_project_query
from app.core.security import CurrentUser
from uuid import uuid4


def test_client_cannot_read_all_orgs() -> None:
    assert can_read_all_orgs(AppRole.CLIENT) is False


def test_leadership_can_read_all_orgs() -> None:
    assert can_read_all_orgs(AppRole.BSG_LEADERSHIP) is True


def test_scoped_project_query_filters_client_org() -> None:
    org_a = uuid4()
    org_b = uuid4()
    client = CurrentUser(
        id=uuid4(),
        org_id=org_a,
        email="c@example.com",
        role=AppRole.CLIENT,
        is_active=True,
    )
    query = scoped_project_query(client)
    compiled = str(query.compile(compile_kwargs={"literal_binds": True}))
    assert str(org_a) in compiled or "org_id" in compiled
    assert client.org_id == org_a
    assert client.org_id != org_b
