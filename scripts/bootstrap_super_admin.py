#!/usr/bin/env python3
"""Bootstrap the first super_admin user in Supabase Auth and public.users."""

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

from app.db.models import AppRole, Organisation, User  # noqa: E402


def _async_database_url() -> str:
    url = os.environ["DATABASE_URL"]
    if url.startswith("postgresql://"):
        return url.replace("postgresql://", "postgresql+asyncpg://", 1)
    return url


async def create_auth_user(email: str, password: str) -> dict:
    base = os.environ["SUPABASE_URL"].rstrip("/")
    service_key = os.environ["SUPABASE_SERVICE_ROLE_KEY"]
    async with httpx.AsyncClient(timeout=30.0) as client:
        response = await client.post(
            f"{base}/auth/v1/admin/users",
            headers={
                "apikey": service_key,
                "Authorization": f"Bearer {service_key}",
            },
            json={"email": email, "password": password, "email_confirm": True},
        )
        response.raise_for_status()
        return response.json()


async def bootstrap(email: str, password: str, full_name: str, org_name: str) -> None:
    engine = create_async_engine(_async_database_url())
    session_factory = async_sessionmaker(engine, expire_on_commit=False)

    auth_user = await create_auth_user(email, password)
    user_id = uuid.UUID(str(auth_user["id"]))

    async with session_factory() as session:
        org = (
            await session.execute(
                select(Organisation).where(Organisation.name == org_name, Organisation.deleted_at.is_(None))
            )
        ).scalar_one_or_none()
        if org is None:
            slug = org_name.lower().replace(" ", "-")
            org = Organisation(
                name=org_name,
                slug=slug,
                vertical="platform",
                region="global",
                is_active=True,
            )
            session.add(org)
            await session.flush()

        existing = await session.get(User, user_id)
        if existing:
            existing.email = email
            existing.full_name = full_name
            existing.role = AppRole.SUPER_ADMIN
            existing.org_id = org.id
            existing.is_active = True
            existing.deleted_at = None
        else:
            session.add(
                User(
                    id=user_id,
                    org_id=org.id,
                    email=email,
                    full_name=full_name,
                    role=AppRole.SUPER_ADMIN,
                    is_active=True,
                )
            )
        await session.commit()

    await engine.dispose()
    print(f"Super admin ready: {email}")
    print(f"User id: {user_id}")
    print(f"Organisation: {org_name}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Bootstrap a super_admin user")
    parser.add_argument("--email", required=True)
    parser.add_argument("--password", required=True)
    parser.add_argument("--full-name", default="Platform Admin")
    parser.add_argument("--org-name", default="BSG Platform")
    args = parser.parse_args()
    asyncio.run(bootstrap(args.email, args.password, args.full_name, args.org_name))


if __name__ == "__main__":
    main()
