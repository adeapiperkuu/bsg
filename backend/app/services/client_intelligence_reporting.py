"""Scheduled client reports and multi-stage governance workflow (Phase 17.4 / 19.4)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import UUID

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.client_intelligence.contracts import EvidenceVisibility
from app.agents.client_intelligence.evidence_pack import build_client_evidence_pack
from app.agents.client_intelligence.report_builder import (
    ReportBuilderRequest,
    ReportExportFormat,
    ReportSectionConfig,
    build_client_report,
    export_client_report,
)
from app.agents.delivery.audit.audit_logger import AuditLogger
from app.agents.governance.services.charter_export import (
    CharterExportDocument,
    generate_charter_docx,
    generate_charter_pdf,
)
from app.core.exceptions import ApiError
from app.core.security import CurrentUser
from app.db.models import (
    AppRole,
    ClientIntelligenceReportApproval,
    ClientIntelligenceReportDelivery,
    ClientIntelligenceReportPackage,
    ClientReportCadence,
    ClientReportDeliveryStatus,
    ClientReportGovernanceStatus,
    ClientReportSchedule,
)
from app.schemas.client_intelligence_reporting import (
    ClientReportApprovalRead,
    ClientReportDeliveryRead,
    ClientReportPackageRead,
    ClientReportScheduleCreate,
    ClientReportScheduleRead,
    ClientReportScheduleUpdate,
    ReportBuilderExportRequest,
    ReportGovernanceTransitionRequest,
)
from app.services.scoping import get_visible_project

_FORWARD_TRANSITIONS: dict[
    ClientReportGovernanceStatus, ClientReportGovernanceStatus
] = {
    ClientReportGovernanceStatus.DRAFT: ClientReportGovernanceStatus.PENDING_MANAGER,
    ClientReportGovernanceStatus.PENDING_MANAGER: (
        ClientReportGovernanceStatus.PENDING_LEADERSHIP
    ),
    ClientReportGovernanceStatus.PENDING_LEADERSHIP: (
        ClientReportGovernanceStatus.PENDING_COMPLIANCE
    ),
    ClientReportGovernanceStatus.PENDING_COMPLIANCE: (
        ClientReportGovernanceStatus.PUBLISHED
    ),
}

_REJECTABLE = frozenset(
    {
        ClientReportGovernanceStatus.PENDING_MANAGER,
        ClientReportGovernanceStatus.PENDING_LEADERSHIP,
        ClientReportGovernanceStatus.PENDING_COMPLIANCE,
    }
)

_CADENCE_DELTA = {
    ClientReportCadence.WEEKLY: timedelta(days=7),
    ClientReportCadence.MONTHLY: timedelta(days=30),
    ClientReportCadence.QUARTERLY: timedelta(days=90),
    ClientReportCadence.EXECUTIVE: timedelta(days=30),
}


def _package_read(row: ClientIntelligenceReportPackage) -> ClientReportPackageRead:
    return ClientReportPackageRead.model_validate(row, from_attributes=True)


def _schedule_read(row: ClientReportSchedule) -> ClientReportScheduleRead:
    return ClientReportScheduleRead.model_validate(row, from_attributes=True)


async def upsert_report_schedule(
    session: AsyncSession,
    current_user: CurrentUser,
    project_id: UUID,
    payload: ClientReportScheduleCreate,
) -> ClientReportScheduleRead:
    project = await get_visible_project(session, project_id, current_user)
    existing = (
        await session.execute(
            select(ClientReportSchedule).where(
                ClientReportSchedule.org_id == project.org_id,
                ClientReportSchedule.project_id == project.id,
                ClientReportSchedule.cadence == payload.cadence,
            )
        )
    ).scalar_one_or_none()

    next_run = payload.next_run_at or (
        datetime.now(UTC) + _CADENCE_DELTA[payload.cadence]
    )
    section_config = [item.model_dump(mode="json") for item in payload.sections]

    if existing is None:
        row = ClientReportSchedule(
            org_id=project.org_id,
            project_id=project.id,
            cadence=payload.cadence,
            enabled=payload.enabled,
            section_config=section_config,
            next_run_at=next_run,
            created_by=current_user.id,
        )
        session.add(row)
    else:
        existing.enabled = payload.enabled
        existing.section_config = section_config
        existing.next_run_at = next_run
        row = existing

    await session.flush()
    await AuditLogger(session).log(
        event_type="client_report_schedule.upserted",
        org_id=project.org_id,
        project_id=project.id,
        payload={"cadence": row.cadence.value, "enabled": row.enabled, "id": str(row.id)},
    )
    return _schedule_read(row)


async def list_report_schedules(
    session: AsyncSession,
    current_user: CurrentUser,
    project_id: UUID,
) -> list[ClientReportScheduleRead]:
    project = await get_visible_project(session, project_id, current_user)
    rows = (
        await session.execute(
            select(ClientReportSchedule)
            .where(
                ClientReportSchedule.org_id == project.org_id,
                ClientReportSchedule.project_id == project.id,
            )
            .order_by(ClientReportSchedule.cadence.asc())
        )
    ).scalars().all()
    return [_schedule_read(row) for row in rows]


async def update_report_schedule(
    session: AsyncSession,
    current_user: CurrentUser,
    schedule_id: UUID,
    payload: ClientReportScheduleUpdate,
) -> ClientReportScheduleRead:
    row = await session.get(ClientReportSchedule, schedule_id)
    if row is None:
        raise ApiError(404, "REPORT_SCHEDULE_NOT_FOUND", "Report schedule not found.")
    await get_visible_project(session, row.project_id, current_user)
    if payload.enabled is not None:
        row.enabled = payload.enabled
    if payload.next_run_at is not None:
        row.next_run_at = payload.next_run_at
    if payload.sections is not None:
        row.section_config = [item.model_dump(mode="json") for item in payload.sections]
    await session.flush()
    return _schedule_read(row)


async def generate_scheduled_report_draft(
    session: AsyncSession,
    current_user: CurrentUser,
    project_id: UUID,
    *,
    cadence: ClientReportCadence,
    schedule_id: UUID | None = None,
    title: str | None = None,
    sections: list[ReportSectionConfig] | None = None,
) -> ClientReportPackageRead:
    """AI draft generation step — creates a governance Draft package."""
    project = await get_visible_project(session, project_id, current_user)
    pack = await build_client_evidence_pack(
        session,
        current_user,
        project.id,
        visibility_mode=EvidenceVisibility.INTERNAL,
    )
    section_configs = sections or []
    report = build_client_report(
        pack,
        request=ReportBuilderRequest(
            title=title
            or f"{cadence.value.replace('_', ' ').title()} Client Report — "
            f"{project.name}",
            sections=section_configs,
        ),
    )

    version = 1
    latest = (
        await session.execute(
            select(ClientIntelligenceReportPackage)
            .where(
                ClientIntelligenceReportPackage.org_id == project.org_id,
                ClientIntelligenceReportPackage.project_id == project.id,
                ClientIntelligenceReportPackage.report_type == cadence,
            )
            .order_by(ClientIntelligenceReportPackage.version.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    if latest is not None:
        version = latest.version + 1

    package = ClientIntelligenceReportPackage(
        org_id=project.org_id,
        project_id=project.id,
        schedule_id=schedule_id,
        report_type=cadence,
        title=report.title,
        body_markdown=report.markdown,
        section_config=[
            {"section": s.section.value, "enabled": s.enabled} for s in report.sections
        ],
        version=version,
        status=ClientReportGovernanceStatus.DRAFT,
        source_fingerprint=report.source_fingerprint,
        created_by=current_user.id,
        updated_by=current_user.id,
    )
    session.add(package)
    await session.flush()

    session.add(
        ClientIntelligenceReportApproval(
            org_id=project.org_id,
            package_id=package.id,
            from_status=None,
            to_status=ClientReportGovernanceStatus.DRAFT,
            actor_user_id=current_user.id,
            comment="AI draft generated",
        )
    )

    if schedule_id is not None:
        schedule = await session.get(ClientReportSchedule, schedule_id)
        if schedule is not None and schedule.project_id == project.id:
            schedule.last_run_at = datetime.now(UTC)
            schedule.last_package_id = package.id
            schedule.next_run_at = datetime.now(UTC) + _CADENCE_DELTA[cadence]

    await session.flush()
    await AuditLogger(session).log(
        event_type="client_report_package.drafted",
        org_id=project.org_id,
        project_id=project.id,
        payload={"cadence": cadence.value, "version": version, "id": str(package.id)},
    )
    return _package_read(package)


async def run_due_report_schedules(
    session: AsyncSession,
    current_user: CurrentUser,
    project_id: UUID,
) -> list[ClientReportPackageRead]:
    """Generate drafts for enabled schedules that are due."""
    project = await get_visible_project(session, project_id, current_user)
    now = datetime.now(UTC)
    rows = (
        await session.execute(
            select(ClientReportSchedule).where(
                ClientReportSchedule.org_id == project.org_id,
                ClientReportSchedule.project_id == project.id,
                ClientReportSchedule.enabled.is_(True),
                or_(
                    ClientReportSchedule.next_run_at.is_(None),
                    ClientReportSchedule.next_run_at <= now,
                ),
            )
        )
    ).scalars().all()

    packages: list[ClientReportPackageRead] = []
    for schedule in rows:
        sections = [
            ReportSectionConfig.model_validate(item)
            for item in (schedule.section_config or [])
        ]
        packages.append(
            await generate_scheduled_report_draft(
                session,
                current_user,
                project.id,
                cadence=schedule.cadence,
                schedule_id=schedule.id,
                sections=sections or None,
            )
        )
    return packages


async def list_report_packages(
    session: AsyncSession,
    current_user: CurrentUser,
    project_id: UUID,
    *,
    limit: int = 20,
) -> list[ClientReportPackageRead]:
    project = await get_visible_project(session, project_id, current_user)
    rows = (
        await session.execute(
            select(ClientIntelligenceReportPackage)
            .where(
                ClientIntelligenceReportPackage.org_id == project.org_id,
                ClientIntelligenceReportPackage.project_id == project.id,
            )
            .order_by(
                ClientIntelligenceReportPackage.created_at.desc(),
                ClientIntelligenceReportPackage.version.desc(),
            )
            .limit(limit)
        )
    ).scalars().all()
    return [_package_read(row) for row in rows]


async def get_report_package(
    session: AsyncSession,
    current_user: CurrentUser,
    package_id: UUID,
) -> ClientReportPackageRead:
    row = await _get_package(session, current_user, package_id)
    return _package_read(row)


async def list_report_approvals(
    session: AsyncSession,
    current_user: CurrentUser,
    package_id: UUID,
) -> list[ClientReportApprovalRead]:
    package = await _get_package(session, current_user, package_id)
    rows = (
        await session.execute(
            select(ClientIntelligenceReportApproval)
            .where(ClientIntelligenceReportApproval.package_id == package.id)
            .order_by(ClientIntelligenceReportApproval.created_at.asc())
        )
    ).scalars().all()
    return [
        ClientReportApprovalRead.model_validate(row, from_attributes=True)
        for row in rows
    ]


async def transition_report_governance(
    session: AsyncSession,
    current_user: CurrentUser,
    package_id: UUID,
    payload: ReportGovernanceTransitionRequest,
) -> ClientReportPackageRead:
    """Advance, reject, or resubmit a report package through governance stages."""
    package = await _get_package(session, current_user, package_id)
    action = payload.action
    from_status = package.status

    if action == "submit":
        if package.status != ClientReportGovernanceStatus.DRAFT:
            raise ApiError(
                409,
                "INVALID_REPORT_GOVERNANCE_TRANSITION",
                "Only draft packages can be submitted for manager review.",
                {"current_status": package.status.value, "requested_action": action},
            )
        package.status = ClientReportGovernanceStatus.PENDING_MANAGER
        package.rejection_reason = None
    elif action == "approve":
        if package.status not in {
            ClientReportGovernanceStatus.PENDING_MANAGER,
            ClientReportGovernanceStatus.PENDING_LEADERSHIP,
            ClientReportGovernanceStatus.PENDING_COMPLIANCE,
        }:
            raise ApiError(
                409,
                "INVALID_REPORT_GOVERNANCE_TRANSITION",
                "Package cannot be approved from the current status.",
                {"current_status": package.status.value, "requested_action": action},
            )
        expected = _FORWARD_TRANSITIONS[package.status]
        _assert_approver_role(current_user, package.status)
        package.status = expected
        if package.status == ClientReportGovernanceStatus.PUBLISHED:
            package.published_at = datetime.now(UTC)
            await _record_distribution(session, package, current_user)
    elif action == "reject":
        if package.status not in _REJECTABLE:
            raise ApiError(
                409,
                "INVALID_REPORT_GOVERNANCE_TRANSITION",
                "Package cannot be rejected from the current status.",
                {"current_status": package.status.value, "requested_action": action},
            )
        reason = (payload.rejection_reason or "").strip()
        if not reason:
            raise ApiError(
                400,
                "REJECTION_REASON_REQUIRED",
                "A rejection reason is required.",
            )
        package.status = ClientReportGovernanceStatus.REJECTED
        package.rejection_reason = reason
    elif action == "resubmit":
        if package.status != ClientReportGovernanceStatus.REJECTED:
            raise ApiError(
                409,
                "INVALID_REPORT_GOVERNANCE_TRANSITION",
                "Only rejected packages can be resubmitted.",
                {"current_status": package.status.value, "requested_action": action},
            )
        package.status = ClientReportGovernanceStatus.DRAFT
        package.rejection_reason = None
        package.version += 1
    else:
        raise ApiError(400, "INVALID_GOVERNANCE_ACTION", "Unsupported governance action.")

    package.updated_by = current_user.id
    session.add(
        ClientIntelligenceReportApproval(
            org_id=package.org_id,
            package_id=package.id,
            from_status=from_status,
            to_status=package.status,
            actor_user_id=current_user.id,
            comment=(payload.comment or "").strip() or None,
            rejection_reason=package.rejection_reason if action == "reject" else None,
        )
    )
    await session.flush()
    await AuditLogger(session).log(
        event_type=f"client_report_package.{action}",
        org_id=package.org_id,
        project_id=package.project_id,
        payload={
            "from_status": from_status.value,
            "to_status": package.status.value,
            "version": package.version,
            "id": str(package.id),
        },
    )
    return _package_read(package)


async def export_report_package(
    session: AsyncSession,
    current_user: CurrentUser,
    package_id: UUID,
    payload: ReportBuilderExportRequest,
) -> tuple[bytes, str, str, ClientReportPackageRead]:
    package = await _get_package(session, current_user, package_id)
    if package.source_fingerprint:
        pack = await build_client_evidence_pack(
            session,
            current_user,
            package.project_id,
            visibility_mode=EvidenceVisibility.INTERNAL,
        )
        sections = [
            ReportSectionConfig.model_validate(item)
            for item in (package.section_config or [])
        ]
        report = build_client_report(
            pack,
            request=ReportBuilderRequest(
                title=package.title,
                sections=sections,
                export_format=payload.export_format,
            ),
        )
        content, media_type, extension = export_client_report(
            report, export_format=payload.export_format
        )
        return content, media_type, extension, _package_read(package)

    document = CharterExportDocument(
        title=package.title,
        metadata=[
            ("Project ID", str(package.project_id)),
            ("Report type", package.report_type.value.replace("_", " ").title()),
            ("Governance status", package.status.value.replace("_", " ").title()),
            ("Version", str(package.version)),
        ],
        markdown=package.body_markdown,
    )
    if payload.export_format == ReportExportFormat.DOCX:
        return (
            generate_charter_docx(document),
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            "docx",
            _package_read(package),
        )
    return (
        generate_charter_pdf(document),
        "application/pdf",
        "pdf",
        _package_read(package),
    )


async def list_report_deliveries(
    session: AsyncSession,
    current_user: CurrentUser,
    package_id: UUID,
) -> list[ClientReportDeliveryRead]:
    package = await _get_package(session, current_user, package_id)
    rows = (
        await session.execute(
            select(ClientIntelligenceReportDelivery)
            .where(ClientIntelligenceReportDelivery.package_id == package.id)
            .order_by(ClientIntelligenceReportDelivery.created_at.desc())
        )
    ).scalars().all()
    return [
        ClientReportDeliveryRead.model_validate(row, from_attributes=True)
        for row in rows
    ]


async def _get_package(
    session: AsyncSession,
    current_user: CurrentUser,
    package_id: UUID,
) -> ClientIntelligenceReportPackage:
    row = await session.get(ClientIntelligenceReportPackage, package_id)
    if row is None:
        raise ApiError(404, "REPORT_PACKAGE_NOT_FOUND", "Report package not found.")
    await get_visible_project(session, row.project_id, current_user)
    return row


def _assert_approver_role(
    current_user: CurrentUser, status: ClientReportGovernanceStatus
) -> None:
    role = current_user.role
    if role == AppRole.SUPER_ADMIN:
        return
    if status == ClientReportGovernanceStatus.PENDING_MANAGER and role in {
        AppRole.DELIVERY_MANAGER,
        AppRole.BSG_LEADERSHIP,
    }:
        return
    if status == ClientReportGovernanceStatus.PENDING_LEADERSHIP and role in {
        AppRole.BSG_LEADERSHIP,
    }:
        return
    if status == ClientReportGovernanceStatus.PENDING_COMPLIANCE and role in {
        AppRole.BSG_LEADERSHIP,
        AppRole.DELIVERY_MANAGER,
    }:
        return
    raise ApiError(
        403,
        "REPORT_GOVERNANCE_ROLE_DENIED",
        "Caller is not authorized for this governance stage.",
        {"current_status": status.value, "role": getattr(role, "value", str(role))},
    )


async def _record_distribution(
    session: AsyncSession,
    package: ClientIntelligenceReportPackage,
    current_user: CurrentUser,
) -> None:
    delivery = ClientIntelligenceReportDelivery(
        org_id=package.org_id,
        package_id=package.id,
        channel="in_app",
        status=ClientReportDeliveryStatus.DISTRIBUTED,
        recipient_summary="Published to authorized client-visible archive path",
        delivered_at=datetime.now(UTC),
    )
    session.add(delivery)
    await AuditLogger(session).log(
        event_type="client_report_package.distributed",
        org_id=package.org_id,
        project_id=package.project_id,
        payload={"channel": "in_app", "id": str(package.id)},
    )
