from __future__ import annotations

from datetime import UTC, datetime
from time import perf_counter
from uuid import UUID

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.governance.schemas.governance import (
    GovernanceProjectSheetActionSectionRead,
    GovernanceProjectSheetDependencySectionRead,
    GovernanceProjectSheetEscalationSectionRead,
    GovernanceProjectSheetPermissionsRead,
    GovernanceProjectSheetProjectRead,
    GovernanceProjectSheetRead,
    GovernanceProjectSheetRiskSectionRead,
    GovernanceProjectSheetSummaryRead,
    ProjectScopeStateRead,
)
from app.agents.governance.services.register_service import _compute_register_health
from app.agents.governance.timing import get_governance_timer, governance_db_section
from app.core.exceptions import ApiError
from app.core.security import CurrentUser
from app.db.models import AppRole, Project

PROJECT_SHEET_SECTION_LIMIT = 6


PROJECT_SHEET_SQL = text(
    """
    WITH authorized_project AS (
        SELECT p.id, p.org_id, p.name, p.description, p.vertical, p.status,
               p.start_date, p.target_end_date
        FROM projects p
        WHERE p.id = CAST(:project_id AS uuid)
          AND p.deleted_at IS NULL
          AND (
              CAST(:is_super_admin AS boolean)
              OR (
                  CAST(:is_internal AS boolean)
                  AND p.org_id = CAST(:org_id AS uuid)
              )
              OR (
                  CAST(:is_client AS boolean)
                  AND p.org_id = CAST(:org_id AS uuid)
                  AND EXISTS (
                      SELECT 1
                      FROM project_assignments pa
                      WHERE pa.project_id = p.id
                        AND pa.user_id = CAST(:user_id AS uuid)
                        AND pa.org_id = CAST(:org_id AS uuid)
                        AND pa.is_active IS TRUE
                        AND pa.deleted_at IS NULL
                  )
              )
          )
    ),
    scope_summary AS (
        SELECT s.id, s.scope_status, s.version_label
        FROM project_scope_states s
        JOIN authorized_project ap ON ap.id = s.project_id AND ap.org_id = s.org_id
        WHERE s.deleted_at IS NULL
        ORDER BY s.updated_at DESC, s.created_at DESC
        LIMIT 1
    ),
    scope_row AS (
        SELECT s.id, s.org_id, s.project_id, s.scope_status, s.version_label,
               s.notes, s.linked_charter_document_id, s.created_by, s.updated_by,
               s.created_at, s.updated_at
        FROM project_scope_states s
        JOIN authorized_project ap ON ap.id = s.project_id AND ap.org_id = s.org_id
        WHERE CAST(:can_view_internal AS boolean)
          AND s.deleted_at IS NULL
        ORDER BY s.updated_at DESC, s.created_at DESC
        LIMIT 1
    ),
    dependency_rows AS (
        SELECT d.id, d.project_id, d.title, d.dependency_type, d.owner_id,
               d.due_date, d.status, ap.name AS project_name,
               COALESCE(u.full_name, u.email) AS owner_name,
               CASE
                   WHEN d.status IN ('open', 'blocking') AND d.due_date < CURRENT_DATE
                   THEN CURRENT_DATE - d.due_date
                   ELSE 0
               END AS overdue_days,
               d.created_at,
               COUNT(*) OVER () AS section_total
        FROM project_dependencies d
        JOIN authorized_project ap ON ap.id = d.project_id AND ap.org_id = d.org_id
        LEFT JOIN users u ON u.id = d.owner_id
        WHERE CAST(:can_view_internal AS boolean)
          AND d.deleted_at IS NULL
        ORDER BY d.due_date ASC NULLS LAST, d.created_at DESC
        LIMIT :section_limit
    ),
    dependency_section AS (
        SELECT COALESCE(
                   jsonb_agg(
                       jsonb_build_object(
                           'id', id, 'project_id', project_id, 'title', title,
                           'dependency_type', dependency_type, 'owner_id', owner_id,
                           'due_date', due_date, 'status', status,
                           'overdue_days', overdue_days, 'project_name', project_name,
                           'owner_name', owner_name
                       ) ORDER BY due_date ASC NULLS LAST, created_at DESC
                   ), '[]'::jsonb
               ) AS items,
               COALESCE(MAX(section_total), 0) AS total
        FROM dependency_rows
    ),
    action_rows AS (
        SELECT a.id, a.project_id, a.title, a.owner_id, a.due_date,
               CASE
                   WHEN a.status IN ('open', 'in_progress') AND a.due_date < CURRENT_DATE
                   THEN 'overdue'
                   ELSE a.status::text
               END AS status,
               ap.name AS project_name, COALESCE(u.full_name, u.email) AS owner_name,
               a.created_at, COUNT(*) OVER () AS section_total
        FROM governance_actions a
        JOIN authorized_project ap ON ap.id = a.project_id AND ap.org_id = a.org_id
        LEFT JOIN users u ON u.id = a.owner_id
        WHERE CAST(:can_view_internal AS boolean)
          AND a.deleted_at IS NULL
        ORDER BY a.due_date ASC NULLS LAST, a.created_at DESC
        LIMIT :section_limit
    ),
    action_section AS (
        SELECT COALESCE(
                   jsonb_agg(
                       jsonb_build_object(
                           'id', id, 'project_id', project_id, 'title', title,
                           'owner_id', owner_id, 'due_date', due_date, 'status', status,
                           'project_name', project_name, 'owner_name', owner_name
                       ) ORDER BY due_date ASC NULLS LAST, created_at DESC
                   ), '[]'::jsonb
               ) AS items,
               COALESCE(MAX(section_total), 0) AS total
        FROM action_rows
    ),
    escalation_rows AS (
        SELECT e.id, e.project_id, e.title,
               CASE WHEN CAST(:is_client AS boolean) THEN e.client_summary ELSE e.description END
                   AS description,
               e.severity, e.status, e.raised_at,
               CASE WHEN CAST(:is_client AS boolean) THEN NULL ELSE e.source_type::text END
                   AS source_type,
               CASE WHEN CAST(:is_client AS boolean) THEN NULL ELSE e.source_id END AS source_id,
               e.client_summary, e.client_visible, e.client_published_at,
               ap.name AS project_name, COALESCE(raiser.full_name, raiser.email) AS raised_by_name,
               CASE WHEN CAST(:is_client AS boolean) THEN NULL
                    ELSE COALESCE(assignee.full_name, assignee.email) END AS assigned_to_name,
               e.created_at, COUNT(*) OVER () AS section_total
        FROM governance_escalations e
        JOIN authorized_project ap ON ap.id = e.project_id AND ap.org_id = e.org_id
        LEFT JOIN users raiser ON raiser.id = e.raised_by
        LEFT JOIN users assignee ON assignee.id = e.assigned_to
        WHERE e.deleted_at IS NULL
          AND (NOT CAST(:is_client AS boolean) OR e.client_visible IS TRUE)
        ORDER BY e.raised_at DESC, e.created_at DESC
        LIMIT :section_limit
    ),
    escalation_section AS (
        SELECT COALESCE(
                   jsonb_agg(
                       jsonb_build_object(
                           'id', id, 'project_id', project_id, 'title', title,
                           'description', description, 'severity', severity, 'status', status,
                           'raised_at', raised_at, 'source_type', source_type,
                           'source_id', source_id, 'client_summary', client_summary,
                           'client_visible', client_visible,
                           'client_published_at', client_published_at,
                           'project_name', project_name, 'raised_by_name', raised_by_name,
                           'assigned_to_name', assigned_to_name
                       ) ORDER BY raised_at DESC, created_at DESC
                   ), '[]'::jsonb
               ) AS items,
               COALESCE(MAX(section_total), 0) AS total
        FROM escalation_rows
    ),
    risk_rows AS (
        SELECT r.id, r.project_id, r.title, r.detail, r.risk_tier, r.status,
               r.created_at, COUNT(*) OVER () AS section_total
        FROM risk_alerts r
        JOIN authorized_project ap ON ap.id = r.project_id AND ap.org_id = r.org_id
        WHERE CAST(:can_view_delivery_risks AS boolean)
          AND r.deleted_at IS NULL
        ORDER BY r.created_at DESC
        LIMIT :section_limit
    ),
    risk_section AS (
        SELECT COALESCE(
                   jsonb_agg(
                       jsonb_build_object(
                           'id', id, 'project_id', project_id, 'title', title,
                           'detail', detail, 'risk_tier', risk_tier,
                           'status', status, 'created_at', created_at
                       ) ORDER BY created_at DESC
                   ), '[]'::jsonb
               ) AS items,
               COALESCE(MAX(section_total), 0) AS total
        FROM risk_rows
    )
    SELECT ap.id, ap.name, ap.description, ap.vertical, ap.status,
           ap.start_date, ap.target_end_date,
           ss.scope_status, ss.version_label AS scope_version,
           COALESCE(gs.open_dependencies_count, 0) AS open_dependencies,
           COALESCE(gs.blocked_dependencies_count, 0) AS blocking_dependencies,
           COALESCE(gs.blocking_overdue_dependencies_count, 0)
               AS blocking_overdue_dependencies,
           COALESCE(gs.open_actions_count, 0) AS open_actions,
           COALESCE(gs.overdue_actions_count, 0) AS overdue_actions,
           COALESCE(gs.open_escalations_count, 0) AS open_escalations,
           COALESCE(gs.critical_escalations_count, 0) AS critical_escalations,
           CASE WHEN s.id IS NULL THEN NULL ELSE jsonb_build_object(
               'id', s.id, 'org_id', s.org_id, 'project_id', s.project_id,
               'scope_status', s.scope_status, 'version_label', s.version_label,
               'notes', s.notes, 'linked_charter_document_id', s.linked_charter_document_id,
               'created_by', s.created_by, 'updated_by', s.updated_by,
               'created_at', s.created_at, 'updated_at', s.updated_at
           ) END AS scope,
           ds.items AS dependencies, ds.total AS dependency_total,
           acts.items AS actions, acts.total AS action_total,
           es.items AS escalations, es.total AS escalation_total,
           rs.items AS delivery_risks, rs.total AS risk_total
    FROM authorized_project ap
    LEFT JOIN project_governance_summary gs
      ON gs.project_id = ap.id AND gs.org_id = ap.org_id
    LEFT JOIN scope_summary ss ON TRUE
    LEFT JOIN scope_row s ON TRUE
    CROSS JOIN dependency_section ds
    CROSS JOIN action_section acts
    CROSS JOIN escalation_section es
    CROSS JOIN risk_section rs
    """
)


def _section(section_type, items: list[dict], total: int):
    return section_type(
        items=items,
        total=total,
        has_more=total > len(items),
    )


async def get_governance_project_sheet(
    session: AsyncSession,
    current_user: CurrentUser,
    *,
    project_id: UUID,
) -> GovernanceProjectSheetRead:
    can_internal = current_user.role in {
        AppRole.DELIVERY_MANAGER,
        AppRole.BSG_LEADERSHIP,
        AppRole.SUPER_ADMIN,
    }
    can_write = current_user.role in {AppRole.DELIVERY_MANAGER, AppRole.SUPER_ADMIN}
    params = {
        "project_id": str(project_id),
        "org_id": str(current_user.org_id) if current_user.org_id else None,
        "user_id": str(current_user.id),
        "is_super_admin": current_user.role == AppRole.SUPER_ADMIN,
        "is_internal": can_internal,
        "is_client": current_user.role == AppRole.CLIENT,
        "can_view_internal": can_internal,
        "can_view_delivery_risks": can_write,
        "section_limit": PROJECT_SHEET_SECTION_LIMIT,
    }

    db_started = perf_counter()
    async with governance_db_section():
        row = (await session.execute(PROJECT_SHEET_SQL, params)).mappings().one_or_none()
    db_ms = round((perf_counter() - db_started) * 1000, 1)

    if row is None:
        async with governance_db_section():
            project_exists = (
                await session.execute(
                    select(Project.id).where(
                        Project.id == project_id,
                        Project.deleted_at.is_(None),
                    )
                )
            ).scalar_one_or_none()
        timer = get_governance_timer()
        if timer is not None:
            timer.record_meta(project_id=str(project_id), execute_count=2, authorization_ms=db_ms)
        if project_exists is None:
            raise ApiError(
                404,
                "NOT_FOUND",
                "Project was not found.",
                {"project_id": str(project_id)},
            )
        raise ApiError(403, "FORBIDDEN", "Authenticated user lacks permission.")

    summary = GovernanceProjectSheetSummaryRead(
        scope_status=row.scope_status,
        scope_version=row.scope_version,
        open_dependencies=row.open_dependencies if can_internal else 0,
        blocking_dependencies=row.blocking_dependencies if can_internal else 0,
        open_actions=row.open_actions if can_internal else 0,
        overdue_actions=row.overdue_actions if can_internal else 0,
        open_escalations=row.open_escalations,
        critical_escalations=row.critical_escalations,
        health=_compute_register_health(
            scope_status=row.scope_status,
            critical_escalations=row.critical_escalations,
            blocking_overdue_dependencies=(
                row.blocking_overdue_dependencies if can_internal else 0
            ),
            open_escalations=row.open_escalations,
            overdue_actions=row.overdue_actions if can_internal else 0,
        ),
    )
    result = GovernanceProjectSheetRead(
        project=GovernanceProjectSheetProjectRead(
            id=row.id,
            name=row.name,
            description=row.description,
            vertical=row.vertical,
            status=str(row.status),
            start_date=row.start_date,
            target_end_date=row.target_end_date,
        ),
        summary=summary,
        scope=ProjectScopeStateRead.model_validate(row.scope) if row.scope else None,
        dependencies=_section(
            GovernanceProjectSheetDependencySectionRead,
            list(row.dependencies or []),
            int(row.dependency_total),
        ),
        actions=_section(
            GovernanceProjectSheetActionSectionRead,
            list(row.actions or []),
            int(row.action_total),
        ),
        escalations=_section(
            GovernanceProjectSheetEscalationSectionRead,
            list(row.escalations or []),
            int(row.escalation_total),
        ),
        delivery_risks=_section(
            GovernanceProjectSheetRiskSectionRead,
            list(row.delivery_risks or []),
            int(row.risk_total),
        ),
        permissions=GovernanceProjectSheetPermissionsRead(
            can_write=can_write,
            can_view_internal=can_internal,
            can_view_delivery_risks=can_write,
        ),
        generated_at=datetime.now(UTC),
    )
    timer = get_governance_timer()
    if timer is not None:
        timer.record_meta(
            project_id=str(project_id),
            execute_count=1,
            cache_hit=False,
            # Authorization is part of the same SQL statement, so there is no
            # separate authorization round trip to time on successful reads.
            authorization_ms=0.0,
            dependency_count=len(result.dependencies.items),
            action_count=len(result.actions.items),
            escalation_count=len(result.escalations.items),
            risk_count=len(result.delivery_risks.items),
        )
    return result
