"""Compatibility adapters for existing domain-owned report-like records.

Domain rows remain canonical. Shared ``report_instances`` are linked shadow
records used by the Phase 18.3 reporting framework for history, exports, and
approval provenance without copying domain repositories.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Any, Mapping
from uuid import UUID

from sqlalchemy import exists, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import CurrentUser
from app.db.models import (
    ClientCommunication,
    CommunicationEvidenceLink,
    GovernanceRecommendationEvaluationReport,
    GovernanceWeeklySummary,
    ProjectCharter,
    ReportEvidenceRef,
    ReportInstance,
    ReportTemplate,
)
from app.reports.contracts import ReportBuildContext
from app.reports.engine import build_report
from app.reports.registry import resolve_template
from app.time_series.observations import fingerprint_payload

logger = logging.getLogger(__name__)

_COMM_STATUS_MAP = {
    "draft": "draft",
    "in_review": "in_review",
    "approved": "approved",
    "rejected": "rejected",
    "sent": "distributed",
}


def link_communication_to_report(
    report: ReportInstance, communication: ClientCommunication
) -> ReportInstance:
    report.source_table = "client_communications"
    report.source_id = communication.id
    report.source_communication_id = communication.id
    return report


def link_weekly_summary(
    report: ReportInstance, summary: GovernanceWeeklySummary
) -> ReportInstance:
    report.source_table = "governance_weekly_summaries"
    report.source_id = summary.id
    report.source_weekly_summary_id = summary.id
    return report


def link_charter(report: ReportInstance, charter: ProjectCharter) -> ReportInstance:
    report.source_table = "project_charters"
    report.source_id = charter.id
    report.source_charter_id = charter.id
    return report


def link_evaluation_report(
    report: ReportInstance, evaluation: GovernanceRecommendationEvaluationReport
) -> ReportInstance:
    report.source_table = "governance_recommendation_evaluation_reports"
    report.source_id = evaluation.id
    report.source_evaluation_report_id = evaluation.id
    return report


def link_delivery_briefing(
    report: ReportInstance, *, project_id: UUID, briefing_fingerprint: str
) -> ReportInstance:
    report.source_table = "delivery_operational_briefings"
    report.source_id = project_id
    report.evidence_fingerprint = briefing_fingerprint
    return report


async def _resolve_required_template(
    session: AsyncSession,
    template_key: str,
    *,
    org_id: UUID | None,
) -> ReportTemplate:
    resolved = await resolve_template(session, template_key, org_id=org_id)
    if resolved is None:
        raise ValueError(f"Active report template '{template_key}' is required.")
    return resolved


def _sync_communication_fields(report: ReportInstance, communication: ClientCommunication) -> None:
    status_value = getattr(communication.status, "value", str(communication.status))
    report.status = _COMM_STATUS_MAP.get(status_value, "draft")
    body = communication.body_approved or communication.body_draft
    report.title = communication.subject
    report.body_markdown = body
    report.evidence_fingerprint = communication.evidence_source_fingerprint
    report.reviewed_by = communication.reviewed_by
    report.reviewed_at = communication.reviewed_at
    report.approved_by = communication.approved_by
    report.approved_at = communication.approved_at
    report.rejected_by = communication.rejected_by
    report.rejected_at = communication.rejected_at
    report.rejection_reason = communication.rejection_reason
    report.distributed_at = communication.sent_at
    report.generation_mode = communication.generation_mode or report.generation_mode


async def ensure_shadow_instance_for_communication(
    session: AsyncSession,
    communication: ClientCommunication,
    *,
    template: ReportTemplate | None = None,
) -> ReportInstance:
    existing = (
        await session.execute(
            select(ReportInstance).where(
                ReportInstance.source_communication_id == communication.id
            )
        )
    ).scalar_one_or_none()
    if existing is not None:
        _sync_communication_fields(existing, communication)
        await session.flush()
        return existing
    resolved = template or await _resolve_required_template(
        session,
        "client.weekly_status"
        if getattr(communication.comm_type, "value", str(communication.comm_type))
        != "executive_summary"
        else "executive.status_summary",
        org_id=communication.org_id,
    )
    status_value = getattr(communication.status, "value", str(communication.status))
    body = communication.body_approved or communication.body_draft
    fingerprint = communication.evidence_source_fingerprint or fingerprint_payload(
        {
            "communication_id": str(communication.id),
            "body": body,
            "status": status_value,
        }
    )
    report = ReportInstance(
        org_id=communication.org_id,
        project_id=communication.project_id,
        template_id=resolved.id,
        template_key=resolved.template_key,
        template_version=resolved.version,
        audience=resolved.audience,
        domain=resolved.domain,
        status=_COMM_STATUS_MAP.get(status_value, "draft"),
        title=communication.subject,
        body_markdown=body,
        content_payload={
            "sections": [
                {
                    "key": "legacy_communication",
                    "title": communication.subject,
                    "payload": {"body": body},
                    "markdown": body or "",
                    "limitations": [],
                    "has_ai": True,
                    "requires_approval": True,
                }
            ]
        },
        provenance={"adapter": "client_communication_shadow_v1"},
        limitations=["Shadow instance; canonical content remains in client_communications."],
        evidence_fingerprint=fingerprint,
        has_ai_sections=True,
        generation_mode=communication.generation_mode or "legacy_adapter",
        reviewed_by=communication.reviewed_by,
        reviewed_at=communication.reviewed_at,
        approved_by=communication.approved_by,
        approved_at=communication.approved_at,
        rejected_by=communication.rejected_by,
        rejected_at=communication.rejected_at,
        rejection_reason=communication.rejection_reason,
        distributed_at=communication.sent_at,
        idempotency_key=f"communication-shadow:{communication.id}",
    )
    link_communication_to_report(report, communication)
    session.add(report)
    await session.flush()
    links = list(
        (
            await session.execute(
                select(CommunicationEvidenceLink).where(
                    CommunicationEvidenceLink.communication_id == communication.id
                )
            )
        ).scalars()
    )
    for link in links:
        session.add(
            ReportEvidenceRef(
                org_id=communication.org_id,
                report_instance_id=report.id,
                source_table=link.source_table,
                source_id=link.source_row_id,
                label=link.description,
                metadata_={
                    "visibility": link.visibility,
                    "observed_at": link.observed_at.isoformat() if link.observed_at else None,
                    "claim_keys": list(link.claim_keys or []),
                },
            )
        )
    await session.flush()
    return report


async def ensure_shadow_instance_for_weekly_summary(
    session: AsyncSession,
    summary: GovernanceWeeklySummary,
) -> ReportInstance:
    existing = (
        await session.execute(
            select(ReportInstance).where(ReportInstance.source_weekly_summary_id == summary.id)
        )
    ).scalar_one_or_none()
    if existing is not None:
        status = (
            "approved"
            if getattr(summary.status, "value", str(summary.status)) == "approved"
            else "draft"
        )
        existing.status = status
        existing.body_markdown = summary.summary_text or existing.body_markdown
        existing.approved_by = summary.approved_by
        existing.approved_at = summary.approved_at
        await session.flush()
        return existing
    resolved = await _resolve_required_template(
        session, "governance.weekly_summary", org_id=summary.org_id
    )
    status = (
        "approved"
        if getattr(summary.status, "value", str(summary.status)) == "approved"
        else "draft"
    )
    body = summary.summary_text or "Governance weekly summary"
    week_label = summary.summary_week.isoformat() if summary.summary_week else "week"
    report = ReportInstance(
        org_id=summary.org_id,
        project_id=None,
        template_id=resolved.id,
        template_key=resolved.template_key,
        template_version=resolved.version,
        audience=resolved.audience,
        domain="governance",
        status=status,
        title=f"Governance Weekly Summary · {week_label}",
        body_markdown=body,
        content_payload={
            "sections": [
                {
                    "key": "legacy_weekly_summary",
                    "title": f"Week of {week_label}",
                    "payload": {"body": body},
                    "markdown": body,
                    "limitations": [],
                    "has_ai": bool(summary.generated_by_ai),
                    "requires_approval": True,
                }
            ]
        },
        provenance={"adapter": "governance_weekly_summary_shadow_v1"},
        limitations=["Shadow instance; canonical content remains in governance_weekly_summaries."],
        has_ai_sections=bool(summary.generated_by_ai),
        generation_mode="legacy_adapter",
        approved_by=summary.approved_by,
        approved_at=summary.approved_at,
        idempotency_key=f"weekly-summary-shadow:{summary.id}",
    )
    link_weekly_summary(report, summary)
    session.add(report)
    await session.flush()
    return report


async def ensure_shadow_instance_for_charter(
    session: AsyncSession,
    charter: ProjectCharter,
) -> ReportInstance:
    existing = (
        await session.execute(
            select(ReportInstance).where(ReportInstance.source_charter_id == charter.id)
        )
    ).scalar_one_or_none()
    if existing is not None:
        status_value = getattr(charter.status, "value", str(charter.status))
        existing.status = "approved" if status_value == "approved" else "draft"
        existing.body_markdown = charter.generated_text
        existing.approved_by = charter.approved_by
        existing.approved_at = charter.approved_at
        await session.flush()
        return existing
    resolved = await _resolve_required_template(
        session, "governance.charter", org_id=charter.org_id
    )
    status_value = getattr(charter.status, "value", str(charter.status))
    body = charter.generated_text or "Project charter"
    report = ReportInstance(
        org_id=charter.org_id,
        project_id=charter.project_id,
        template_id=resolved.id,
        template_key=resolved.template_key,
        template_version=resolved.version,
        audience=resolved.audience,
        domain="governance",
        status="approved" if status_value == "approved" else "draft",
        title=f"Project Charter · v{charter.version}",
        body_markdown=body,
        content_payload={
            "sections": [
                {
                    "key": "legacy_charter",
                    "title": f"Charter v{charter.version}",
                    "payload": {"body": body, "version": charter.version},
                    "markdown": body,
                    "limitations": [],
                    "has_ai": bool(charter.generated_by_ai),
                    "requires_approval": True,
                }
            ]
        },
        provenance={"adapter": "governance_charter_shadow_v1"},
        limitations=["Shadow instance; canonical content remains in project_charters."],
        has_ai_sections=bool(charter.generated_by_ai),
        generation_mode="legacy_adapter",
        approved_by=charter.approved_by,
        approved_at=charter.approved_at,
        idempotency_key=f"charter-shadow:{charter.id}",
    )
    link_charter(report, charter)
    session.add(report)
    await session.flush()
    return report


async def ensure_shadow_instance_for_evaluation_report(
    session: AsyncSession,
    evaluation: GovernanceRecommendationEvaluationReport,
) -> ReportInstance:
    existing = (
        await session.execute(
            select(ReportInstance).where(
                ReportInstance.source_evaluation_report_id == evaluation.id
            )
        )
    ).scalar_one_or_none()
    if existing is not None:
        existing.content_payload = {"sections": existing.content_payload.get("sections", []), "report_payload": evaluation.report_payload}
        await session.flush()
        return existing
    resolved = await _resolve_required_template(
        session, "governance.evaluation", org_id=evaluation.org_id
    )
    period = getattr(evaluation.period, "value", str(evaluation.period))
    payload = evaluation.report_payload or {}
    body = f"Governance recommendation evaluation ({period})"
    report = ReportInstance(
        org_id=evaluation.org_id,
        project_id=None,
        template_id=resolved.id,
        template_key=resolved.template_key,
        template_version=resolved.version,
        audience=resolved.audience,
        domain="governance",
        status="approved",
        title=f"Recommendation Evaluation · {period}",
        body_markdown=body,
        content_payload={
            "sections": [
                {
                    "key": "legacy_evaluation",
                    "title": f"Evaluation {period}",
                    "payload": payload,
                    "markdown": body,
                    "limitations": [],
                    "has_ai": False,
                    "requires_approval": False,
                }
            ],
            "report_payload": payload,
        },
        provenance={"adapter": "governance_evaluation_shadow_v1"},
        limitations=[
            "Shadow instance; canonical content remains in governance_recommendation_evaluation_reports."
        ],
        period_start=datetime.combine(evaluation.period_start, datetime.min.time(), tzinfo=UTC),
        period_end=datetime.combine(evaluation.period_end, datetime.min.time(), tzinfo=UTC),
        has_ai_sections=False,
        generation_mode="legacy_adapter",
        generated_by_user_id=evaluation.generated_by_user_id,
        idempotency_key=f"evaluation-shadow:{evaluation.id}",
    )
    link_evaluation_report(report, evaluation)
    session.add(report)
    await session.flush()
    return report


async def ensure_shadow_instance_for_delivery_briefing(
    session: AsyncSession,
    *,
    org_id: UUID,
    project_id: UUID,
    briefing: Mapping[str, Any],
) -> ReportInstance:
    """Link a generated Delivery briefing to a shadow report instance.

    Briefings are ephemeral (not a durable domain table). Idempotency uses
    project + briefing fingerprint so stable regenerations reuse one shadow row.
    """
    fingerprint = fingerprint_payload(
        {
            "project_id": str(project_id),
            "model_version": briefing.get("model_version"),
            "headline": briefing.get("headline") or briefing.get("title"),
            "narrative": briefing.get("narrative"),
            "overnight_changes": briefing.get("overnight_changes"),
            "top_priorities": briefing.get("top_priorities"),
        }
    )
    existing = (
        await session.execute(
            select(ReportInstance).where(
                ReportInstance.org_id == org_id,
                ReportInstance.project_id == project_id,
                ReportInstance.source_table == "delivery_operational_briefings",
                ReportInstance.idempotency_key == f"delivery-briefing-shadow:{project_id}:{fingerprint}",
            )
        )
    ).scalar_one_or_none()
    if existing is not None:
        return existing
    resolved = await _resolve_required_template(
        session, "delivery.health_summary", org_id=org_id
    )
    title = str(briefing.get("headline") or briefing.get("title") or "Delivery operational briefing")
    narrative = str(briefing.get("narrative") or title)
    report = ReportInstance(
        org_id=org_id,
        project_id=project_id,
        template_id=resolved.id,
        template_key=resolved.template_key,
        template_version=resolved.version,
        audience=resolved.audience,
        domain="delivery",
        status="draft",
        title=title,
        body_markdown=narrative,
        content_payload={
            "sections": [
                {
                    "key": "legacy_delivery_briefing",
                    "title": title,
                    "payload": dict(briefing),
                    "markdown": narrative,
                    "limitations": [],
                    "has_ai": bool(briefing.get("ai_generated")),
                    "requires_approval": bool(briefing.get("ai_generated")),
                }
            ]
        },
        provenance={"adapter": "delivery_briefing_shadow_v1"},
        limitations=[
            "Shadow instance; Delivery dashboard briefing payload remains the live source of truth."
        ],
        evidence_fingerprint=fingerprint,
        has_ai_sections=bool(briefing.get("ai_generated")),
        generation_mode="legacy_adapter",
        idempotency_key=f"delivery-briefing-shadow:{project_id}:{fingerprint}",
    )
    link_delivery_briefing(report, project_id=project_id, briefing_fingerprint=fingerprint)
    session.add(report)
    await session.flush()
    return report


async def generate_quality_report(
    session: AsyncSession,
    current_user: CurrentUser,
    *,
    project_id: UUID | None = None,
    period_start: datetime | None = None,
    period_end: datetime | None = None,
) -> ReportInstance:
    """Compose a Quality report via shared templates (no alternate KPI formulas)."""
    template = await _resolve_required_template(
        session, "quality.weekly_quality", org_id=current_user.org_id
    )
    context = ReportBuildContext(
        org_id=current_user.org_id,
        project_id=project_id,
        period_start=period_start,
        period_end=period_end,
        audience=template.audience,
        template_key=template.template_key,
        template_version=template.version,
        generation_mode="structured",
    )
    return await build_report(session, current_user, template, context)


async def generate_workforce_report(
    session: AsyncSession,
    current_user: CurrentUser,
    *,
    project_id: UUID | None = None,
    period_start: datetime | None = None,
    period_end: datetime | None = None,
) -> ReportInstance:
    """Compose a Workforce report via shared templates (no alternate KPI formulas)."""
    template = await _resolve_required_template(
        session, "workforce.utilization_summary", org_id=current_user.org_id
    )
    context = ReportBuildContext(
        org_id=current_user.org_id,
        project_id=project_id,
        period_start=period_start,
        period_end=period_end,
        audience=template.audience,
        template_key=template.template_key,
        template_version=template.version,
        generation_mode="structured",
    )
    return await build_report(session, current_user, template, context)


async def lookup_platform_report_id_for_communication(
    session: AsyncSession, communication_id: UUID
) -> UUID | None:
    return (
        await session.execute(
            select(ReportInstance.id).where(
                ReportInstance.source_communication_id == communication_id
            )
        )
    ).scalar_one_or_none()


async def lookup_platform_report_id_for_weekly_summary(
    session: AsyncSession, summary_id: UUID
) -> UUID | None:
    return (
        await session.execute(
            select(ReportInstance.id).where(ReportInstance.source_weekly_summary_id == summary_id)
        )
    ).scalar_one_or_none()


async def backfill_communications(session: AsyncSession, limit: int = 100) -> int:
    rows = list(
        (
            await session.execute(
                select(ClientCommunication)
                .where(
                    ~exists().where(
                        ReportInstance.source_communication_id == ClientCommunication.id
                    )
                )
                .order_by(ClientCommunication.created_at.asc())
                .limit(max(1, min(limit, 1000)))
            )
        ).scalars()
    )
    count = 0
    for communication in rows:
        await ensure_shadow_instance_for_communication(session, communication)
        count += 1
    return count


async def backfill_weekly_summaries(session: AsyncSession, limit: int = 100) -> int:
    rows = list(
        (
            await session.execute(
                select(GovernanceWeeklySummary)
                .where(
                    ~exists().where(
                        ReportInstance.source_weekly_summary_id == GovernanceWeeklySummary.id
                    )
                )
                .order_by(GovernanceWeeklySummary.created_at.asc())
                .limit(max(1, min(limit, 1000)))
            )
        ).scalars()
    )
    count = 0
    for summary in rows:
        await ensure_shadow_instance_for_weekly_summary(session, summary)
        count += 1
    return count


async def backfill_charters(session: AsyncSession, limit: int = 100) -> int:
    rows = list(
        (
            await session.execute(
                select(ProjectCharter)
                .where(
                    ~exists().where(ReportInstance.source_charter_id == ProjectCharter.id)
                )
                .order_by(ProjectCharter.created_at.asc())
                .limit(max(1, min(limit, 1000)))
            )
        ).scalars()
    )
    count = 0
    for charter in rows:
        await ensure_shadow_instance_for_charter(session, charter)
        count += 1
    return count


async def backfill_evaluation_reports(session: AsyncSession, limit: int = 100) -> int:
    rows = list(
        (
            await session.execute(
                select(GovernanceRecommendationEvaluationReport)
                .where(
                    ~exists().where(
                        ReportInstance.source_evaluation_report_id
                        == GovernanceRecommendationEvaluationReport.id
                    )
                )
                .order_by(GovernanceRecommendationEvaluationReport.generated_at.asc())
                .limit(max(1, min(limit, 1000)))
            )
        ).scalars()
    )
    count = 0
    for evaluation in rows:
        await ensure_shadow_instance_for_evaluation_report(session, evaluation)
        count += 1
    return count


async def backfill_historical_reports(
    session: AsyncSession, *, limit: int = 100
) -> dict[str, int]:
    """Idempotent historical backfill across supported domain sources."""
    per_source = max(1, limit // 4)
    results = {
        "communications": await backfill_communications(session, per_source),
        "weekly_summaries": await backfill_weekly_summaries(session, per_source),
        "charters": await backfill_charters(session, per_source),
        "evaluation_reports": await backfill_evaluation_reports(session, per_source),
    }
    logger.info("event=report_backfill_complete counts=%s", results)
    return results
