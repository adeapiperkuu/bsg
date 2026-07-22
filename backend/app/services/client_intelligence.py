"""Read-only Client Intelligence overview and summary orchestration."""

from __future__ import annotations

import asyncio
from datetime import UTC, date, datetime
from decimal import ROUND_HALF_UP, Decimal
from uuid import UUID

from sqlalchemy import case, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.client_intelligence.contracts import EvidenceVisibility
from app.agents.client_intelligence.delivery_confidence_intelligence import (
    DeliveryConfidenceIntegrityError,
    assess_delivery_confidence,
)
from app.agents.client_intelligence.delivery_trend import (
    DeliveryTrendIntegrityError,
    assess_delivery_trend,
)
from app.agents.client_intelligence.evidence_pack import build_client_evidence_pack
from app.agents.client_intelligence.evidence_validation import EvidencePackIntegrityError
from app.agents.client_intelligence.go_live import (
    GoLiveIntegrityError,
    assess_go_live_readiness,
)
from app.agents.client_intelligence.project_health import (
    ProjectHealthIntegrityError,
    assess_project_health,
)
from app.agents.client_intelligence.readiness import (
    ReadinessIntegrityError,
    assess_project_readiness,
)
from app.agents.client_intelligence.recommendations import (
    RecommendationIntegrityError,
    generate_readiness_recommendations,
)
from app.agents.client_intelligence.risk_transparency import (
    RiskTransparencyIntegrityError,
    assess_risk_transparency,
)
from app.core.config import get_settings
from app.core.exceptions import ApiError
from app.core.security import CurrentUser
from app.db.session import _uses_session_pooler
from app.db.models import (
    AgentQuery,
    AgentQueryEvidenceLink,
    ClientCommunication,
    ClientCsatScore,
    CommunicationEvidenceLink,
    CommunicationStatus,
    DeliveryConfidenceScore,
    Milestone,
    MilestoneStatus,
)
from app.schemas.client_intelligence import (
    ClientIntelligenceOverviewRead,
    ClientIntelligenceReportHistoryItem,
    ClientIntelligenceReportHistoryRead,
    ClientIntelligenceReportStatus,
    ClientIntelligenceSummaryRead,
    ClientMasterHealthAvailability,
    ClientMasterRowRead,
    CsatSummaryMetric,
    DeliveryConfidenceCurrentScoreAvailability,
    DeliveryConfidenceHistoryAvailability,
    DeliveryConfidenceHistoryPoint,
    DeliveryConfidenceHistoryRead,
    DeliveryConfidenceSummaryMetric,
    QueryResponseSummaryMetric,
    ReportProvenanceAvailability,
    ReportsSummaryMetric,
    SummaryMetricAvailability,
)
from app.schemas.common import EvidenceLinkRead
from app.services.scoping import get_visible_project, scoped_project_query

_INTEGRITY_ERRORS = (
    EvidencePackIntegrityError,
    ProjectHealthIntegrityError,
    DeliveryConfidenceIntegrityError,
    RiskTransparencyIntegrityError,
    DeliveryTrendIntegrityError,
    ReadinessIntegrityError,
    GoLiveIntegrityError,
    RecommendationIntegrityError,
)

CLIENT_INTERACTION_AGENT_NAME = "client_interaction_agent"

LIMITATION_NO_AUTHORIZED_PROJECTS = "NO_AUTHORIZED_PROJECTS"
LIMITATION_REPORT_SENT_APPROVAL_PROVENANCE_INCOMPLETE = (
    "REPORT_SENT_APPROVAL_PROVENANCE_INCOMPLETE"
)
LIMITATION_QUERY_LATENCY_MISSING_OR_INVALID = "QUERY_LATENCY_MISSING_OR_INVALID"
LIMITATION_CSAT_SCORE_OUT_OF_RANGE = "CSAT_SCORE_OUT_OF_RANGE"
LIMITATION_DELIVERY_CONFIDENCE_COVERAGE_PARTIAL = (
    "DELIVERY_CONFIDENCE_COVERAGE_PARTIAL"
)
LIMITATION_DELIVERY_CONFIDENCE_SCORE_OUT_OF_RANGE = (
    "DELIVERY_CONFIDENCE_SCORE_OUT_OF_RANGE"
)
LIMITATION_DELIVERY_CONFIDENCE_HISTORY_TRUNCATED = (
    "DELIVERY_CONFIDENCE_HISTORY_TRUNCATED"
)
LIMITATION_LATEST_DELIVERY_CONFIDENCE_SCORE_OUT_OF_RANGE = (
    "LATEST_DELIVERY_CONFIDENCE_SCORE_OUT_OF_RANGE"
)
LIMITATION_REPORT_APPROVED_BODY_MISSING = "REPORT_APPROVED_BODY_MISSING"
LIMITATION_REPORT_APPROVER_MISSING = "REPORT_APPROVER_MISSING"
LIMITATION_REPORT_APPROVED_AT_MISSING = "REPORT_APPROVED_AT_MISSING"
LIMITATION_REPORT_REVIEW_PROVENANCE_INCOMPLETE = (
    "REPORT_REVIEW_PROVENANCE_INCOMPLETE"
)
LIMITATION_REPORT_SENT_AT_MISSING = "REPORT_SENT_AT_MISSING"
LIMITATION_REPORT_HISTORY_TIMESTAMP_FALLBACK = "REPORT_HISTORY_TIMESTAMP_FALLBACK"

REPORT_HISTORY_DEFAULT_LIMIT = 20
REPORT_HISTORY_MAX_LIMIT = 50

# Bounded sparkline history: most recent valid scores only.
DELIVERY_CONFIDENCE_HISTORY_LIMIT = 30

_CONFIDENCE_LATEST_ORDER = (
    DeliveryConfidenceScore.created_at.desc(),
    DeliveryConfidenceScore.id.desc(),
)

_DRAFT_STATUSES = (CommunicationStatus.DRAFT, CommunicationStatus.IN_REVIEW)
_APPROVED_STATUSES = (CommunicationStatus.APPROVED, CommunicationStatus.SENT)


def resolve_effective_as_of(as_of: date | None) -> date:
    """Resolve the request as_of boundary once at the API/service edge."""
    effective = as_of or datetime.now(UTC).date()
    today = datetime.now(UTC).date()
    if effective > today:
        raise ApiError(
            400,
            "FUTURE_AS_OF_NOT_ALLOWED",
            "as_of cannot be after the current UTC date.",
            {"as_of": effective.isoformat(), "today_utc": today.isoformat()},
        )
    return effective


async def build_client_intelligence_overview(
    session: AsyncSession,
    current_user: CurrentUser,
    project_id: UUID,
    *,
    as_of: date | None = None,
) -> ClientIntelligenceOverviewRead:
    """Assemble the internal overview from one governed evidence pack."""
    effective_as_of = resolve_effective_as_of(as_of)
    try:
        pack = await build_client_evidence_pack(
            session,
            current_user,
            project_id,
            as_of=effective_as_of,
            visibility_mode=EvidenceVisibility.INTERNAL,
        )
        project_health = assess_project_health(pack, policy=None)
        delivery_confidence = assess_delivery_confidence(pack, explanation_policy=None)
        risk_transparency = assess_risk_transparency(pack, policy=None)
        delivery_trend = assess_delivery_trend(pack, policy=None)
        readiness = assess_project_readiness(pack)
        go_live = assess_go_live_readiness(pack)
        recommendations = generate_readiness_recommendations(
            pack, readiness=readiness
        )
    except _INTEGRITY_ERRORS as exc:
        raise ApiError(
            422,
            "CLIENT_INTELLIGENCE_INTEGRITY_ERROR",
            "Client Intelligence could not be assembled from the available governed evidence.",
        ) from exc

    return ClientIntelligenceOverviewRead(
        project=pack.project,
        reporting_period=pack.reporting_period,
        as_of=pack.reporting_period.as_of,
        generated_at=pack.generated_at,
        visibility_mode=pack.visibility_mode,
        source_fingerprint=pack.source_fingerprint,
        overall_data_quality=pack.overall_data_quality,
        data_quality=pack.data_quality,
        source_limitations=list(pack.limitations),
        visibility_limitations=pack.visibility_limitations,
        project_health=project_health,
        delivery_confidence=delivery_confidence,
        risk_transparency=risk_transparency,
        delivery_trend=delivery_trend,
        readiness=readiness,
        go_live=go_live,
        recommendations=recommendations,
    )


def _empty_summary(
    *,
    authorized_project_count: int,
    limitations: list[str],
) -> ClientIntelligenceSummaryRead:
    return ClientIntelligenceSummaryRead(
        delivery_confidence=DeliveryConfidenceSummaryMetric(
            availability=SummaryMetricAvailability.NO_DATA,
            average_score_pct=None,
            covered_project_count=0,
            eligible_project_count=authorized_project_count,
            limitations=limitations,
        ),
        reports=ReportsSummaryMetric(
            availability=SummaryMetricAvailability.NO_DATA,
            drafted_count=0,
            approved_count=0,
            eligible_record_count=0,
            limitations=limitations,
        ),
        query_response=QueryResponseSummaryMetric(
            availability=SummaryMetricAvailability.NO_DATA,
            average_latency_ms=None,
            sample_size=0,
            limitations=limitations,
        ),
        csat=CsatSummaryMetric(
            availability=SummaryMetricAvailability.NO_DATA,
            average_score=None,
            sample_size=0,
            scale_max=5,
            limitations=limitations,
        ),
        authorized_project_count=authorized_project_count,
    )


def _quantize_csat(value: Decimal) -> Decimal:
    return value.quantize(Decimal("0.1"), rounding=ROUND_HALF_UP)


def _quantize_confidence(value: Decimal) -> Decimal:
    return value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def _confidence_status_value(status: object) -> str:
    return status.value if hasattr(status, "value") else str(status)


async def _authorized_project_ids(
    session: AsyncSession,
    current_user: CurrentUser,
) -> list[UUID]:
    rows = list((await session.execute(scoped_project_query(current_user))).scalars())
    return [row.id for row in rows]


async def _aggregate_reports(
    session: AsyncSession,
    project_ids: list[UUID],
) -> ReportsSummaryMetric:
    drafted_expr = func.count(case((ClientCommunication.status.in_(_DRAFT_STATUSES), 1)))
    approved_expr = func.count(
        case((ClientCommunication.status.in_(_APPROVED_STATUSES), 1))
    )
    eligible_expr = func.count(
        case((ClientCommunication.status != CommunicationStatus.REJECTED, 1))
    )
    sent_missing_approval = func.count(
        case(
            (
                (ClientCommunication.status == CommunicationStatus.SENT)
                & (ClientCommunication.approved_at.is_(None)),
                1,
            )
        )
    )
    row = (
        await session.execute(
            select(
                drafted_expr.label("drafted_count"),
                approved_expr.label("approved_count"),
                eligible_expr.label("eligible_record_count"),
                sent_missing_approval.label("sent_missing_approval"),
            ).where(
                ClientCommunication.project_id.in_(project_ids),
                ClientCommunication.drafted_by_agent == CLIENT_INTERACTION_AGENT_NAME,
            )
        )
    ).one()

    drafted = int(row.drafted_count or 0)
    approved = int(row.approved_count or 0)
    eligible = int(row.eligible_record_count or 0)
    incomplete_sent = int(row.sent_missing_approval or 0)
    limitations: list[str] = []
    if incomplete_sent > 0:
        limitations.append(LIMITATION_REPORT_SENT_APPROVAL_PROVENANCE_INCOMPLETE)

    if eligible == 0:
        return ReportsSummaryMetric(
            availability=SummaryMetricAvailability.NO_DATA,
            drafted_count=0,
            approved_count=0,
            eligible_record_count=0,
            limitations=limitations,
        )

    availability = (
        SummaryMetricAvailability.PARTIAL
        if incomplete_sent > 0
        else SummaryMetricAvailability.AVAILABLE
    )
    return ReportsSummaryMetric(
        availability=availability,
        drafted_count=drafted,
        approved_count=approved,
        eligible_record_count=eligible,
        limitations=limitations,
    )


async def _aggregate_delivery_confidence(
    session: AsyncSession,
    project_ids: list[UUID],
) -> DeliveryConfidenceSummaryMetric:
    ranked = (
        select(
            DeliveryConfidenceScore.project_id.label("project_id"),
            DeliveryConfidenceScore.score_pct.label("score_pct"),
            func.row_number()
            .over(
                partition_by=DeliveryConfidenceScore.project_id,
                order_by=_CONFIDENCE_LATEST_ORDER,
            )
            .label("row_number"),
        )
        .where(DeliveryConfidenceScore.project_id.in_(project_ids))
        .subquery()
    )
    eligible = (ranked.c.score_pct >= 0) & (ranked.c.score_pct <= 100)
    invalid = (ranked.c.score_pct < 0) | (ranked.c.score_pct > 100)
    row = (
        await session.execute(
            select(
                func.avg(case((eligible, ranked.c.score_pct))).label(
                    "average_score_pct"
                ),
                func.count(case((eligible, 1))).label("covered_project_count"),
                func.count().label("detected_project_count"),
                func.count(case((invalid, 1))).label("invalid_project_count"),
            ).where(ranked.c.row_number == 1)
        )
    ).one()

    eligible_project_count = len(project_ids)
    covered_project_count = int(row.covered_project_count or 0)
    detected_project_count = int(row.detected_project_count or 0)
    invalid_project_count = int(row.invalid_project_count or 0)
    limitations: list[str] = []
    if invalid_project_count > 0:
        limitations.append(LIMITATION_DELIVERY_CONFIDENCE_SCORE_OUT_OF_RANGE)

    if detected_project_count == 0:
        return DeliveryConfidenceSummaryMetric(
            availability=SummaryMetricAvailability.NO_DATA,
            average_score_pct=None,
            covered_project_count=0,
            eligible_project_count=eligible_project_count,
            limitations=[],
        )

    if covered_project_count == 0:
        return DeliveryConfidenceSummaryMetric(
            availability=SummaryMetricAvailability.PARTIAL,
            average_score_pct=None,
            covered_project_count=0,
            eligible_project_count=eligible_project_count,
            limitations=limitations
            or [LIMITATION_DELIVERY_CONFIDENCE_SCORE_OUT_OF_RANGE],
        )

    if covered_project_count < eligible_project_count:
        limitations.append(LIMITATION_DELIVERY_CONFIDENCE_COVERAGE_PARTIAL)

    average_score_pct = _quantize_confidence(
        Decimal(str(row.average_score_pct))
    )
    availability = (
        SummaryMetricAvailability.PARTIAL
        if limitations
        else SummaryMetricAvailability.AVAILABLE
    )
    return DeliveryConfidenceSummaryMetric(
        availability=availability,
        average_score_pct=average_score_pct,
        covered_project_count=covered_project_count,
        eligible_project_count=eligible_project_count,
        limitations=limitations,
    )


async def _aggregate_query_response(
    session: AsyncSession,
    project_ids: list[UUID],
) -> QueryResponseSummaryMetric:
    eligible = (AgentQuery.latency_ms.is_not(None)) & (AgentQuery.latency_ms >= 0)
    invalid = (AgentQuery.latency_ms.is_(None)) | (AgentQuery.latency_ms < 0)
    row = (
        await session.execute(
            select(
                func.avg(case((eligible, AgentQuery.latency_ms))).label(
                    "average_latency_ms"
                ),
                func.count(case((eligible, 1))).label("sample_size"),
                func.count().label("detected_count"),
                func.count(case((invalid, 1))).label("invalid_count"),
            ).where(
                AgentQuery.project_id.in_(project_ids),
                AgentQuery.agent_name == CLIENT_INTERACTION_AGENT_NAME,
                AgentQuery.project_id.is_not(None),
            )
        )
    ).one()

    sample_size = int(row.sample_size or 0)
    detected = int(row.detected_count or 0)
    invalid_count = int(row.invalid_count or 0)
    limitations: list[str] = []
    if invalid_count > 0:
        limitations.append(LIMITATION_QUERY_LATENCY_MISSING_OR_INVALID)

    if detected == 0:
        return QueryResponseSummaryMetric(
            availability=SummaryMetricAvailability.NO_DATA,
            average_latency_ms=None,
            sample_size=0,
            limitations=[],
        )

    if sample_size == 0:
        return QueryResponseSummaryMetric(
            availability=SummaryMetricAvailability.PARTIAL,
            average_latency_ms=None,
            sample_size=0,
            limitations=limitations or [LIMITATION_QUERY_LATENCY_MISSING_OR_INVALID],
        )

    average = int(round(float(row.average_latency_ms)))
    availability = (
        SummaryMetricAvailability.PARTIAL
        if invalid_count > 0
        else SummaryMetricAvailability.AVAILABLE
    )
    return QueryResponseSummaryMetric(
        availability=availability,
        average_latency_ms=average,
        sample_size=sample_size,
        limitations=limitations,
    )


async def _aggregate_csat(
    session: AsyncSession,
    project_ids: list[UUID],
) -> CsatSummaryMetric:
    eligible = (ClientCsatScore.score >= 1) & (ClientCsatScore.score <= 5)
    invalid = (ClientCsatScore.score < 1) | (ClientCsatScore.score > 5)
    row = (
        await session.execute(
            select(
                func.avg(case((eligible, ClientCsatScore.score))).label("average_score"),
                func.count(case((eligible, 1))).label("sample_size"),
                func.count().label("detected_count"),
                func.count(case((invalid, 1))).label("invalid_count"),
            ).where(ClientCsatScore.project_id.in_(project_ids))
        )
    ).one()

    sample_size = int(row.sample_size or 0)
    detected = int(row.detected_count or 0)
    invalid_count = int(row.invalid_count or 0)
    limitations: list[str] = []
    if invalid_count > 0:
        limitations.append(LIMITATION_CSAT_SCORE_OUT_OF_RANGE)

    if detected == 0:
        return CsatSummaryMetric(
            availability=SummaryMetricAvailability.NO_DATA,
            average_score=None,
            sample_size=0,
            scale_max=5,
            limitations=[],
        )

    if sample_size == 0:
        return CsatSummaryMetric(
            availability=SummaryMetricAvailability.PARTIAL,
            average_score=None,
            sample_size=0,
            scale_max=5,
            limitations=limitations or [LIMITATION_CSAT_SCORE_OUT_OF_RANGE],
        )

    average = _quantize_csat(Decimal(str(row.average_score)))
    availability = (
        SummaryMetricAvailability.PARTIAL
        if invalid_count > 0
        else SummaryMetricAvailability.AVAILABLE
    )
    return CsatSummaryMetric(
        availability=availability,
        average_score=average,
        sample_size=sample_size,
        scale_max=5,
        limitations=limitations,
    )


async def build_client_intelligence_summary(
    session: AsyncSession,
    current_user: CurrentUser,
    *,
    project_id: UUID | None = None,
) -> ClientIntelligenceSummaryRead:
    """Aggregate authorized-scope Client Intelligence summary KPI sources."""
    if project_id is None:
        project_ids = await _authorized_project_ids(session, current_user)
    else:
        project = await get_visible_project(session, project_id, current_user)
        project_ids = [project.id]
    if not project_ids:
        return _empty_summary(
            authorized_project_count=0,
            limitations=[LIMITATION_NO_AUTHORIZED_PROJECTS],
        )

    settings = get_settings()
    if _uses_session_pooler(settings.async_database_url):
        delivery_confidence = await _aggregate_delivery_confidence(session, project_ids)
        reports = await _aggregate_reports(session, project_ids)
        query_response = await _aggregate_query_response(session, project_ids)
        csat = await _aggregate_csat(session, project_ids)
    else:
        from app.db.session import AsyncSessionLocal

        async def _confidence():
            async with AsyncSessionLocal() as aggregate_session:
                return await _aggregate_delivery_confidence(aggregate_session, project_ids)

        async def _reports():
            async with AsyncSessionLocal() as aggregate_session:
                return await _aggregate_reports(aggregate_session, project_ids)

        async def _queries():
            async with AsyncSessionLocal() as aggregate_session:
                return await _aggregate_query_response(aggregate_session, project_ids)

        async def _csat():
            async with AsyncSessionLocal() as aggregate_session:
                return await _aggregate_csat(aggregate_session, project_ids)

        delivery_confidence, reports, query_response, csat = await asyncio.gather(
            _confidence(),
            _reports(),
            _queries(),
            _csat(),
        )

    return ClientIntelligenceSummaryRead(
        delivery_confidence=delivery_confidence,
        reports=reports,
        query_response=query_response,
        csat=csat,
        authorized_project_count=len(project_ids),
    )


async def build_client_master(
    session: AsyncSession,
    current_user: CurrentUser,
) -> list[ClientMasterRowRead]:
    """Build the live, authorized project navigator in one aggregate query."""
    authorized = scoped_project_query(current_user).subquery()

    ranked_confidence = (
        select(
            DeliveryConfidenceScore.project_id.label("project_id"),
            DeliveryConfidenceScore.score_pct.label("score_pct"),
            func.row_number()
            .over(
                partition_by=DeliveryConfidenceScore.project_id,
                order_by=_CONFIDENCE_LATEST_ORDER,
            )
            .label("row_number"),
        )
        .subquery()
    )
    latest_confidence = (
        select(
            ranked_confidence.c.project_id,
            ranked_confidence.c.score_pct,
        )
        .where(
            ranked_confidence.c.row_number == 1,
            ranked_confidence.c.score_pct >= 0,
            ranked_confidence.c.score_pct <= 100,
        )
        .subquery()
    )

    reports = (
        select(
            ClientCommunication.project_id.label("project_id"),
            func.max(
                case(
                    (
                        ClientCommunication.status.in_(_APPROVED_STATUSES),
                        ClientCommunication.approved_at,
                    )
                )
            ).label("last_report_at"),
            func.count(
                case((ClientCommunication.status.in_(_DRAFT_STATUSES), 1))
            ).label("draft_count"),
        )
        .where(
            ClientCommunication.drafted_by_agent == CLIENT_INTERACTION_AGENT_NAME,
            ClientCommunication.status != CommunicationStatus.REJECTED,
        )
        .group_by(ClientCommunication.project_id)
        .subquery()
    )

    next_milestone = (
        select(
            Milestone.project_id.label("project_id"),
            func.min(Milestone.planned_date).label("next_milestone_date"),
        )
        .where(
            Milestone.deleted_at.is_(None),
            Milestone.status.in_(
                (
                    MilestoneStatus.PENDING,
                    MilestoneStatus.ON_TRACK,
                    MilestoneStatus.AT_RISK,
                )
            ),
            Milestone.planned_date >= datetime.now(UTC).date(),
        )
        .group_by(Milestone.project_id)
        .subquery()
    )

    valid_csat = (ClientCsatScore.score >= 1) & (ClientCsatScore.score <= 5)
    csat = (
        select(
            ClientCsatScore.project_id.label("project_id"),
            func.avg(case((valid_csat, ClientCsatScore.score))).label(
                "csat_average"
            ),
            func.count(case((valid_csat, 1))).label("csat_sample_size"),
        )
        .group_by(ClientCsatScore.project_id)
        .subquery()
    )

    rows = (
        await session.execute(
            select(
                authorized.c.id.label("project_id"),
                authorized.c.name.label("project_name"),
                latest_confidence.c.score_pct.label("confidence_score_pct"),
                reports.c.last_report_at,
                next_milestone.c.next_milestone_date,
                csat.c.csat_average,
                func.coalesce(csat.c.csat_sample_size, 0).label(
                    "csat_sample_size"
                ),
                func.coalesce(reports.c.draft_count, 0).label("draft_count"),
            )
            .outerjoin(
                latest_confidence,
                latest_confidence.c.project_id == authorized.c.id,
            )
            .outerjoin(reports, reports.c.project_id == authorized.c.id)
            .outerjoin(
                next_milestone,
                next_milestone.c.project_id == authorized.c.id,
            )
            .outerjoin(csat, csat.c.project_id == authorized.c.id)
            .order_by(authorized.c.name.asc(), authorized.c.id.asc())
        )
    ).all()

    # Health is not Delivery Confidence status. No governed bulk/persisted
    # Project Health assessment exists yet (CI-DQ07 open) — do not N+1 overview.
    return [
        ClientMasterRowRead(
            project_id=row.project_id,
            project_name=row.project_name,
            health_status=None,
            health_availability=ClientMasterHealthAvailability.NOT_ASSESSED,
            confidence_score_pct=(
                _quantize_confidence(Decimal(str(row.confidence_score_pct)))
                if row.confidence_score_pct is not None
                else None
            ),
            last_report_at=row.last_report_at,
            next_milestone_date=row.next_milestone_date,
            csat_average=(
                _quantize_csat(Decimal(str(row.csat_average)))
                if row.csat_average is not None
                else None
            ),
            csat_sample_size=int(row.csat_sample_size or 0),
            draft_count=int(row.draft_count or 0),
        )
        for row in rows
    ]


async def build_delivery_confidence_history(
    session: AsyncSession,
    current_user: CurrentUser,
    project_id: UUID,
    *,
    limit: int = DELIVERY_CONFIDENCE_HISTORY_LIMIT,
) -> DeliveryConfidenceHistoryRead:
    """Read bounded persisted Delivery Confidence history for one visible project.

    Canonical **current** row = latest persisted row by ``created_at DESC, id DESC``,
    then 0–100 validation (no fallback to an older valid row).

    History **points** = bounded valid persisted rows only. An older valid point is
    never promoted to current when the latest raw row is invalid.
    """
    if limit < 1:
        raise ApiError(422, "VALIDATION_ERROR", "limit must be at least 1.")

    await get_visible_project(session, project_id, current_user)

    valid_score = (DeliveryConfidenceScore.score_pct >= 0) & (
        DeliveryConfidenceScore.score_pct <= 100
    )
    invalid_score = (DeliveryConfidenceScore.score_pct < 0) | (
        DeliveryConfidenceScore.score_pct > 100
    )

    counts = (
        await session.execute(
            select(
                func.count().label("total_rows"),
                func.count(case((valid_score, 1))).label("valid_count"),
                func.count(case((invalid_score, 1))).label("invalid_count"),
            ).where(DeliveryConfidenceScore.project_id == project_id)
        )
    ).one()

    total_rows = int(counts.total_rows or 0)
    total_valid = int(counts.valid_count or 0)
    invalid_count = int(counts.invalid_count or 0)

    if total_rows == 0:
        return DeliveryConfidenceHistoryRead(
            project_id=project_id,
            availability=DeliveryConfidenceHistoryAvailability.NO_DATA,
            points=[],
            returned_point_count=0,
            total_valid_point_count=0,
            limitations=[],
            current_score_availability=DeliveryConfidenceCurrentScoreAvailability.MISSING,
            current_source_row_id=None,
            latest_history_point_is_current=False,
        )

    latest_row = (
        await session.execute(
            select(DeliveryConfidenceScore)
            .where(DeliveryConfidenceScore.project_id == project_id)
            .order_by(*_CONFIDENCE_LATEST_ORDER)
            .limit(1)
        )
    ).scalar_one_or_none()
    if latest_row is None:
        raise ApiError(
            500,
            "INTERNAL_ERROR",
            "Delivery Confidence source row count was inconsistent.",
        )

    latest_score = Decimal(str(latest_row.score_pct))
    if Decimal("0") <= latest_score <= Decimal("100"):
        current_availability = DeliveryConfidenceCurrentScoreAvailability.AVAILABLE
    else:
        current_availability = DeliveryConfidenceCurrentScoreAvailability.INVALID
    current_source_row_id = latest_row.id

    limitations: list[str] = []
    if current_availability == DeliveryConfidenceCurrentScoreAvailability.INVALID:
        limitations.append(LIMITATION_LATEST_DELIVERY_CONFIDENCE_SCORE_OUT_OF_RANGE)
    if invalid_count > 0:
        limitations.append(LIMITATION_DELIVERY_CONFIDENCE_SCORE_OUT_OF_RANGE)

    if total_valid == 0:
        return DeliveryConfidenceHistoryRead(
            project_id=project_id,
            availability=DeliveryConfidenceHistoryAvailability.PARTIAL,
            points=[],
            returned_point_count=0,
            total_valid_point_count=0,
            limitations=limitations
            or [LIMITATION_LATEST_DELIVERY_CONFIDENCE_SCORE_OUT_OF_RANGE],
            current_score_availability=DeliveryConfidenceCurrentScoreAvailability.INVALID,
            current_source_row_id=current_source_row_id,
            latest_history_point_is_current=False,
        )

    recent_valid = (
        await session.execute(
            select(DeliveryConfidenceScore)
            .where(
                DeliveryConfidenceScore.project_id == project_id,
                valid_score,
            )
            .order_by(*_CONFIDENCE_LATEST_ORDER)
            .limit(limit)
        )
    ).scalars().all()

    chronological = list(reversed(recent_valid))
    points = [
        DeliveryConfidenceHistoryPoint(
            source_row_id=row.id,
            project_id=row.project_id,
            milestone_id=row.milestone_id,
            score_pct=Decimal(str(row.score_pct)),
            confidence_status=_confidence_status_value(row.status),
            observed_at=row.created_at,
        )
        for row in chronological
    ]

    if total_valid > len(points):
        limitations.append(LIMITATION_DELIVERY_CONFIDENCE_HISTORY_TRUNCATED)

    latest_history_point_is_current = bool(
        points
        and current_availability
        == DeliveryConfidenceCurrentScoreAvailability.AVAILABLE
        and points[-1].source_row_id == current_source_row_id
    )

    if not points:
        return DeliveryConfidenceHistoryRead(
            project_id=project_id,
            availability=DeliveryConfidenceHistoryAvailability.PARTIAL,
            points=[],
            returned_point_count=0,
            total_valid_point_count=total_valid,
            limitations=limitations
            or [LIMITATION_DELIVERY_CONFIDENCE_SCORE_OUT_OF_RANGE],
            current_score_availability=current_availability,
            current_source_row_id=current_source_row_id,
            latest_history_point_is_current=False,
        )

    availability = (
        DeliveryConfidenceHistoryAvailability.PARTIAL
        if limitations
        else DeliveryConfidenceHistoryAvailability.AVAILABLE
    )
    return DeliveryConfidenceHistoryRead(
        project_id=project_id,
        availability=availability,
        points=points,
        returned_point_count=len(points),
        total_valid_point_count=total_valid,
        limitations=limitations,
        current_score_availability=current_availability,
        current_source_row_id=current_source_row_id,
        latest_history_point_is_current=latest_history_point_is_current,
    )


def _aware_timestamp(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None or value.utcoffset() is None:
        return None
    return value


def _report_history_status_value(
    status: CommunicationStatus | ClientIntelligenceReportStatus | str,
) -> ClientIntelligenceReportStatus:
    raw = status.value if hasattr(status, "value") else str(status)
    return ClientIntelligenceReportStatus(raw)


def _assess_report_provenance(
    row: ClientCommunication,
) -> tuple[ReportProvenanceAvailability, str | None, list[str], datetime | None]:
    status = _report_history_status_value(row.status)
    body = (row.body_approved or "").strip() or None
    approved_at = _aware_timestamp(row.approved_at)
    sent_at = _aware_timestamp(row.sent_at)
    reviewed_at = _aware_timestamp(row.reviewed_at)
    limitations: list[str] = []

    if body is None:
        limitations.append(LIMITATION_REPORT_APPROVED_BODY_MISSING)
    if row.approved_by is None:
        limitations.append(LIMITATION_REPORT_APPROVER_MISSING)
    if approved_at is None:
        limitations.append(LIMITATION_REPORT_APPROVED_AT_MISSING)
    if row.reviewed_by is None or reviewed_at is None:
        limitations.append(LIMITATION_REPORT_REVIEW_PROVENANCE_INCOMPLETE)
    if status == ClientIntelligenceReportStatus.SENT and sent_at is None:
        limitations.append(LIMITATION_REPORT_SENT_AT_MISSING)

    genuine_history_at = (
        sent_at if status == ClientIntelligenceReportStatus.SENT else approved_at
    )
    if genuine_history_at is None:
        limitations.append(LIMITATION_REPORT_HISTORY_TIMESTAMP_FALLBACK)

    if body is None:
        return (
            ReportProvenanceAvailability.UNAVAILABLE,
            None,
            _canonicalize_report_limitations(limitations),
            genuine_history_at,
        )

    required_ok = (
        row.approved_by is not None
        and approved_at is not None
        and (
            status != ClientIntelligenceReportStatus.SENT
            or sent_at is not None
        )
        and row.reviewed_by is not None
        and reviewed_at is not None
        and genuine_history_at is not None
    )
    if required_ok and not limitations:
        return (
            ReportProvenanceAvailability.COMPLETE,
            body,
            [],
            genuine_history_at,
        )

    # Readable body with incomplete provenance.
    return (
        ReportProvenanceAvailability.PARTIAL,
        body,
        _canonicalize_report_limitations(limitations),
        genuine_history_at,
    )


def _canonicalize_report_limitations(values: list[str]) -> list[str]:
    return sorted({item.strip() for item in values if item and item.strip()})


def _report_history_base_filters(
    project_id: UUID,
    status_filter: ClientIntelligenceReportStatus | None,
):
    statuses = (
        (CommunicationStatus(status_filter.value),)
        if status_filter is not None
        else _APPROVED_STATUSES
    )
    return (
        ClientCommunication.project_id == project_id,
        ClientCommunication.drafted_by_agent == CLIENT_INTERACTION_AGENT_NAME,
        ClientCommunication.status.in_(statuses),
    )


async def _evidence_links_for_communications(
    session: AsyncSession,
    communication_ids: list[UUID],
) -> dict[UUID, list[EvidenceLinkRead]]:
    if not communication_ids:
        return {}
    links = list(
        (
            await session.execute(
                select(CommunicationEvidenceLink)
                .where(
                    CommunicationEvidenceLink.communication_id.in_(communication_ids)
                )
                .order_by(
                    CommunicationEvidenceLink.communication_id.asc(),
                    CommunicationEvidenceLink.created_at.asc(),
                    CommunicationEvidenceLink.id.asc(),
                )
            )
        ).scalars()
    )
    grouped: dict[UUID, list[EvidenceLinkRead]] = {
        communication_id: [] for communication_id in communication_ids
    }
    for link in links:
        grouped.setdefault(link.communication_id, []).append(
            EvidenceLinkRead.model_validate(link)
        )
    return grouped


async def build_client_intelligence_report_history(
    session: AsyncSession,
    current_user: CurrentUser,
    project_id: UUID,
    *,
    limit: int = REPORT_HISTORY_DEFAULT_LIMIT,
    offset: int = 0,
    status_filter: ClientIntelligenceReportStatus | None = None,
) -> ClientIntelligenceReportHistoryRead:
    if limit < 1 or limit > REPORT_HISTORY_MAX_LIMIT:
        raise ApiError(
            422,
            "VALIDATION_ERROR",
            f"limit must be between 1 and {REPORT_HISTORY_MAX_LIMIT}.",
            {"limit": limit},
        )
    if offset < 0:
        raise ApiError(
            422,
            "VALIDATION_ERROR",
            "offset must be greater than or equal to 0.",
            {"offset": offset},
        )

    await get_visible_project(session, project_id, current_user)
    filters = _report_history_base_filters(project_id, status_filter)

    total = int(
        (
            await session.execute(
                select(func.count()).select_from(ClientCommunication).where(*filters)
            )
        ).scalar_one_or_none()
        or 0
    )

    lifecycle_ts = case(
        (
            ClientCommunication.status == CommunicationStatus.SENT,
            ClientCommunication.sent_at,
        ),
        else_=ClientCommunication.approved_at,
    )
    order_ts = func.coalesce(lifecycle_ts, ClientCommunication.created_at)

    rows = list(
        (
            await session.execute(
                select(ClientCommunication)
                .where(*filters)
                .order_by(order_ts.desc(), ClientCommunication.id.desc())
                .offset(offset)
                .limit(limit)
            )
        ).scalars()
    )
    evidence_by_id = await _evidence_links_for_communications(
        session,
        [row.id for row in rows],
    )

    items: list[ClientIntelligenceReportHistoryItem] = []
    for row in rows:
        availability, approved_body, limitations, history_at = _assess_report_provenance(
            row
        )
        report_type = (
            row.comm_type.value if hasattr(row.comm_type, "value") else str(row.comm_type)
        )
        items.append(
            ClientIntelligenceReportHistoryItem(
                communication_id=row.id,
                project_id=row.project_id,
                report_type=report_type,
                subject=row.subject,
                approved_body=approved_body,
                status=_report_history_status_value(row.status),
                reviewed_by=row.reviewed_by,
                reviewed_at=_aware_timestamp(row.reviewed_at),
                approved_by=row.approved_by,
                approved_at=_aware_timestamp(row.approved_at),
                sent_at=_aware_timestamp(row.sent_at),
                history_at=history_at,
                provenance_availability=availability,
                limitations=limitations,
                evidence_links=evidence_by_id.get(row.id, []),
                created_at=row.created_at,
                updated_at=row.updated_at,
            )
        )

    return ClientIntelligenceReportHistoryRead(
        project_id=project_id,
        items=items,
        limit=limit,
        offset=offset,
        total=total,
        has_more=offset + len(items) < total,
        status_filter=status_filter,
    )


QUERY_HISTORY_DEFAULT_LIMIT = 20
QUERY_HISTORY_MAX_LIMIT = 50


async def create_client_intelligence_query(
    session: AsyncSession,
    current_user: CurrentUser,
    project_id: UUID,
    *,
    question: str,
):
    from app.agents.client_intelligence.query_contracts import (
        ClientIntelligenceQuestionCreate,
    )
    from app.agents.client_intelligence.query_handler import (
        answer_client_intelligence_question,
    )

    payload = ClientIntelligenceQuestionCreate(question=question)
    read, _query = await answer_client_intelligence_question(
        session,
        current_user,
        project_id,
        payload,
    )
    return read


async def build_client_intelligence_query_history(
    session: AsyncSession,
    current_user: CurrentUser,
    project_id: UUID,
    *,
    limit: int = QUERY_HISTORY_DEFAULT_LIMIT,
    offset: int = 0,
):
    from app.agents.client_intelligence.query_contracts import (
        ClientIntelligenceQueryHistoryRead,
    )
    from app.agents.client_intelligence.query_handler import _to_query_read

    if limit < 1 or limit > QUERY_HISTORY_MAX_LIMIT:
        raise ApiError(
            422,
            "VALIDATION_ERROR",
            f"limit must be between 1 and {QUERY_HISTORY_MAX_LIMIT}.",
            {"limit": limit},
        )
    if offset < 0:
        raise ApiError(
            422,
            "VALIDATION_ERROR",
            "offset must be greater than or equal to 0.",
            {"offset": offset},
        )

    project = await get_visible_project(session, project_id, current_user)
    filters = (
        AgentQuery.project_id == project_id,
        AgentQuery.org_id == project.org_id,
        AgentQuery.agent_name == CLIENT_INTERACTION_AGENT_NAME,
    )
    total = int(
        (
            await session.execute(
                select(func.count()).select_from(AgentQuery).where(*filters)
            )
        ).scalar_one_or_none()
        or 0
    )
    rows = list(
        (
            await session.execute(
                select(AgentQuery)
                .where(*filters)
                .order_by(AgentQuery.created_at.desc(), AgentQuery.id.desc())
                .offset(offset)
                .limit(limit)
            )
        ).scalars()
    )
    evidence_by_id: dict[UUID, list[AgentQueryEvidenceLink]] = {
        row.id: [] for row in rows
    }
    if rows:
        links = list(
            (
                await session.execute(
                    select(AgentQueryEvidenceLink)
                    .where(
                        AgentQueryEvidenceLink.agent_query_id.in_([row.id for row in rows])
                    )
                    .order_by(
                        AgentQueryEvidenceLink.agent_query_id.asc(),
                        AgentQueryEvidenceLink.created_at.asc(),
                        AgentQueryEvidenceLink.id.asc(),
                    )
                )
            ).scalars()
        )
        for link in links:
            evidence_by_id.setdefault(link.agent_query_id, []).append(link)

    items = [_to_query_read(row, evidence_by_id.get(row.id, [])) for row in rows]
    return ClientIntelligenceQueryHistoryRead(
        project_id=project_id,
        items=items,
        limit=limit,
        offset=offset,
        total=total,
        has_more=offset + len(items) < total,
    )


async def build_project_readiness(
    session: AsyncSession,
    current_user: CurrentUser,
    project_id: UUID,
    *,
    as_of: date | None = None,
):
    """Assess project readiness from one governed evidence pack."""
    overview = await build_client_intelligence_overview(
        session, current_user, project_id, as_of=as_of
    )
    if overview.readiness is None:
        raise ApiError(
            422,
            "READINESS_UNAVAILABLE",
            "Readiness could not be assessed from the available governed evidence.",
        )
    return overview.readiness


async def build_go_live_assessment(
    session: AsyncSession,
    current_user: CurrentUser,
    project_id: UUID,
    *,
    as_of: date | None = None,
):
    overview = await build_client_intelligence_overview(
        session, current_user, project_id, as_of=as_of
    )
    if overview.go_live is None:
        raise ApiError(
            422,
            "GO_LIVE_UNAVAILABLE",
            "Go-live readiness could not be assessed from the available governed evidence.",
        )
    return overview.go_live


async def build_readiness_recommendations(
    session: AsyncSession,
    current_user: CurrentUser,
    project_id: UUID,
    *,
    as_of: date | None = None,
):
    overview = await build_client_intelligence_overview(
        session, current_user, project_id, as_of=as_of
    )
    if overview.recommendations is None:
        raise ApiError(
            422,
            "RECOMMENDATIONS_UNAVAILABLE",
            "Readiness recommendations could not be generated.",
        )
    return overview.recommendations


async def build_client_dashboard(
    session: AsyncSession,
    current_user: CurrentUser,
    project_id: UUID,
    *,
    as_of: date | None = None,
):
    """Assemble Client Dashboard widgets for readiness, reports, and health."""
    from app.agents.client_intelligence.milestone_intelligence import (
        assess_milestone_intelligence,
    )
    from app.db.models import (
        ClientIntelligenceReportPackage,
        ClientReportGovernanceStatus,
    )
    from app.schemas.client_intelligence import (
        ClientDashboardRead,
        ClientDashboardWidgetAvailability,
    )

    overview = await build_client_intelligence_overview(
        session, current_user, project_id, as_of=as_of
    )
    project = await get_visible_project(session, project_id, current_user)

    draft_statuses = (CommunicationStatus.DRAFT, CommunicationStatus.IN_REVIEW)
    approved_statuses = (CommunicationStatus.APPROVED, CommunicationStatus.SENT)
    drafted_count = int(
        (
            await session.execute(
                select(func.count())
                .select_from(ClientCommunication)
                .where(
                    ClientCommunication.project_id == project.id,
                    ClientCommunication.org_id == project.org_id,
                    ClientCommunication.drafted_by_agent == CLIENT_INTERACTION_AGENT_NAME,
                    ClientCommunication.status.in_(draft_statuses),
                )
            )
        ).scalar_one_or_none()
        or 0
    )
    approved_count = int(
        (
            await session.execute(
                select(func.count())
                .select_from(ClientCommunication)
                .where(
                    ClientCommunication.project_id == project.id,
                    ClientCommunication.org_id == project.org_id,
                    ClientCommunication.drafted_by_agent == CLIENT_INTERACTION_AGENT_NAME,
                    ClientCommunication.status.in_(approved_statuses),
                )
            )
        ).scalar_one_or_none()
        or 0
    )
    published_count = 0
    open_approvals = 0
    package_tables_available = True
    try:
        published_count = int(
            (
                await session.execute(
                    select(func.count())
                    .select_from(ClientIntelligenceReportPackage)
                    .where(
                        ClientIntelligenceReportPackage.project_id == project.id,
                        ClientIntelligenceReportPackage.org_id == project.org_id,
                        ClientIntelligenceReportPackage.status
                        == ClientReportGovernanceStatus.PUBLISHED,
                    )
                )
            ).scalar_one_or_none()
            or 0
        )
        open_approvals = int(
            (
                await session.execute(
                    select(func.count())
                    .select_from(ClientIntelligenceReportPackage)
                    .where(
                        ClientIntelligenceReportPackage.project_id == project.id,
                        ClientIntelligenceReportPackage.org_id == project.org_id,
                        ClientIntelligenceReportPackage.status.in_(
                            (
                                ClientReportGovernanceStatus.PENDING_MANAGER,
                                ClientReportGovernanceStatus.PENDING_LEADERSHIP,
                                ClientReportGovernanceStatus.PENDING_COMPLIANCE,
                            )
                        ),
                    )
                )
            ).scalar_one_or_none()
            or 0
        )
    except Exception as exc:
        # Only degrade when package tables are missing / unusable.
        detail = str(getattr(exc, "orig", exc)).lower()
        if "client_intelligence_report_packages" in detail or "does not exist" in detail:
            package_tables_available = False
            await session.rollback()
            project = await get_visible_project(session, project_id, current_user)
        else:
            raise

    pack = await build_client_evidence_pack(
        session,
        current_user,
        project.id,
        as_of=overview.as_of,
        visibility_mode=EvidenceVisibility.INTERNAL,
    )
    milestones = assess_milestone_intelligence(pack)

    def _avail(value: str | None) -> ClientDashboardWidgetAvailability:
        if value in {"available"}:
            return ClientDashboardWidgetAvailability.AVAILABLE
        if value in {"partial", "stale"}:
            return ClientDashboardWidgetAvailability.PARTIAL
        return ClientDashboardWidgetAvailability.UNAVAILABLE

    limitations = list(overview.source_limitations)
    if not package_tables_available:
        limitations.append("REPORT_PACKAGE_TABLES_UNAVAILABLE")

    return ClientDashboardRead(
        project_id=project.id,
        as_of=overview.as_of,
        generated_at=overview.generated_at,
        readiness=overview.readiness,
        go_live=overview.go_live,
        recommendations=overview.recommendations,
        project_health=overview.project_health,
        reports_drafted_count=drafted_count,
        reports_approved_count=approved_count,
        reports_published_count=published_count,
        communications_pending_count=drafted_count,
        open_approvals_count=open_approvals,
        milestone_on_track_count=milestones.period_counts.on_track_count,
        milestone_at_risk_count=milestones.period_counts.at_risk_count,
        widget_availability={
            "readiness": _avail(
                overview.readiness.availability.value if overview.readiness else None
            ),
            "reports": ClientDashboardWidgetAvailability.AVAILABLE,
            "communications": ClientDashboardWidgetAvailability.AVAILABLE,
            "project_health": (
                ClientDashboardWidgetAvailability.PARTIAL
                if overview.project_health.status.value == "insufficient"
                else ClientDashboardWidgetAvailability.AVAILABLE
            ),
            "milestones": _avail(milestones.availability.value),
            "approvals": (
                ClientDashboardWidgetAvailability.AVAILABLE
                if package_tables_available
                else ClientDashboardWidgetAvailability.UNAVAILABLE
            ),
        },
        limitations=limitations,
    )
