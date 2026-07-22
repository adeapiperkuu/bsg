"""KPI evaluation service with RBAC and version selection."""

from __future__ import annotations

import inspect
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import ApiError
from app.core.security import CurrentUser
from app.db.models import AppRole
from app.kpis.contracts import CalculatorResult, EvaluationContext, RegisteredKpi
from app.kpis.registry import get_kpi_registry
from app.kpis.thresholds import resolve_thresholds
from app.schemas.kpi import (
    KpiCalculationMetadataRead,
    KpiDefinitionRead,
    KpiDependencyRead,
    KpiEvaluationRead,
    KpiVersionRead,
)
from app.services.scoping import get_visible_project


def _role_value(role: AppRole | str) -> str:
    return role.value if isinstance(role, AppRole) else str(role)


def can_view_kpi(kpi: RegisteredKpi, current_user: CurrentUser) -> bool:
    role = _role_value(current_user.role)
    if role == AppRole.CLIENT.value:
        return kpi.is_client_visible and role in kpi.allowed_roles
    return role in kpi.allowed_roles or role == AppRole.SUPER_ADMIN.value


def filter_explainability(
    explainability: dict[str, Any] | None,
    *,
    current_user: CurrentUser,
    include_explainability: bool,
) -> dict[str, Any] | None:
    if not include_explainability or explainability is None:
        return None
    if current_user.role == AppRole.CLIENT:
        # Clients only receive the high-level summary, never internal provenance detail.
        summary = explainability.get("summary")
        return {"summary": summary} if summary else {}
    return dict(explainability)


def to_version_read(kpi: RegisteredKpi) -> KpiVersionRead:
    return KpiVersionRead(
        id=UUID(int=0),  # in-code catalog has no DB id; API overlays DB ids when available
        version=kpi.version,
        name=kpi.name,
        description=kpi.description,
        unit=kpi.unit,
        trend_direction=kpi.trend_direction,
        refresh_frequency=kpi.refresh_frequency,
        calculator_key=kpi.calculator_key,
        formula_description=kpi.formula_description,
        source_fields=list(kpi.source_fields),
        default_thresholds=dict(kpi.default_thresholds),
        explainability=dict(kpi.explainability),
        allowed_roles=list(kpi.allowed_roles),
        is_client_visible=kpi.is_client_visible,
        compatibility_status=kpi.compatibility_status,
        effective_from=datetime(1970, 1, 1, tzinfo=UTC),
        effective_to=None,
        dependencies=[
            KpiDependencyRead(
                depends_on_kpi_key=dep.depends_on_kpi_key,
                depends_on_version=dep.depends_on_version,
                dependency_type=dep.dependency_type,
            )
            for dep in kpi.dependencies
        ],
    )


def to_definition_read(kpi: RegisteredKpi, *, include_all_versions: bool = False) -> KpiDefinitionRead:
    registry = get_kpi_registry()
    versions = registry.versions_for(kpi.kpi_key) if include_all_versions else [kpi]
    version_reads = [to_version_read(item) for item in versions]
    return KpiDefinitionRead(
        id=UUID(int=0),
        kpi_key=kpi.kpi_key,
        owner_agent=kpi.owner_agent,
        scope=kpi.scope,
        is_active=kpi.compatibility_status != "historical",
        current_version=to_version_read(kpi),
        versions=version_reads,
    )


async def build_calculation_metadata(
    session: AsyncSession | None,
    kpi: RegisteredKpi,
    current_user: CurrentUser,
) -> KpiCalculationMetadataRead:
    resolved = await resolve_thresholds(
        session,
        metric_config_key=kpi.metric_config_key,
        organisation_id=current_user.org_id,
        defaults=dict(kpi.default_thresholds),
    )
    explainability = filter_explainability(
        dict(kpi.explainability),
        current_user=current_user,
        include_explainability=True,
    ) or {}
    return KpiCalculationMetadataRead(
        kpi_key=kpi.kpi_key,
        version=kpi.version,
        name=kpi.name,
        calculator_key=kpi.calculator_key,
        formula_description=kpi.formula_description,
        source_fields=list(kpi.source_fields),
        thresholds=resolved.thresholds,
        threshold_source=resolved.source,
        explainability=explainability,
        dependencies=[
            KpiDependencyRead(
                depends_on_kpi_key=dep.depends_on_kpi_key,
                depends_on_version=dep.depends_on_version,
                dependency_type=dep.dependency_type,
            )
            for dep in kpi.dependencies
        ],
        compatibility_status=kpi.compatibility_status,
        unit=kpi.unit,
        trend_direction=kpi.trend_direction,
        refresh_frequency=kpi.refresh_frequency,
    )


async def _resolve_org_and_project(
    session: AsyncSession,
    current_user: CurrentUser,
    *,
    requested_org_id: UUID | None,
    project_id: UUID | None,
    scope: str,
) -> tuple[UUID | None, UUID | None]:
    org_id = current_user.org_id
    if requested_org_id is not None:
        if current_user.role != AppRole.SUPER_ADMIN and requested_org_id != current_user.org_id:
            raise ApiError(403, "FORBIDDEN", "Cannot evaluate KPIs for another organisation.")
        org_id = requested_org_id

    if project_id is not None:
        project = await get_visible_project(session, project_id, current_user)
        if org_id is None:
            org_id = project.org_id
        elif project.org_id != org_id and current_user.role != AppRole.SUPER_ADMIN:
            raise ApiError(403, "FORBIDDEN", "Project is outside the evaluation organisation.")
        return org_id, project.id

    if scope == "project":
        raise ApiError(422, "PROJECT_REQUIRED", "This KPI requires a project_id.")
    return org_id, None


async def evaluate_kpi(
    session: AsyncSession | None,
    current_user: CurrentUser,
    kpi_key: str,
    *,
    project_id: UUID | None = None,
    org_id: UUID | None = None,
    as_of: datetime | None = None,
    version: str | None = None,
    inputs: dict[str, Any] | None = None,
    include_explainability: bool = True,
    persist_observation: bool = False,
    source_type: str = "evaluation",
    dependency_outputs: dict[str, Any] | None = None,
) -> KpiEvaluationRead:
    registry = get_kpi_registry()
    kpi = registry.get(kpi_key, version)
    if kpi is None:
        raise ApiError(404, "NOT_FOUND", f"KPI '{kpi_key}' was not found.")
    if version is not None and kpi.version != version:
        raise ApiError(404, "NOT_FOUND", f"KPI '{kpi_key}' version '{version}' was not found.")
    if not can_view_kpi(kpi, current_user):
        raise ApiError(403, "FORBIDDEN", "You do not have permission to evaluate this KPI.")

    resolved_org_id = org_id
    resolved_project_id = project_id
    has_inputs = bool(inputs)
    if session is not None:
        if kpi.scope == "project" and project_id is None and has_inputs:
            # Pure formula evaluation via explicit inputs does not require project scope.
            if org_id is not None and current_user.role != AppRole.SUPER_ADMIN:
                if org_id != current_user.org_id:
                    raise ApiError(
                        403, "FORBIDDEN", "Cannot evaluate KPIs for another organisation."
                    )
            resolved_org_id = org_id or current_user.org_id
            resolved_project_id = None
        else:
            resolved_org_id, resolved_project_id = await _resolve_org_and_project(
                session,
                current_user,
                requested_org_id=org_id,
                project_id=project_id,
                scope=kpi.scope,
            )
    elif kpi.scope == "project" and project_id is None and not has_inputs:
        raise ApiError(422, "PROJECT_REQUIRED", "This KPI requires a project_id.")

    if as_of is not None and version is None:
        # Historical evaluation without an explicit version returns no_data rather than
        # silently applying current semantics to past periods.
        return KpiEvaluationRead(
            kpi_key=kpi.kpi_key,
            version=kpi.version,
            calculator_key=kpi.calculator_key,
            org_id=resolved_org_id,
            project_id=resolved_project_id,
            evaluated_at=datetime.now(UTC),
            as_of=as_of,
            status="no_data",
            numeric_value=None,
            text_value=None,
            unit=kpi.unit,
            thresholds={},
            provenance={"reason": "historical_version_required"},
            explainability={"summary": "Historical evaluation requires an explicit KPI version."}
            if include_explainability
            else None,
            dependencies=[
                KpiDependencyRead(
                    depends_on_kpi_key=dep.depends_on_kpi_key,
                    depends_on_version=dep.depends_on_version,
                    dependency_type=dep.dependency_type,
                )
                for dep in kpi.dependencies
            ],
        )

    merged_inputs = dict(inputs or {})
    if dependency_outputs:
        merged_inputs.update(dependency_outputs)
    if session is not None and not has_inputs:
        from app.kpis.hydrators import hydrate_kpi_inputs

        merged_inputs = await hydrate_kpi_inputs(
            session,
            kpi_key=kpi.kpi_key,
            org_id=resolved_org_id,
            project_id=resolved_project_id,
            as_of=as_of,
            existing_inputs=merged_inputs,
        )

    context = EvaluationContext(
        current_user=current_user,
        org_id=resolved_org_id,
        project_id=resolved_project_id,
        as_of=as_of,
        version=kpi.version,
        inputs=merged_inputs,
        include_explainability=include_explainability,
        session=session,
    )
    calculator = registry.get_calculator(kpi.calculator_key)
    if calculator is None:
        raise ApiError(500, "KPI_CALCULATOR_MISSING", f"Calculator {kpi.calculator_key} is missing.")

    result = calculator(context)
    if inspect.isawaitable(result):
        result = await result
    if not isinstance(result, CalculatorResult):
        raise ApiError(500, "KPI_CALCULATOR_INVALID", "Calculator returned an invalid result.")

    resolved = await resolve_thresholds(
        session,
        metric_config_key=kpi.metric_config_key,
        organisation_id=resolved_org_id,
        defaults=dict(kpi.default_thresholds),
    )
    evaluation = KpiEvaluationRead(
        kpi_key=kpi.kpi_key,
        version=kpi.version,
        calculator_key=kpi.calculator_key,
        org_id=resolved_org_id,
        project_id=resolved_project_id,
        evaluated_at=datetime.now(UTC),
        as_of=as_of,
        status=result.status,
        numeric_value=_as_decimal(result.numeric_value),
        text_value=result.text_value,
        unit=kpi.unit,
        thresholds=resolved.thresholds,
        provenance=dict(result.provenance),
        explainability=filter_explainability(
            dict(result.explainability) if result.explainability else dict(kpi.explainability),
            current_user=current_user,
            include_explainability=include_explainability,
        ),
        dependencies=[
            KpiDependencyRead(
                depends_on_kpi_key=dep.depends_on_kpi_key,
                depends_on_version=dep.depends_on_version,
                dependency_type=dep.dependency_type,
            )
            for dep in kpi.dependencies
        ],
    )
    if persist_observation and session is not None and resolved_org_id is not None:
        from app.kpis.hydrators import resolve_department_key
        from app.time_series.observations import persist_kpi_observation

        department_key = await resolve_department_key(session, resolved_project_id)
        await persist_kpi_observation(
            session,
            evaluation,
            source_type=source_type,
            department_key=department_key,
            agent_key=kpi.owner_agent,
        )
    return evaluation


async def evaluate_kpis(
    session: AsyncSession | None,
    current_user: CurrentUser,
    kpi_keys: list[str],
    *,
    project_id: UUID | None = None,
    org_id: UUID | None = None,
    as_of: datetime | None = None,
    version: str | None = None,
    inputs: dict[str, Any] | None = None,
    include_explainability: bool = True,
    persist_observation: bool = False,
    source_type: str = "evaluation",
) -> list[KpiEvaluationRead]:
    registry = get_kpi_registry()
    order = registry.topological_order(kpi_keys)
    results: list[KpiEvaluationRead] = []
    shared_inputs = dict(inputs or {})
    dependency_outputs: dict[str, Any] = {}
    for key in order:
        result = await evaluate_kpi(
            session,
            current_user,
            key,
            project_id=project_id,
            org_id=org_id,
            as_of=as_of,
            version=version,
            inputs=shared_inputs,
            include_explainability=include_explainability,
            persist_observation=persist_observation,
            source_type=source_type,
            dependency_outputs=dependency_outputs,
        )
        results.append(result)
        # Wire dependency outputs for downstream calculators.
        if result.numeric_value is not None:
            if key == "delivery.confidence":
                dependency_outputs["confidence_score_pct"] = result.numeric_value
                dependency_outputs["confidence"] = result.numeric_value
            elif key == "delivery.risk":
                dependency_outputs["risk_score"] = result.numeric_value
            dependency_outputs[f"{key}.numeric_value"] = result.numeric_value
        if result.text_value is not None:
            dependency_outputs[f"{key}.text_value"] = result.text_value
    by_key = {item.kpi_key: item for item in results}
    return [by_key[key] for key in kpi_keys if key in by_key]


def _as_decimal(value: Decimal | int | float | None) -> Decimal | None:
    if value is None:
        return None
    if isinstance(value, Decimal):
        return value
    return Decimal(str(value))
