"""Explicit, human-governed report lifecycle transitions."""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import ApiError
from app.core.security import CurrentUser
from app.db.models import (
    AppRole,
    NotificationType,
    ReportApprovalEvent,
    ReportInstance,
    User,
)
from app.reports.permissions import can_approve_report, can_mutate_report
from app.services.notifications import create_notification


async def _append_event(
    session: AsyncSession,
    report: ReportInstance,
    actor: CurrentUser,
    *,
    previous: str,
    action: str,
    note: str | None,
) -> None:
    session.add(
        ReportApprovalEvent(
            org_id=report.org_id,
            report_instance_id=report.id,
            actor_user_id=actor.id,
            from_status=previous,
            to_status=report.status,
            action=action,
            note=note,
            event_metadata={
                "has_ai_sections": report.has_ai_sections,
                "evidence_fingerprint": report.evidence_fingerprint,
            },
        )
    )
    await session.flush()


async def submit_for_review(
    session: AsyncSession,
    report: ReportInstance,
    current_user: CurrentUser,
    *,
    note: str | None = None,
) -> ReportInstance:
    if report.status != "draft" or not can_mutate_report(report, current_user):
        raise ApiError(409, "INVALID_REPORT_TRANSITION", "Only mutable drafts can be submitted.")
    previous = report.status
    report.status = "in_review"
    report.reviewed_by = current_user.id
    report.reviewed_at = datetime.now(UTC)
    await _append_event(
        session, report, current_user, previous=previous, action="submitted", note=note
    )
    recipients = list(
        (
            await session.execute(
                select(User).where(
                    User.org_id == report.org_id,
                    User.is_active.is_(True),
                    User.deleted_at.is_(None),
                    User.role.in_(
                        (AppRole.DELIVERY_MANAGER, AppRole.BSG_LEADERSHIP, AppRole.SUPER_ADMIN)
                    ),
                    User.id != current_user.id,
                )
            )
        ).scalars()
    )
    for recipient in recipients:
        await create_notification(
            session,
            user_id=recipient.id,
            org_id=report.org_id,
            notification_type=NotificationType.COMMUNICATION_PENDING,
            title="Report awaiting review",
            body=f"{report.title} has been submitted for review.",
            source_table="report_instances",
            source_row_id=report.id,
        )
    return report


async def approve_report(
    session: AsyncSession,
    report: ReportInstance,
    current_user: CurrentUser,
    *,
    note: str | None = None,
) -> ReportInstance:
    if not can_approve_report(report, current_user):
        raise ApiError(409, "INVALID_REPORT_TRANSITION", "Report cannot be approved.")
    previous = report.status
    report.status = "approved"
    report.approved_by = current_user.id
    report.approved_at = datetime.now(UTC)
    await _append_event(
        session, report, current_user, previous=previous, action="approved", note=note
    )
    return report


async def reject_report(
    session: AsyncSession,
    report: ReportInstance,
    current_user: CurrentUser,
    *,
    reason: str,
) -> ReportInstance:
    if not reason.strip():
        raise ApiError(422, "REJECTION_REASON_REQUIRED", "A rejection reason is required.")
    if not can_approve_report(report, current_user):
        raise ApiError(409, "INVALID_REPORT_TRANSITION", "Report cannot be rejected.")
    previous = report.status
    report.status = "rejected"
    report.rejected_by = current_user.id
    report.rejected_at = datetime.now(UTC)
    report.rejection_reason = reason.strip()
    await _append_event(
        session, report, current_user, previous=previous, action="rejected", note=reason.strip()
    )
    return report


async def distribute_report(
    session: AsyncSession,
    report: ReportInstance,
    current_user: CurrentUser,
    *,
    note: str | None = None,
) -> ReportInstance:
    if report.status != "approved" or not can_mutate_report(report, current_user):
        raise ApiError(
            409,
            "INVALID_REPORT_TRANSITION",
            "Only an approved report can be marked distributed.",
        )
    if report.has_ai_sections and report.approved_at is None:
        raise ApiError(409, "REPORT_APPROVAL_REQUIRED", "AI-authored sections require approval.")
    previous = report.status
    report.status = "distributed"
    report.distributed_at = datetime.now(UTC)
    await _append_event(
        session, report, current_user, previous=previous, action="distributed", note=note
    )
    return report
