#!/usr/bin/env python3
"""Seed programs (UI Projects), scopes/sprints, and teammate assignments."""

from __future__ import annotations

import asyncio
import os
import ssl
import sys
from datetime import date, timedelta
from pathlib import Path
from uuid import uuid4

from dotenv import load_dotenv
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "backend"))

load_dotenv(REPO_ROOT / ".env")
load_dotenv(REPO_ROOT / "backend" / ".env")

from app.db.models import (  # noqa: E402
    AppRole,
    DeliverySite,
    Organisation,
    Program,
    Project,
    ProjectAssignment,
    ProjectStatus,
    Team,
    User,
)

# Corrected display names from the roster request.
# Internal programs live under BSG; each product/client program has its own org.
PROGRAMS: list[dict] = [
    {
        "name": "AI Driven Operational Intelligence",
        "org_slug": "bsg",
        "vertical": "operations_intelligence",
        "description": "Portfolio operational intelligence and delivery insights.",
    },
    {
        "name": "Intelligent Systems",
        "org_slug": "bsg",
        "vertical": "intelligent_systems",
        "description": "Core intelligent systems platform workstreams.",
    },
    {
        "name": "CV Convertor Agent",
        "org_slug": "cv-convertor-agent",
        "vertical": "computer_vision",
        "description": "CV conversion agent delivery scopes.",
    },
    {
        "name": "Job Description Agent",
        "org_slug": "job-description-agent",
        "vertical": "nlp_annotation",
        "description": "Job description generation and review agent.",
    },
    {
        "name": "TestFlow AI",
        "org_slug": "testflow-ai",
        "vertical": "qa_automation",
        "description": "AI-assisted test flow automation.",
    },
    {
        "name": "Sustainability Agent",
        "org_slug": "sustainability-agent",
        "vertical": "sustainability",
        "description": "Sustainability reporting and insights agent.",
    },
    {
        "name": "PDF Extractor Platform",
        "org_slug": "pdf-extractor-platform",
        "vertical": "document_ai",
        "description": "PDF extraction and structuring platform.",
    },
    {
        "name": "AI Support Agent",
        "org_slug": "ai-support-agent",
        "vertical": "support_ai",
        "description": "Customer and ops support agent.",
    },
    {
        "name": "Leadership AI",
        "org_slug": "bsg",
        "vertical": "leadership_analytics",
        "description": "Leadership cockpit AI and analytics.",
    },
    {
        "name": "TTL - Tax Tech Lab",
        "org_slug": "ttl-tax-tech-lab",
        "vertical": "tax_tech",
        "description": "Tax Tech Lab client delivery program.",
    },
    {
        "name": "TrailGuide",
        "org_slug": "trailguide",
        "vertical": "travel_ai",
        "description": "TrailGuide product delivery.",
    },
    {
        "name": "StayGuide",
        "org_slug": "stayguide",
        "vertical": "travel_ai",
        "description": "StayGuide product delivery.",
    },
    {
        "name": "BOE - Operational Excellence",
        "org_slug": "bsg",
        "vertical": "operational_excellence",
        "description": "Business operational excellence program.",
    },
    {
        "name": "Storyboom.ai",
        "org_slug": "storyboom-ai",
        "vertical": "content_ai",
        "description": "Storyboom.ai content generation platform.",
    },
    {
        "name": "Order Entry Agent",
        "org_slug": "order-entry-agent",
        "vertical": "order_automation",
        "description": "Order entry automation agent.",
    },
]

# AI Devs + PM rotate across BSG programs; TTL client joins TTL scopes.
AI_DEV_EMAILS = [
    "laida.abazi@bsg.dev",
    "anda.rexhepi@bsg.dev",
    "alisa.grajceveci@bsg.dev",
    "den.hyseni@bsg.dev",
    "lind.geci@bsg.dev",
    "vesa.susuri@bsg.dev",
    "lum.meta@bsg.dev",
    "florent.sahiti@bsg.dev",
    "erijon.peci@bsg.dev",
    "erza.haziri@bsg.dev",
    "adea.piperku@bsg.dev",
    "roni.shabani@bsg.dev",
    "sara.ademi@bsg.dev",
    "diellze.salihu@bsg.dev",
    "erjon.karaca@bsg.dev",
]
PM_EMAIL = "arbios.kastrati@bsg.dev"
TTL_CLIENT_EMAIL = "ttl@bsg.dev"
LEADERSHIP_EMAIL = "leadership@bsg.dev"

SCOPE_TEMPLATES = [
    ("Sprint 1 — Discovery", ProjectStatus.COMPLETED, -90, -30, 120),
    ("Sprint 2 — Build", ProjectStatus.ACTIVE, -30, 60, 180),
    ("Sprint 3 — Harden", ProjectStatus.RAMPING, 60, 120, 150),
]


def _async_database_url() -> str:
    url = os.environ["DATABASE_URL"]
    if url.startswith("postgresql://"):
        return url.replace("postgresql://", "postgresql+asyncpg://", 1)
    return url


def _engine_connect_args(database_url: str) -> dict:
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


async def get_org(session: AsyncSession, slug: str) -> Organisation:
    org = (
        await session.execute(
            select(Organisation).where(
                Organisation.slug == slug,
                Organisation.deleted_at.is_(None),
            )
        )
    ).scalar_one_or_none()
    if org is None:
        raise SystemExit(f"Organisation slug={slug!r} not found. Seed users/orgs first.")
    return org


async def get_users_by_email(session: AsyncSession, emails: list[str]) -> dict[str, User]:
    rows = (
        await session.execute(select(User).where(User.email.in_(emails), User.deleted_at.is_(None)))
    ).scalars().all()
    by_email = {u.email.lower(): u for u in rows}
    missing = [e for e in emails if e.lower() not in by_email]
    if missing:
        raise SystemExit(f"Missing users (seed them first): {', '.join(missing)}")
    return by_email


async def ensure_program(session: AsyncSession, org: Organisation, spec: dict) -> Program:
    existing = (
        await session.execute(
            select(Program).where(
                Program.org_id == org.id,
                Program.name == spec["name"],
                Program.deleted_at.is_(None),
            )
        )
    ).scalar_one_or_none()
    if existing is not None:
        existing.description = spec["description"]
        return existing

    program = Program(
        org_id=org.id,
        name=spec["name"],
        description=spec["description"],
    )
    session.add(program)
    await session.flush()
    return program


async def ensure_scope(
    session: AsyncSession,
    *,
    org: Organisation,
    program: Program,
    name: str,
    vertical: str,
    status: ProjectStatus,
    start: date,
    end: date,
    daily_target: int,
) -> Project:
    existing = (
        await session.execute(
            select(Project).where(
                Project.org_id == org.id,
                Project.program_id == program.id,
                Project.name == name,
                Project.deleted_at.is_(None),
            )
        )
    ).scalar_one_or_none()
    if existing is not None:
        existing.status = status
        existing.start_date = start
        existing.target_end_date = end
        existing.daily_target_units = daily_target
        existing.vertical = vertical
        return existing

    scope = Project(
        org_id=org.id,
        program_id=program.id,
        name=name,
        description=f"{program.name} — {name}",
        vertical=vertical,
        status=status,
        start_date=start,
        target_end_date=end,
        actual_end_date=end if status == ProjectStatus.COMPLETED else None,
        daily_target_units=daily_target,
    )
    session.add(scope)
    await session.flush()
    return scope


async def ensure_assignment(
    session: AsyncSession,
    *,
    user: User,
    project: Project,
    org: Organisation,
) -> bool:
    existing = (
        await session.execute(
            select(ProjectAssignment).where(
                ProjectAssignment.user_id == user.id,
                ProjectAssignment.project_id == project.id,
            )
        )
    ).scalar_one_or_none()
    if existing is not None:
        existing.is_active = True
        existing.deleted_at = None
        existing.org_id = org.id
        return False

    session.add(
        ProjectAssignment(
            user_id=user.id,
            project_id=project.id,
            org_id=org.id,
            is_active=True,
        )
    )
    return True


async def ensure_team(
    session: AsyncSession,
    *,
    org: Organisation,
    project: Project,
    name: str,
) -> Team:
    existing = (
        await session.execute(
            select(Team).where(
                Team.project_id == project.id,
                Team.name == name,
                Team.deleted_at.is_(None),
            )
        )
    ).scalar_one_or_none()
    if existing is not None:
        existing.is_active = True
        return existing

    team = Team(
        project_id=project.id,
        org_id=org.id,
        name=name,
        site=DeliverySite.KOSOVO,
        domain=project.vertical,
        is_active=True,
    )
    session.add(team)
    await session.flush()
    return team


def teammate_emails_for(program_name: str, org_slug: str, roster: list[str], index: int) -> list[str]:
    """Pick a stable mix of AI Devs per program; always include PM; TTL gets client."""
    emails: list[str] = [PM_EMAIL]
    # 4 AI Devs rotating so coverage is spread across the portfolio.
    start = (index * 4) % len(roster)
    for offset in range(4):
        emails.append(roster[(start + offset) % len(roster)])

    if org_slug in {"ttl", "ttl-tax-tech-lab"}:
        emails.append(TTL_CLIENT_EMAIL)
    if program_name == "Leadership AI":
        emails.append(LEADERSHIP_EMAIL)

    # Dedupe while preserving order.
    seen: set[str] = set()
    ordered: list[str] = []
    for email in emails:
        key = email.lower()
        if key not in seen:
            seen.add(key)
            ordered.append(email)
    return ordered


async def seed() -> None:
    database_url = _async_database_url()
    engine = create_async_engine(
        database_url,
        connect_args=_engine_connect_args(database_url),
    )
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    today = date.today()

    needed_emails = sorted(
        {
            *AI_DEV_EMAILS,
            PM_EMAIL,
            TTL_CLIENT_EMAIL,
            LEADERSHIP_EMAIL,
        }
    )

    async with session_factory() as session:
        users = await get_users_by_email(session, needed_emails)
        orgs: dict[str, Organisation] = {}
        for slug in {p["org_slug"] for p in PROGRAMS}:
            orgs[slug] = await get_org(session, slug)

        created_programs = 0
        created_scopes = 0
        created_assignments = 0
        created_teams = 0

        for index, spec in enumerate(PROGRAMS):
            org = orgs[spec["org_slug"]]
            existing_program = (
                await session.execute(
                    select(Program.id).where(
                        Program.org_id == org.id,
                        Program.name == spec["name"],
                        Program.deleted_at.is_(None),
                    )
                )
            ).scalar_one_or_none()
            program = await ensure_program(session, org, spec)
            if existing_program is None:
                created_programs += 1

            teammate_emails = teammate_emails_for(
                spec["name"], spec["org_slug"], AI_DEV_EMAILS, index
            )
            teammates = [users[e.lower()] for e in teammate_emails]

            for scope_name, status, start_offset, end_offset, daily_target in SCOPE_TEMPLATES:
                full_scope_name = scope_name
                existing_before = (
                    await session.execute(
                        select(Project.id).where(
                            Project.org_id == org.id,
                            Project.program_id == program.id,
                            Project.name == full_scope_name,
                            Project.deleted_at.is_(None),
                        )
                    )
                ).scalar_one_or_none()

                scope = await ensure_scope(
                    session,
                    org=org,
                    program=program,
                    name=full_scope_name,
                    vertical=spec["vertical"],
                    status=status,
                    start=today + timedelta(days=start_offset),
                    end=today + timedelta(days=end_offset),
                    daily_target=daily_target,
                )
                if existing_before is None:
                    created_scopes += 1

                for user in teammates:
                    if await ensure_assignment(session, user=user, project=scope, org=org):
                        created_assignments += 1

                team_before = (
                    await session.execute(
                        select(Team.id).where(
                            Team.project_id == scope.id,
                            Team.name == "Kosovo Delivery",
                            Team.deleted_at.is_(None),
                        )
                    )
                ).scalar_one_or_none()
                await ensure_team(
                    session,
                    org=org,
                    project=scope,
                    name="Kosovo Delivery",
                )
                if team_before is None:
                    created_teams += 1

            print(
                f"{spec['name']:40}  org={spec['org_slug']:14}  "
                f"teammates={len(teammates)}  scopes={len(SCOPE_TEMPLATES)}"
            )

        await session.commit()

    await engine.dispose()
    print(
        f"\nDone. new programs={created_programs}, scopes={created_scopes}, "
        f"assignments={created_assignments}, teams={created_teams}."
    )
    print(f"Total programs: {len(PROGRAMS)}; scopes each: {len(SCOPE_TEMPLATES)}.")


if __name__ == "__main__":
    asyncio.run(seed())
