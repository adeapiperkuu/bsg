from datetime import date
from decimal import Decimal
from uuid import uuid4

import pytest
from httpx import AsyncClient
from pydantic import ValidationError

from app.core.exceptions import ApiError
from app.core.security import CurrentUser
from app.db.models import AppRole, DeliverySite, Project, Team, UtilizationSnapshot
from app.schemas.domain import UtilizationSnapshotCreate, UtilizationSnapshotUpdate
from app.services.workforce import (
    create_utilization_snapshot,
    get_utilization_snapshot_or_404,
    resolve_utilization_pct,
    resolve_utilization_team,
    soft_delete_utilization_snapshot,
    update_utilization_snapshot,
)
from tests.conftest import ORG_A, client_a, override_user


def _user(role: AppRole, org_id=None) -> CurrentUser:
    return CurrentUser(
        id=uuid4(),
        org_id=org_id or uuid4(),
        email=f"{role.value}@example.com",
        role=role,
        is_active=True,
    )


def _project(org_id) -> Project:
    return Project(
        id=uuid4(),
        org_id=org_id,
        name="Test Project",
        vertical="medical",
        status="active",
        start_date="2026-01-01",
        target_end_date="2026-12-31",
    )


def _team(org_id, project_id) -> Team:
    return Team(
        id=uuid4(),
        org_id=org_id,
        project_id=project_id,
        name="Radiology Pod A",
        site=DeliverySite.INDIA,
        domain="radiology",
        is_active=True,
    )


def _snapshot(org_id, project_id, team_id=None) -> UtilizationSnapshot:
    return UtilizationSnapshot(
        id=uuid4(),
        org_id=org_id,
        project_id=project_id,
        team_id=team_id,
        annotator_id=None,
        snapshot_date=date(2026, 6, 1),
        allocated_hours=Decimal("34.00"),
        available_hours=Decimal("40.00"),
        utilization_pct=Decimal("85.00"),
    )


class FakeResult:
    def __init__(self, value):
        self._value = value

    def scalar_one_or_none(self):
        return self._value


class FakeSession:
    def __init__(self, *, team=None, project=None, snapshot=None):
        self.team = team
        self.project = project
        self.snapshot = snapshot
        self.added: list[object] = []

    def add(self, obj: object) -> None:
        self.added.append(obj)

    async def flush(self) -> None:
        return None

    async def execute(self, stmt):
        compiled = str(stmt.compile(compile_kwargs={"literal_binds": True}))
        if "FROM teams" in compiled or "teams." in compiled:
            return FakeResult(self.team)
        if "FROM projects" in compiled or "projects." in compiled:
            return FakeResult(self.project)
        if "FROM utilization_snapshots" in compiled or "utilization_snapshots." in compiled:
            return FakeResult(self.snapshot)
        return FakeResult(None)


def test_utilization_snapshot_create_rejects_negative_hours() -> None:
    with pytest.raises(ValidationError):
        UtilizationSnapshotCreate(
            snapshot_date=date(2026, 6, 1),
            allocated_hours=Decimal("-1"),
            available_hours=Decimal("40"),
        )


def test_utilization_snapshot_create_rejects_annotator_without_team() -> None:
    with pytest.raises(ValidationError):
        UtilizationSnapshotCreate(
            snapshot_date=date(2026, 6, 1),
            annotator_id=uuid4(),
            allocated_hours=Decimal("10"),
            available_hours=Decimal("20"),
        )


def test_resolve_utilization_pct_computes_from_hours() -> None:
    pct = resolve_utilization_pct(Decimal("34"), Decimal("40"), None)
    assert pct == Decimal("85.00")


def test_resolve_utilization_pct_uses_explicit_value() -> None:
    pct = resolve_utilization_pct(Decimal("34"), Decimal("40"), Decimal("110"))
    assert pct == Decimal("110")


def test_resolve_utilization_pct_rejects_zero_available_without_explicit_pct() -> None:
    with pytest.raises(ApiError) as exc:
        resolve_utilization_pct(Decimal("10"), Decimal("0"), None)
    assert exc.value.status_code == 400


@pytest.mark.asyncio
async def test_resolve_utilization_team_rejects_cross_project_team() -> None:
    org_a = uuid4()
    project = _project(org_a)
    other_project_id = uuid4()
    team = _team(org_a, other_project_id)
    session = FakeSession(team=team)
    user = _user(AppRole.DELIVERY_MANAGER, org_a)

    with pytest.raises(ApiError) as exc:
        await resolve_utilization_team(session, project, team.id, user, for_mutation=True)

    assert exc.value.status_code == 404


@pytest.mark.asyncio
async def test_create_utilization_snapshot_sets_org_and_computes_pct() -> None:
    org_a = uuid4()
    project = _project(org_a)
    team = _team(org_a, project.id)
    session = FakeSession(team=team, project=project)
    user = _user(AppRole.DELIVERY_MANAGER, org_a)

    snapshot = await create_utilization_snapshot(
        session,
        project,
        UtilizationSnapshotCreate(
            snapshot_date=date(2026, 6, 1),
            team_id=team.id,
            allocated_hours=Decimal("30"),
            available_hours=Decimal("40"),
        ),
        user,
    )

    assert snapshot.org_id == project.org_id
    assert snapshot.project_id == project.id
    assert snapshot.utilization_pct == Decimal("75.00")
    assert len(session.added) == 1


@pytest.mark.asyncio
async def test_get_utilization_snapshot_or_404_cross_org_returns_404() -> None:
    org_a = uuid4()
    org_b = uuid4()
    snapshot = _snapshot(org_a, uuid4())
    session = FakeSession(snapshot=snapshot)
    user = _user(AppRole.DELIVERY_MANAGER, org_b)

    with pytest.raises(ApiError) as exc:
        await get_utilization_snapshot_or_404(session, snapshot.id, user)

    assert exc.value.status_code == 404


@pytest.mark.asyncio
async def test_update_utilization_snapshot_recomputes_pct_when_hours_change() -> None:
    org_a = uuid4()
    project = _project(org_a)
    snapshot = _snapshot(org_a, project.id)
    session = FakeSession(snapshot=snapshot, project=project)
    user = _user(AppRole.DELIVERY_MANAGER, org_a)

    updated = await update_utilization_snapshot(
        session,
        snapshot,
        UtilizationSnapshotUpdate(allocated_hours=Decimal("20")),
        user,
    )

    assert updated.utilization_pct == Decimal("50.00")


@pytest.mark.asyncio
async def test_soft_delete_utilization_snapshot_sets_deleted_at() -> None:
    snapshot = _snapshot(uuid4(), uuid4())
    session = FakeSession(snapshot=snapshot)

    await soft_delete_utilization_snapshot(session, snapshot)

    assert snapshot.deleted_at is not None


@pytest.mark.asyncio
async def test_client_cannot_list_utilization_http(api_client: AsyncClient, client_a) -> None:
    override_user(client_a)
    response = await api_client.get(
        f"/api/v1/projects/{uuid4()}/utilization",
        headers={"Authorization": "Bearer test-token"},
    )
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "FORBIDDEN"


@pytest.mark.asyncio
async def test_client_cannot_create_utilization_http(api_client: AsyncClient, client_a) -> None:
    override_user(client_a)
    response = await api_client.post(
        f"/api/v1/projects/{uuid4()}/utilization",
        json={
            "snapshot_date": "2026-06-01",
            "allocated_hours": "30",
            "available_hours": "40",
        },
        headers={"Authorization": "Bearer test-token"},
    )
    assert response.status_code == 403


@pytest.mark.asyncio
async def test_client_cannot_update_utilization_http(api_client: AsyncClient, client_a) -> None:
    override_user(client_a)
    response = await api_client.patch(
        f"/api/v1/utilization/{uuid4()}",
        json={"allocated_hours": "20"},
        headers={"Authorization": "Bearer test-token"},
    )
    assert response.status_code == 403


@pytest.mark.asyncio
async def test_client_cannot_delete_utilization_http(api_client: AsyncClient, client_a) -> None:
    override_user(client_a)
    response = await api_client.delete(
        f"/api/v1/utilization/{uuid4()}",
        headers={"Authorization": "Bearer test-token"},
    )
    assert response.status_code == 403


@pytest.mark.asyncio
async def test_leadership_cannot_create_utilization_http(api_client: AsyncClient) -> None:
    override_user(
        CurrentUser(
            id=uuid4(),
            org_id=ORG_A,
            email="lead@example.com",
            role=AppRole.BSG_LEADERSHIP,
            is_active=True,
        )
    )
    response = await api_client.post(
        f"/api/v1/projects/{uuid4()}/utilization",
        json={
            "snapshot_date": "2026-06-01",
            "allocated_hours": "30",
            "available_hours": "40",
        },
        headers={"Authorization": "Bearer test-token"},
    )
    assert response.status_code == 403


@pytest.mark.asyncio
async def test_leadership_cannot_update_utilization_http(api_client: AsyncClient) -> None:
    override_user(
        CurrentUser(
            id=uuid4(),
            org_id=ORG_A,
            email="lead@example.com",
            role=AppRole.BSG_LEADERSHIP,
            is_active=True,
        )
    )
    response = await api_client.patch(
        f"/api/v1/utilization/{uuid4()}",
        json={"allocated_hours": "20"},
        headers={"Authorization": "Bearer test-token"},
    )
    assert response.status_code == 403
