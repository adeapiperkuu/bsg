"""Catalog helpers that prefer DB metadata and fall back to the in-code registry."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID, uuid5

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.security import CurrentUser
from app.db.models import KpiDefinition, KpiDefinitionVersion
from app.kpis.contracts import RegisteredKpi
from app.kpis.evaluation import can_view_kpi, to_definition_read
from app.kpis.registry import get_kpi_registry
from app.schemas.kpi import (
    KpiDefinitionRead,
    KpiDependencyRead,
    KpiVersionRead,
)

KPI_NAMESPACE = UUID("a1000000-0000-4000-8000-000000000000")


def stable_kpi_uuid(kpi_key: str) -> UUID:
    return uuid5(KPI_NAMESPACE, kpi_key)


def stable_version_uuid(kpi_key: str, version: str) -> UUID:
    return uuid5(KPI_NAMESPACE, f"{kpi_key}@{version}")


def _with_stable_ids(definition: KpiDefinitionRead, kpi: RegisteredKpi) -> KpiDefinitionRead:
    current = definition.current_version
    if current is not None:
        current = current.model_copy(update={"id": stable_version_uuid(kpi.kpi_key, kpi.version)})
    versions = [
        item.model_copy(update={"id": stable_version_uuid(kpi.kpi_key, item.version)})
        for item in definition.versions
    ]
    return definition.model_copy(
        update={
            "id": stable_kpi_uuid(kpi.kpi_key),
            "current_version": current,
            "versions": versions,
        }
    )


def list_registry_definitions(
    current_user: CurrentUser,
    *,
    owner_agent: str | None = None,
    include_all_versions: bool = False,
) -> list[KpiDefinitionRead]:
    registry = get_kpi_registry()
    results: list[KpiDefinitionRead] = []
    for kpi in registry.list_kpis(owner_agent=owner_agent):
        if not can_view_kpi(kpi, current_user):
            continue
        results.append(
            _with_stable_ids(
                to_definition_read(kpi, include_all_versions=include_all_versions),
                kpi,
            )
        )
    return results


def get_registry_definition(
    current_user: CurrentUser,
    kpi_key: str,
    *,
    version: str | None = None,
    include_all_versions: bool = True,
) -> KpiDefinitionRead | None:
    registry = get_kpi_registry()
    kpi = registry.get(kpi_key, version)
    if kpi is None or not can_view_kpi(kpi, current_user):
        return None
    return _with_stable_ids(
        to_definition_read(kpi, include_all_versions=include_all_versions),
        kpi,
    )


async def list_kpi_definitions(
    session: AsyncSession,
    current_user: CurrentUser,
    *,
    owner_agent: str | None = None,
) -> list[KpiDefinitionRead]:
    """Return authorized KPI catalog, enriching with DB rows when present."""
    registry_defs = {
        item.kpi_key: item
        for item in list_registry_definitions(current_user, owner_agent=owner_agent)
    }
    try:
        query = (
            select(KpiDefinition)
            .where(KpiDefinition.deleted_at.is_(None), KpiDefinition.is_active.is_(True))
            .options(
                selectinload(KpiDefinition.versions).selectinload(KpiDefinitionVersion.dependencies)
            )
            .order_by(KpiDefinition.kpi_key)
        )
        if owner_agent:
            query = query.where(KpiDefinition.owner_agent == owner_agent)
        rows = (await session.execute(query)).scalars().all()
    except Exception:
        return list(registry_defs.values())

    if not rows:
        return list(registry_defs.values())

    merged: list[KpiDefinitionRead] = []
    seen: set[str] = set()
    for row in rows:
        registry_kpi = get_kpi_registry().get(row.kpi_key)
        if registry_kpi is None or not can_view_kpi(registry_kpi, current_user):
            continue
        merged.append(_definition_from_db(row, registry_kpi))
        seen.add(row.kpi_key)
    for key, item in registry_defs.items():
        if key not in seen:
            merged.append(item)
    return merged


async def get_kpi_definition(
    session: AsyncSession,
    current_user: CurrentUser,
    kpi_key: str,
    *,
    version: str | None = None,
) -> KpiDefinitionRead | None:
    fallback = get_registry_definition(
        current_user, kpi_key, version=version, include_all_versions=True
    )
    try:
        row = (
            await session.execute(
                select(KpiDefinition)
                .where(
                    KpiDefinition.deleted_at.is_(None),
                    KpiDefinition.kpi_key == kpi_key,
                )
                .options(
                    selectinload(KpiDefinition.versions).selectinload(
                        KpiDefinitionVersion.dependencies
                    )
                )
            )
        ).scalar_one_or_none()
    except Exception:
        return fallback
    if row is None:
        return fallback
    registry_kpi = get_kpi_registry().get(kpi_key, version)
    if registry_kpi is None or not can_view_kpi(registry_kpi, current_user):
        return None
    return _definition_from_db(row, registry_kpi, preferred_version=version)


def _definition_from_db(
    row: KpiDefinition,
    registry_kpi: RegisteredKpi,
    *,
    preferred_version: str | None = None,
) -> KpiDefinitionRead:
    version_reads = [_version_from_db(item) for item in sorted(row.versions, key=lambda v: v.version)]
    if not version_reads:
        return _with_stable_ids(to_definition_read(registry_kpi, include_all_versions=True), registry_kpi)

    preferred = preferred_version or registry_kpi.version
    current = next((item for item in version_reads if item.version == preferred), version_reads[-1])
    return KpiDefinitionRead(
        id=row.id,
        kpi_key=row.kpi_key,
        owner_agent=row.owner_agent,
        scope=row.scope,
        is_active=row.is_active,
        current_version=current,
        versions=version_reads,
    )


def _version_from_db(row: KpiDefinitionVersion) -> KpiVersionRead:
    return KpiVersionRead(
        id=row.id,
        version=row.version,
        name=row.name,
        description=row.description,
        unit=row.unit,
        trend_direction=row.trend_direction,
        refresh_frequency=row.refresh_frequency,
        calculator_key=row.calculator_key,
        formula_description=row.formula_description,
        source_fields=list(row.source_fields or []),
        default_thresholds=dict(row.default_thresholds or {}),
        explainability=dict(row.explainability or {}),
        allowed_roles=[str(role) for role in (row.allowed_roles or [])],
        is_client_visible=row.is_client_visible,
        compatibility_status=row.compatibility_status,
        effective_from=row.effective_from or datetime(1970, 1, 1, tzinfo=UTC),
        effective_to=row.effective_to,
        dependencies=[
            KpiDependencyRead(
                depends_on_kpi_key=dep.depends_on_kpi_key,
                depends_on_version=dep.depends_on_version,
                dependency_type=dep.dependency_type,
            )
            for dep in (row.dependencies or [])
        ],
    )
