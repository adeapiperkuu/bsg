from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any
from uuid import UUID, uuid4

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import CurrentUser, get_current_user
from app.db.models import AppRole
from app.db.session import get_db_session
from app.main import app

ORG_A = uuid4()
ORG_B = uuid4()
USER_CLIENT_A = uuid4()
USER_SUPER = uuid4()


class FakeScalars:
    def __init__(self, items: list[Any] | None = None) -> None:
        self._items = items or []

    def all(self) -> list[Any]:
        return self._items

    def __iter__(self):
        return iter(self._items)


class FakeResult:
    def __init__(self, value: Any = None, items: list[Any] | None = None) -> None:
        self._value = value
        self._items = items or []

    def scalar_one_or_none(self) -> Any:
        return self._value

    def scalars(self) -> FakeScalars:
        return FakeScalars(self._items)


class FakeSession:
    """Minimal async session for HTTP tests; returns empty / not-found DB results."""

    def add(self, *_args: Any, **_kwargs: Any) -> None:
        return None

    async def execute(self, *_args: Any, **_kwargs: Any) -> FakeResult:
        return FakeResult()

    async def commit(self) -> None:
        return None

    async def refresh(self, *_args: Any, **_kwargs: Any) -> None:
        return None

    async def flush(self) -> None:
        return None


@pytest.fixture
def client_a() -> CurrentUser:
    return CurrentUser(
        id=USER_CLIENT_A,
        org_id=ORG_A,
        email="client-a@example.com",
        role=AppRole.CLIENT,
        is_active=True,
    )


@pytest.fixture
def super_admin() -> CurrentUser:
    return CurrentUser(
        id=USER_SUPER,
        org_id=ORG_A,
        email="admin@example.com",
        role=AppRole.SUPER_ADMIN,
        is_active=True,
    )


@pytest.fixture
def delivery_manager() -> CurrentUser:
    return CurrentUser(
        id=uuid4(),
        org_id=ORG_A,
        email="dm@example.com",
        role=AppRole.DELIVERY_MANAGER,
        is_active=True,
    )


async def _override_session() -> AsyncIterator[AsyncSession]:
    yield FakeSession()  # type: ignore[misc]


@pytest.fixture
async def api_client() -> AsyncIterator[AsyncClient]:
    app.dependency_overrides[get_db_session] = _override_session
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        yield client


def override_user(user: CurrentUser):
    async def _dep() -> CurrentUser:
        return user

    app.dependency_overrides[get_current_user] = _dep


def clear_overrides() -> None:
    app.dependency_overrides.clear()


@pytest.fixture(autouse=True)
def _cleanup_overrides() -> AsyncIterator[None]:
    yield
    clear_overrides()
