#!/usr/bin/env python3
"""Create idempotent dev login accounts in Supabase Auth and public.users."""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
import uuid
from pathlib import Path

import httpx
from dotenv import load_dotenv
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "backend"))

load_dotenv(REPO_ROOT / ".env")
load_dotenv(REPO_ROOT / "backend" / ".env")

from app.db.models import AppRole, Organisation, Project, ProjectAssignment, User  # noqa: E402

DEV_PASSWORD = "bsg-dev-2026"

BSG_ORG = {
    "org_slug": "bsg",
    "org_name": "BSG",
    "org_vertical": "platform",
    "org_region": "global",
}

TTL_ORG = {
    "org_slug": "ttl-tax-tech-lab",
    "org_name": "TTL - Tax Tech Lab",
    "org_vertical": "tax_tech",
    "org_region": "europe",
}


def _email_from_name(full_name: str) -> str:
    parts = [p for p in full_name.strip().lower().split() if p]
    local = ".".join(parts) if parts else "user"
    return f"{local}@bsg.dev"


def _team_user(
    full_name: str,
    role: AppRole,
    org: dict,
    *,
    email: str | None = None,
    assign_all_org_projects: bool = False,
) -> dict:
    spec: dict = {
        "email": email or _email_from_name(full_name),
        "password": DEV_PASSWORD,
        "full_name": full_name,
        "role": role,
        **org,
    }
    if assign_all_org_projects:
        spec["assign_all_org_projects"] = True
    return spec


DEV_USERS = [
    {
        "id": uuid.UUID("a0000001-0001-4001-8001-000000000001"),
        "email": "admin@bsg.dev",
        "password": DEV_PASSWORD,
        "full_name": "Admin",
        "role": AppRole.SUPER_ADMIN,
        **BSG_ORG,
    },
    {
        "id": uuid.UUID("a0000001-0001-4001-8001-000000000002"),
        "email": "pm@bsg.dev",
        "password": DEV_PASSWORD,
        "full_name": "PM",
        "role": AppRole.DELIVERY_MANAGER,
        **BSG_ORG,
    },
    {
        "id": uuid.UUID("a0000001-0001-4001-8001-000000000003"),
        "email": "client@bsg.dev",
        "password": DEV_PASSWORD,
        "full_name": "Client",
        "role": AppRole.CLIENT,
        **TTL_ORG,
        # Clients only see projects (and sent reports) they are assigned to under RLS.
        "assign_all_org_projects": True,
    },
]
# Team roster: AI Devs = delivery_manager; named roles as specified.
TEAM_USERS = [
    # AI Devs
    *[_team_user(name, AppRole.DELIVERY_MANAGER, BSG_ORG) for name in [
        "Laida Abazi",
        "Anda Rexhepi",
        "Alisa Grajceveci",
        "Den Hyseni",
        "Lind Geci",
        "Vesa Susuri",
        "Lum Meta",
        "Florent Sahiti",
        "Erijon Peci",
        "Erza Haziri",
        "Adea Piperku",
        "Roni Shabani",
        "Sara Ademi",
        "Diellze Salihu",
        "Erjon Karaca",
    ]],
    # PM
    _team_user("Arbios Kastrati", AppRole.DELIVERY_MANAGER, BSG_ORG),
    # Client
    _team_user(
        "TTL",
        AppRole.CLIENT,
        TTL_ORG,
        email="ttl@bsg.dev",
        assign_all_org_projects=True,
    ),
    # Admin (BSG Leadership)
    _team_user(
        "BSG Leadership",
        AppRole.SUPER_ADMIN,
        BSG_ORG,
        email="leadership@bsg.dev",
    ),
]

ALL_USERS = [*DEV_USERS, *TEAM_USERS]


def _async_database_url() -> str:
    url = os.environ["DATABASE_URL"]
    if url.startswith("postgresql://"):
        return url.replace("postgresql://", "postgresql+asyncpg://", 1)
    return url


def _engine_connect_args(database_url: str) -> dict:
    """Match app DB settings so PgBouncer transaction mode works."""
    import ssl
    from uuid import uuid4

    host_markers = ("supabase.co", "pooler.supabase.com")
    if not any(marker in database_url for marker in host_markers):
        return {}

    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    connect_args: dict = {"ssl": ctx}

    if ":6543/" in database_url or ":6543?" in database_url:
        connect_args["statement_cache_size"] = 0
        connect_args["prepared_statement_cache_size"] = 0
        connect_args["prepared_statement_name_func"] = lambda: f"__asyncpg_{uuid4()}__"
    return connect_args


def _auth_headers() -> dict[str, str]:
    service_key = os.environ["SUPABASE_SERVICE_ROLE_KEY"]
    return {
        "apikey": service_key,
        "Authorization": f"Bearer {service_key}",
    }


async def find_auth_user_id(client: httpx.AsyncClient, base: str, email: str) -> uuid.UUID | None:
    headers = _auth_headers()
    email_lower = email.lower()
    page = 1
    while True:
        response = await client.get(
            f"{base}/auth/v1/admin/users",
            headers=headers,
            params={"page": page, "per_page": 200},
        )
        response.raise_for_status()
        users = response.json().get("users", [])
        for user in users:
            if str(user.get("email", "")).lower() == email_lower:
                return uuid.UUID(str(user["id"]))
        if not users or len(users) < 200:
            return None
        page += 1


async def ensure_auth_user(client: httpx.AsyncClient, base: str, spec: dict) -> uuid.UUID:
    headers = _auth_headers()
    existing_id = await find_auth_user_id(client, base, spec["email"])
    if existing_id is not None:
        update_response = await client.put(
            f"{base}/auth/v1/admin/users/{existing_id}",
            headers=headers,
            json={"password": spec["password"], "email_confirm": True},
        )
        update_response.raise_for_status()
        return existing_id

    create_response = await client.post(
        f"{base}/auth/v1/admin/users",
        headers=headers,
        json={
            "email": spec["email"],
            "password": spec["password"],
            "email_confirm": True,
            "user_metadata": {"full_name": spec["full_name"]},
        },
    )
    create_response.raise_for_status()
    return uuid.UUID(str(create_response.json()["id"]))


async def ensure_org(session: AsyncSession, spec: dict) -> Organisation:
    org = (
        await session.execute(
            select(Organisation).where(
                Organisation.slug == spec["org_slug"],
                Organisation.deleted_at.is_(None),
            )
        )
    ).scalar_one_or_none()
    if org is not None:
        return org

    org = Organisation(
        name=spec["org_name"],
        slug=spec["org_slug"],
        vertical=spec["org_vertical"],
        region=spec["org_region"],
        is_active=True,
    )
    session.add(org)
    await session.flush()
    return org


async def upsert_app_user(session: AsyncSession, auth_user_id: uuid.UUID, org: Organisation, spec: dict) -> User:
    by_auth = await session.get(User, auth_user_id)
    by_email = (
        await session.execute(select(User).where(User.email == spec["email"]))
    ).scalar_one_or_none()

    if by_email is not None and by_email.id != auth_user_id:
        await session.delete(by_email)
        await session.flush()

    user = by_auth
    if user is None:
        user = User(
            id=auth_user_id,
            org_id=org.id,
            email=spec["email"],
            full_name=spec["full_name"],
            role=spec["role"],
            is_active=True,
        )
        session.add(user)
        await session.flush()
        return user

    user.org_id = org.id
    user.email = spec["email"]
    user.full_name = spec["full_name"]
    user.role = spec["role"]
    user.is_active = True
    user.deleted_at = None
    await session.flush()
    return user


async def ensure_client_project_assignments(
    session: AsyncSession,
    *,
    user: User,
    org: Organisation,
) -> int:
    """Assign the client to every active project in their org (idempotent).

    Without project_assignments, RLS hides projects and sent reports from clients
    even when they share the same org_id as the PM who sent them.
    """
    projects = (
        await session.execute(
            select(Project).where(
                Project.org_id == org.id,
                Project.deleted_at.is_(None),
            )
        )
    ).scalars().all()

    created = 0
    for project in projects:
        existing = (
            await session.execute(
                select(ProjectAssignment).where(
                    ProjectAssignment.user_id == user.id,
                    ProjectAssignment.project_id == project.id,
                )
            )
        ).scalar_one_or_none()
        if existing is None:
            session.add(
                ProjectAssignment(
                    user_id=user.id,
                    project_id=project.id,
                    org_id=org.id,
                    is_active=True,
                )
            )
            created += 1
            continue
        existing.is_active = True
        existing.deleted_at = None
        existing.org_id = org.id
    return created


async def seed_dev_users() -> None:
    base = os.environ["SUPABASE_URL"].rstrip("/")
    database_url = _async_database_url()
    engine = create_async_engine(
        database_url,
        connect_args=_engine_connect_args(database_url),
    )
    session_factory = async_sessionmaker(engine, expire_on_commit=False)

    async with httpx.AsyncClient(timeout=30.0) as client:
        for spec in ALL_USERS:
            auth_user_id = await ensure_auth_user(client, base, spec)
            async with session_factory() as session:
                org = await ensure_org(session, spec)
                user = await upsert_app_user(session, auth_user_id, org, spec)
                assigned = 0
                if spec.get("assign_all_org_projects") and spec["role"] == AppRole.CLIENT:
                    assigned = await ensure_client_project_assignments(
                        session, user=user, org=org
                    )
                await session.commit()
            suffix = f"  (+{assigned} project assignments)" if assigned else ""
            print(
                f"{spec['role'].value:18} {spec['email']:40}  "
                f"{spec['full_name']}{suffix}"
            )

    await engine.dispose()
    print(f"\n{len(ALL_USERS)} accounts ready. Shared password: {DEV_PASSWORD}")
    print(
        "Note: client accounts must be assigned to projects to see sent reports "
        "(this script assigns all org projects when configured)."
    )

def main() -> None:
    parser = argparse.ArgumentParser(description="Seed dev login accounts for local development")
    parser.parse_args()
    asyncio.run(seed_dev_users())


if __name__ == "__main__":
    main()
