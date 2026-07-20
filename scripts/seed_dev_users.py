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

DEV_USERS = [
    {
        "id": uuid.UUID("a0000001-0001-4001-8001-000000000001"),
        "email": "admin@bsg.dev",
        "password": DEV_PASSWORD,
        "full_name": "Dev Admin",
        "role": AppRole.SUPER_ADMIN,
        "org_slug": "bsg-platform",
        "org_name": "BSG Platform",
        "org_vertical": "platform",
        "org_region": "global",
    },
    {
        "id": uuid.UUID("a0000001-0001-4001-8001-000000000002"),
        "email": "pm@bsg.dev",
        "password": DEV_PASSWORD,
        "full_name": "Dev PM",
        "role": AppRole.DELIVERY_MANAGER,
        "org_slug": "northwind-analytics",
        "org_name": "Northwind Analytics",
        "org_vertical": "retail",
        "org_region": "north_america",
    },
    {
        "id": uuid.UUID("a0000001-0001-4001-8001-000000000003"),
        "email": "client@bsg.dev",
        "password": DEV_PASSWORD,
        "full_name": "Dev Client",
        "role": AppRole.CLIENT,
        "org_slug": "northwind-analytics",
        "org_name": "Northwind Analytics",
        "org_vertical": "retail",
        "org_region": "north_america",
        # Clients only see projects (and sent reports) they are assigned to under RLS.
        "assign_all_org_projects": True,
    },
]


def _async_database_url() -> str:
    url = os.environ["DATABASE_URL"]
    if url.startswith("postgresql://"):
        return url.replace("postgresql://", "postgresql+asyncpg://", 1)
    return url


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
    engine = create_async_engine(_async_database_url())
    session_factory = async_sessionmaker(engine, expire_on_commit=False)

    async with httpx.AsyncClient(timeout=30.0) as client:
        for spec in DEV_USERS:
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
                f"{spec['role'].value:18} {spec['email']}  "
                f"(password: {spec['password']}){suffix}"
            )

    await engine.dispose()
    print("\nDev users ready. Use these on the login page in local development.")
    print(
        "Note: client@bsg.dev must be assigned to projects to see sent reports "
        "(this script assigns all Northwind projects)."
    )

def main() -> None:
    parser = argparse.ArgumentParser(description="Seed dev login accounts for local development")
    parser.parse_args()
    asyncio.run(seed_dev_users())


if __name__ == "__main__":
    main()
