"""Tests for GET /api/v1/communications — org-scoped lightweight PM inbox list."""

from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace
from typing import Any
from uuid import uuid4

import pytest
from httpx import AsyncClient
from sqlalchemy.dialects import postgresql

from app.core.security import CurrentUser, get_current_user
from app.db.models import AppRole, CommunicationStatus, CommunicationType
from app.db.session import get_db_session
from app.main import app
from app.schemas.domain import CommunicationListItem
from app.services.communications import (
    COMMUNICATIONS_LIST_MAX_LIMIT,
    bound_communications_list_limit,
    bound_communications_list_offset,
    build_communications_list_count_stmt,
    build_communications_list_stmt,
    list_org_communications,
)
from tests.conftest import ORG_A, ORG_B, client_a, delivery_manager, override_user, super_admin


@pytest.fixture
def bsg_leadership() -> CurrentUser:
    return CurrentUser(
        id=uuid4(),
        org_id=ORG_A,
        email="leadership@example.com",
        role=AppRole.BSG_LEADERSHIP,
        is_active=True,
    )


@pytest.fixture
def delivery_manager_org_b() -> CurrentUser:
    return CurrentUser(
        id=uuid4(),
        org_id=ORG_B,
        email="dm-b@example.com",
        role=AppRole.DELIVERY_MANAGER,
        is_active=True,
    )


class _ListFakeResult:
    def __init__(self, *, rows: list[Any] | None = None, scalar: Any = None) -> None:
        self._rows = rows or []
        self._scalar = scalar

    def all(self) -> list[Any]:
        return list(self._rows)

    def scalar_one_or_none(self) -> Any:
        return self._scalar

    def scalars(self) -> Any:
        return SimpleNamespace(all=lambda: self._rows)


class _ListFakeSession:
    """Records execute calls and returns scripted list/count results."""

    def __init__(self, *, rows: list[Any] | None = None, total: int = 0) -> None:
        self.rows = rows or []
        self.total = total
        self.statements: list[Any] = []

    async def execute(self, stmt: Any, *_args: Any, **_kwargs: Any) -> _ListFakeResult:
        self.statements.append(stmt)
        compiled = str(stmt.compile(compile_kwargs={"literal_binds": False}))
        # Count queries select a single aggregate; list queries select many columns.
        if "count(" in compiled.lower() and "evidence_link_count" not in compiled.lower():
            return _ListFakeResult(scalar=self.total)
        return _ListFakeResult(rows=self.rows)


def _compile(stmt: Any) -> str:
    return str(
        stmt.compile(
            dialect=postgresql.dialect(),
            compile_kwargs={"literal_binds": False},
        )
    ).lower()


def _sample_row(
    *,
    org_id=ORG_A,
    status: CommunicationStatus = CommunicationStatus.DRAFT,
    project_id=None,
    created_at: datetime | None = None,
    evidence_link_count: int = 2,
):
    pid = project_id or uuid4()
    return SimpleNamespace(
        id=uuid4(),
        project_id=pid,
        project_name="Project Alpha",
        org_id=org_id,
        org_name="Org Alpha",
        comm_type=CommunicationType.WEEKLY_SUMMARY,
        subject="Weekly Delivery Summary — Project Alpha",
        status=status,
        created_at=created_at or datetime(2026, 7, 16, 12, 0, tzinfo=timezone.utc),
        updated_at=datetime(2026, 7, 16, 12, 30, tzinfo=timezone.utc),
        sent_at=None,
        evidence_link_count=evidence_link_count,
        body_draft="SECRET DRAFT BODY",
        body_approved="SECRET APPROVED BODY",
    )


# --- Pagination bounds -----------------------------------------------------------------


def test_communications_list_limit_bounds() -> None:
    assert bound_communications_list_limit(None) == 30
    assert bound_communications_list_limit(0) == 1
    assert bound_communications_list_limit(30) == 30
    assert bound_communications_list_limit(500) == COMMUNICATIONS_LIST_MAX_LIMIT
    assert bound_communications_list_offset(None) == 0
    assert bound_communications_list_offset(-5) == 0
    assert bound_communications_list_offset(10) == 10


# --- Query shape / SQL -----------------------------------------------------------------


def test_list_stmt_joins_project_and_evidence_counts(delivery_manager) -> None:
    sql = _compile(build_communications_list_stmt(delivery_manager))
    assert "client_communications" in sql
    assert "projects" in sql
    assert "programs" in sql
    assert "organisations" in sql
    assert "project_name" in sql or "projects.name" in sql
    assert "program_name" in sql or "programs.name" in sql
    assert "communication_evidence_links" in sql
    assert "evidence_link_count" in sql
    assert "body_draft" not in sql
    assert "body_approved" not in sql
    assert "order by" in sql
    assert "created_at" in sql
    assert "org_id" in sql


def test_list_stmt_super_admin_skips_org_filter(super_admin) -> None:
    sql = _compile(build_communications_list_stmt(super_admin))
    # Super admin may still join projects; org equality filter should be absent.
    assert "client_communications.org_id" not in sql.replace(" ", "")


def test_list_stmt_applies_status_and_project_filters(delivery_manager) -> None:
    project_id = uuid4()
    sql = _compile(
        build_communications_list_stmt(
            delivery_manager,
            status=CommunicationStatus.IN_REVIEW,
            project_id=project_id,
            limit=10,
            offset=5,
        )
    )
    assert "status" in sql
    assert "project_id" in sql
    assert "limit" in sql
    assert "offset" in sql


def test_count_stmt_excludes_evidence_join(delivery_manager) -> None:
    sql = _compile(build_communications_list_count_stmt(delivery_manager))
    assert "count(" in sql
    assert "communication_evidence_links" not in sql
    assert "body_draft" not in sql


# --- Service behavior -----------------------------------------------------------------


@pytest.mark.asyncio
async def test_list_org_communications_query_count_bounded(delivery_manager) -> None:
    row = _sample_row()
    session = _ListFakeSession(rows=[row], total=1)
    page = await list_org_communications(session, delivery_manager, limit=30, offset=0)
    assert len(session.statements) == 2
    assert len(page.items) == 1
    assert page.total == 1
    assert page.items[0].project_name == "Project Alpha"
    assert page.items[0].evidence_link_count == 2


@pytest.mark.asyncio
async def test_list_org_communications_response_excludes_bodies(delivery_manager) -> None:
    row = _sample_row(evidence_link_count=4)
    session = _ListFakeSession(rows=[row], total=1)
    page = await list_org_communications(session, delivery_manager)
    item = page.items[0]
    dumped = item.model_dump()
    assert "body_draft" not in dumped
    assert "body_approved" not in dumped
    assert "evidence_links" not in dumped
    assert dumped["evidence_link_count"] == 4
    assert dumped["project_name"] == "Project Alpha"
    # Ensure schema class itself has no body fields.
    assert "body_draft" not in CommunicationListItem.model_fields
    assert "body_approved" not in CommunicationListItem.model_fields


@pytest.mark.asyncio
async def test_list_org_communications_rejects_client(client_a) -> None:
    from app.core.exceptions import ApiError

    session = _ListFakeSession()
    with pytest.raises(ApiError) as exc_info:
        await list_org_communications(session, client_a)
    assert exc_info.value.status_code == 403
    assert exc_info.value.code == "FORBIDDEN"


def test_list_stmt_stable_newest_first_ordering(delivery_manager) -> None:
    sql = _compile(build_communications_list_stmt(delivery_manager))
    # created_at DESC, id DESC
    assert "order by" in sql
    created_pos = sql.index("created_at")
    id_pos = sql.rindex("id")
    assert created_pos < id_pos
    assert "desc" in sql[created_pos : id_pos + 20]


@pytest.mark.asyncio
async def test_project_filter_applies_when_project_visible(delivery_manager) -> None:
    """Visibility check succeeds; list/count still two executes after project lookup."""
    project_id = uuid4()
    project = SimpleNamespace(id=project_id, org_id=ORG_A, deleted_at=None)
    row = _sample_row(project_id=project_id)

    class _SessionWithProject(_ListFakeSession):
        async def execute(self, stmt: Any, *_args: Any, **_kwargs: Any) -> _ListFakeResult:
            self.statements.append(stmt)
            compiled = str(stmt.compile(compile_kwargs={"literal_binds": False})).lower()
            if "from projects" in compiled or "from projects " in compiled.replace("\n", " "):
                # get_visible_project path
                return _ListFakeResult(scalar=project)
            if "count(" in compiled and "evidence_link_count" not in compiled:
                return _ListFakeResult(scalar=1)
            return _ListFakeResult(rows=[row])

    session = _SessionWithProject(rows=[row], total=1)
    page = await list_org_communications(
        session, delivery_manager, project_id=project_id, limit=10, offset=0
    )
    assert len(page.items) == 1
    assert page.items[0].project_id == project_id
    # 1 visibility + 1 list + 1 count
    assert len(session.statements) == 3
    list_sql = _compile(session.statements[1])
    assert "project_id" in list_sql


@pytest.mark.asyncio
async def test_delivery_manager_org_filter_in_sql(delivery_manager, delivery_manager_org_b) -> None:
    sql_a = _compile(build_communications_list_stmt(delivery_manager))
    sql_b = _compile(build_communications_list_stmt(delivery_manager_org_b))
    assert "org_id" in sql_a
    assert "org_id" in sql_b
    # Both bind their own org — statements differ by bound parameter identity via compile.
    assert sql_a  # smoke: builds cleanly for each org


@pytest.mark.asyncio
async def test_list_enforces_max_limit(delivery_manager) -> None:
    session = _ListFakeSession(rows=[], total=0)
    page = await list_org_communications(session, delivery_manager, limit=999, offset=0)
    assert page.limit == COMMUNICATIONS_LIST_MAX_LIMIT
    sql = _compile(session.statements[0])
    assert "limit" in sql


# --- HTTP authorization ----------------------------------------------------------------


@pytest.mark.asyncio
async def test_client_cannot_access_pm_communications_list(
    api_client: AsyncClient, client_a
) -> None:
    override_user(client_a)
    response = await api_client.get(
        "/api/v1/communications",
        headers={"Authorization": "Bearer test-token"},
    )
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "FORBIDDEN"


@pytest.mark.asyncio
async def test_unauthenticated_communications_list_rejected(api_client: AsyncClient) -> None:
    app.dependency_overrides.pop(get_current_user, None)
    response = await api_client.get("/api/v1/communications")
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_delivery_manager_can_list_communications(
    api_client: AsyncClient, delivery_manager
) -> None:
    row = _sample_row()
    session = _ListFakeSession(rows=[row], total=1)

    async def _session():
        yield session

    app.dependency_overrides[get_db_session] = _session
    override_user(delivery_manager)
    response = await api_client.get(
        "/api/v1/communications",
        headers={"Authorization": "Bearer test-token"},
    )
    assert response.status_code == 200
    body = response.json()
    assert len(body["data"]) == 1
    assert body["data"][0]["project_name"] == "Project Alpha"
    assert body["data"][0]["evidence_link_count"] == 2
    assert "body_draft" not in body["data"][0]
    assert "body_approved" not in body["data"][0]
    assert body["pagination"]["total"] == 1


@pytest.mark.asyncio
async def test_leadership_can_list_communications_readonly_scope(
    api_client: AsyncClient, bsg_leadership
) -> None:
    session = _ListFakeSession(rows=[], total=0)

    async def _session():
        yield session

    app.dependency_overrides[get_db_session] = _session
    override_user(bsg_leadership)
    response = await api_client.get(
        "/api/v1/communications",
        headers={"Authorization": "Bearer test-token"},
    )
    assert response.status_code == 200
    assert response.json()["data"] == []


@pytest.mark.asyncio
async def test_super_admin_can_list_communications(api_client: AsyncClient, super_admin) -> None:
    session = _ListFakeSession(rows=[], total=0)

    async def _session():
        yield session

    app.dependency_overrides[get_db_session] = _session
    override_user(super_admin)
    response = await api_client.get(
        "/api/v1/communications",
        headers={"Authorization": "Bearer test-token"},
    )
    assert response.status_code == 200


@pytest.mark.asyncio
async def test_status_filter_passed_to_query(api_client: AsyncClient, delivery_manager) -> None:
    session = _ListFakeSession(rows=[], total=0)

    async def _session():
        yield session

    app.dependency_overrides[get_db_session] = _session
    override_user(delivery_manager)
    response = await api_client.get(
        "/api/v1/communications",
        params={"status": "in_review"},
        headers={"Authorization": "Bearer test-token"},
    )
    assert response.status_code == 200
    assert len(session.statements) == 2
    sql = _compile(session.statements[0])
    assert "status" in sql


@pytest.mark.asyncio
async def test_invalid_status_returns_validation_error(
    api_client: AsyncClient, delivery_manager
) -> None:
    override_user(delivery_manager)
    response = await api_client.get(
        "/api/v1/communications",
        params={"status": "pending"},
        headers={"Authorization": "Bearer test-token"},
    )
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_limit_and_offset_query_params(api_client: AsyncClient, delivery_manager) -> None:
    session = _ListFakeSession(rows=[], total=50)

    async def _session():
        yield session

    app.dependency_overrides[get_db_session] = _session
    override_user(delivery_manager)
    response = await api_client.get(
        "/api/v1/communications",
        params={"limit": 10, "offset": 20},
        headers={"Authorization": "Bearer test-token"},
    )
    assert response.status_code == 200
    pagination = response.json()["pagination"]
    assert pagination["limit"] == 10
    assert pagination["offset"] == 20
    assert pagination["total"] == 50
    assert pagination["has_more"] is True


@pytest.mark.asyncio
async def test_maximum_limit_enforced_by_query(api_client: AsyncClient, delivery_manager) -> None:
    override_user(delivery_manager)
    response = await api_client.get(
        "/api/v1/communications",
        params={"limit": 500},
        headers={"Authorization": "Bearer test-token"},
    )
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_project_filter_query_param(api_client: AsyncClient, delivery_manager) -> None:
    """With project_id, visibility lookup runs first; FakeSession returns None → 404."""
    override_user(delivery_manager)
    response = await api_client.get(
        "/api/v1/communications",
        params={"project_id": str(uuid4())},
        headers={"Authorization": "Bearer test-token"},
    )
    # Default FakeSession from api_client fixture → project not found
    assert response.status_code == 404
