"""Assemble a bounded ClientEvidencePack from authorized Delivery-owned facts."""

from __future__ import annotations

from datetime import UTC, date, datetime, time
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.client_intelligence.contracts import (
    BottleneckFacts,
    ClientEvidencePack,
    ClientEvidenceReference,
    DataQualityIssue,
    DataQualityState,
    DeliveryConfidenceFacts,
    DeliveryEvidenceFacts,
    EvidenceVisibility,
    GovernanceEvidenceFacts,
    KnowledgeEvidenceFacts,
    MilestoneFacts,
    ProjectIdentityFacts,
    ReportingPeriod,
    RiskAlertFacts,
    SourceAgent,
    ThroughputSnapshotFacts,
    VisibilityLimitation,
    WorkforceEvidenceFacts,
)
from app.agents.client_intelligence.evidence_fingerprint import (
    compute_source_fingerprint,
    legacy_component_fingerprint,
)
from app.agents.client_intelligence.evidence_fingerprint import (
    worst_data_quality_state as _worst_state,
)
from app.agents.client_intelligence.evidence_validation import (
    EvidencePackIntegrityError,
    finalize_data_quality_issues,
    finalize_pack_collections,
    validate_client_evidence_pack,
)
from app.agents.client_intelligence.governance_adapter import load_governance_evidence
from app.agents.client_intelligence.knowledge_adapter import load_knowledge_evidence
from app.agents.client_intelligence.quality_adapter import load_quality_evidence
from app.agents.client_intelligence.reporting_period import resolve_reporting_period
from app.agents.client_intelligence.visibility import (
    ClientVisibilityPolicy,
    ClientVisibleMetric,
    load_client_visibility_policy,
)
from app.agents.client_intelligence.workforce_adapter import load_workforce_evidence
from app.core.security import CurrentUser
from app.db.models import (
    AlertStatus,
    AppRole,
    Bottleneck,
    DeliveryConfidenceScore,
    Milestone,
    MilestoneStatus,
    Project,
    RiskAlert,
    ThroughputSnapshot,
)
from app.services.scoping import get_visible_project

_MAX_MILESTONES = 50
_MAX_OPEN_RISKS = 25
_MAX_OPEN_BOTTLENECKS = 25

_OPEN_ALERT_STATUSES = (AlertStatus.OPEN, AlertStatus.ACKNOWLEDGED)

_HISTORICAL_STATUS_LIMITATION = (
    "Risk and bottleneck rows store current status only; a past as_of cannot reliably "
    "reconstruct historical open/closed state. Status history is not claimed."
)


def _as_of_end_utc(as_of: date) -> datetime:
    return datetime.combine(as_of, time.max, tzinfo=UTC)


def _enum_str(value: object) -> str:
    return value.value if hasattr(value, "value") else str(value)


def _select_next_milestone_id(
    milestones: list[MilestoneFacts],
    *,
    as_of: date,
) -> UUID | None:
    """Deterministic next-milestone selection from stored fields only."""
    active = [
        milestone
        for milestone in milestones
        if milestone.actual_date is None and milestone.status != MilestoneStatus.COMPLETED.value
    ]
    if not active:
        return None
    upcoming = [milestone for milestone in active if milestone.planned_date >= as_of]
    if upcoming:
        return min(upcoming, key=lambda milestone: (milestone.planned_date, str(milestone.id))).id
    return max(active, key=lambda milestone: (milestone.planned_date, str(milestone.id))).id


def _fingerprint(
    *,
    project_id: UUID,
    visibility_mode: EvidenceVisibility,
    evidence: list[ClientEvidenceReference],
    reporting_period: ReportingPeriod | None = None,
    reporting_period_start: date | None = None,
    reporting_period_end: date | None = None,
    workforce: WorkforceEvidenceFacts | None = None,
    governance: GovernanceEvidenceFacts | None = None,
    knowledge: KnowledgeEvidenceFacts | None = None,
    workforce_projection: dict | None = None,
    governance_projection: dict | None = None,
    knowledge_projection: dict | None = None,
) -> str:
    """Compatibility wrapper — delegates to the single canonical fingerprint algorithm.

    Prefer ``compute_source_fingerprint`` / ``legacy_component_fingerprint``.
    Projection kwargs are accepted only for call-site migration and are ignored when
    the corresponding facts objects are provided; when only a projection dict is
    supplied for an adapter section, that section must be passed as facts instead.
    """
    _ = (workforce_projection, governance_projection, knowledge_projection)
    if reporting_period is None:
        if reporting_period_start is None or reporting_period_end is None:
            raise TypeError("reporting_period or start/end dates are required")
        # Legacy adapter tests historically fingerprinted only the current window.
        # Map onto a complete ReportingPeriod with previous = start window and as_of = end.
        reporting_period = ReportingPeriod(
            start_date=reporting_period_start,
            end_date=reporting_period_end,
            previous_start_date=reporting_period_start,
            previous_end_date=reporting_period_end,
            as_of=reporting_period_end,
        )
    return legacy_component_fingerprint(
        project_id=project_id,
        reporting_period=reporting_period,
        visibility_mode=visibility_mode,
        evidence=evidence,
        workforce=workforce,
        governance=governance,
        knowledge=knowledge,
        as_of=reporting_period.as_of,
    )


def _resolve_visibility_mode(
    current_user: CurrentUser,
    requested: EvidenceVisibility | None,
) -> EvidenceVisibility:
    if current_user.role == AppRole.CLIENT:
        return EvidenceVisibility.CLIENT_SAFE
    if requested is None:
        return EvidenceVisibility.INTERNAL
    return requested


async def build_client_evidence_pack(
    session: AsyncSession,
    current_user: CurrentUser,
    project_id: UUID,
    *,
    as_of: date | None = None,
    visibility_mode: EvidenceVisibility | None = None,
) -> ClientEvidencePack:
    """Build a bounded evidence pack for one authorized project.

    Authorization is enforced via ``get_visible_project`` before source queries.
    CLIENT_SAFE mode applies deny-by-default metric visibility. INTERNAL mode does
    not consult metric configuration.
    """
    project = await get_visible_project(session, project_id, current_user)
    effective_as_of = as_of or datetime.now(UTC).date()
    mode = _resolve_visibility_mode(current_user, visibility_mode)
    reporting_period = resolve_reporting_period(effective_as_of)
    as_of_end = _as_of_end_utc(effective_as_of)
    today = datetime.now(UTC).date()

    policy: ClientVisibilityPolicy | None = None
    policy_fingerprint: str | None = None
    if mode == EvidenceVisibility.CLIENT_SAFE:
        policy = await load_client_visibility_policy(session)
        policy_fingerprint = policy.fingerprint()

    (
        delivery,
        evidence,
        quality_issues,
        limitations,
        visibility_limitations,
    ) = await _load_delivery_facts(
        session,
        project,
        as_of=effective_as_of,
        as_of_end=as_of_end,
        today=today,
        visibility_mode=mode,
        policy=policy,
    )

    (
        quality,
        quality_evidence,
        quality_data_issues,
        quality_visibility_limitations,
        quality_limitations,
    ) = await load_quality_evidence(
        session,
        project.id,
        reporting_period,
        visibility_mode=mode,
        policy=policy,
    )
    evidence.extend(quality_evidence)
    quality_issues.extend(quality_data_issues)
    visibility_limitations.extend(quality_visibility_limitations)
    limitations.extend(quality_limitations)

    (
        workforce,
        workforce_evidence,
        workforce_data_issues,
        workforce_visibility_limitations,
        workforce_limitations,
    ) = await load_workforce_evidence(
        session,
        project.id,
        project.org_id,
        reporting_period,
        visibility_mode=mode,
    )
    evidence.extend(workforce_evidence)
    quality_issues.extend(workforce_data_issues)
    visibility_limitations.extend(workforce_visibility_limitations)
    limitations.extend(workforce_limitations)

    (
        governance,
        governance_evidence,
        governance_data_issues,
        governance_visibility_limitations,
        governance_limitations,
    ) = await load_governance_evidence(
        session,
        project.id,
        project.org_id,
        reporting_period,
        visibility_mode=mode,
    )
    evidence.extend(governance_evidence)
    quality_issues.extend(governance_data_issues)
    visibility_limitations.extend(governance_visibility_limitations)
    limitations.extend(governance_limitations)

    (
        knowledge,
        knowledge_evidence,
        knowledge_data_issues,
        knowledge_visibility_limitations,
        knowledge_limitations,
    ) = await load_knowledge_evidence(
        session,
        project.id,
        project.org_id,
        project.name,
        reporting_period,
        visibility_mode=mode,
        role=current_user.role,
    )
    evidence.extend(knowledge_evidence)
    quality_issues.extend(knowledge_data_issues)
    visibility_limitations.extend(knowledge_visibility_limitations)
    limitations.extend(knowledge_limitations)

    (
        evidence,
        quality_issues,
        visibility_limitations,
        limitations,
    ) = finalize_pack_collections(
        evidence=evidence,
        data_quality=quality_issues,
        visibility_limitations=visibility_limitations,
        limitations=limitations,
        as_of=effective_as_of,
    )

    overall = _worst_state([issue.state for issue in quality_issues])
    if not quality_issues:
        quality_issues.append(
            DataQualityIssue(
                source="delivery",
                state=DataQualityState.COMPLETE,
                detail="All requested Delivery structured sources were present.",
                observed_at=None,
            )
        )
        overall = DataQualityState.COMPLETE
        quality_issues = finalize_data_quality_issues(quality_issues)

    project_facts = ProjectIdentityFacts(
        project_id=project.id,
        org_id=project.org_id,
        project_name=project.name,
        project_status=_enum_str(project.status),
    )
    fingerprint = compute_source_fingerprint(
        project=project_facts,
        reporting_period=reporting_period,
        visibility_mode=mode,
        delivery=delivery,
        quality=quality,
        workforce=workforce,
        governance=governance,
        knowledge=knowledge,
        evidence=evidence,
        data_quality=quality_issues,
        overall_data_quality=overall,
        visibility_limitations=visibility_limitations,
        limitations=limitations,
    )

    pack = ClientEvidencePack(
        project=project_facts,
        reporting_period=reporting_period,
        visibility_mode=mode,
        delivery=delivery,
        quality=quality,
        workforce=workforce,
        governance=governance,
        knowledge=knowledge,
        evidence=evidence,
        data_quality=quality_issues,
        overall_data_quality=overall,
        generated_at=datetime.now(UTC),
        source_fingerprint=fingerprint,
        policy_fingerprint=policy_fingerprint,
        visibility_limitations=visibility_limitations,
        limitations=limitations,
    )

    validation = validate_client_evidence_pack(pack, role=current_user.role)
    if not validation.is_valid:
        raise EvidencePackIntegrityError(validation)
    return pack


async def _load_delivery_facts(
    session: AsyncSession,
    project: Project,
    *,
    as_of: date,
    as_of_end: datetime,
    today: date,
    visibility_mode: EvidenceVisibility,
    policy: ClientVisibilityPolicy | None,
) -> tuple[
    DeliveryEvidenceFacts,
    list[ClientEvidenceReference],
    list[DataQualityIssue],
    list[str],
    list[VisibilityLimitation],
]:
    evidence: list[ClientEvidenceReference] = []
    quality_issues: list[DataQualityIssue] = []
    limitations: list[str] = []
    visibility_limitations: list[VisibilityLimitation] = []
    client_safe = visibility_mode == EvidenceVisibility.CLIENT_SAFE

    evidence.append(
        ClientEvidenceReference(
            source_agent=SourceAgent.DELIVERY_PERFORMANCE,
            source_table="projects",
            source_row_id=project.id,
            description="Authorized project identity for Client Intelligence evidence pack.",
            visibility=EvidenceVisibility.CLIENT_SAFE,
            observed_at=None,
            claim_keys=["project_id", "project_name", "project_status"],
        )
    )

    milestones = await _load_milestones(session, project.id)
    milestone_facts = [
        MilestoneFacts(
            id=row.id,
            name=row.name,
            planned_date=row.planned_date,
            actual_date=row.actual_date,
            status=_enum_str(row.status),
            description=None if client_safe else row.description,
        )
        for row in milestones
    ]
    for row in milestones:
        evidence.append(
            ClientEvidenceReference(
                source_agent=SourceAgent.DELIVERY_PERFORMANCE,
                source_table="milestones",
                source_row_id=row.id,
                description=f"Milestone record '{row.name}'.",
                visibility=EvidenceVisibility.CLIENT_SAFE,
                observed_at=row.updated_at if hasattr(row, "updated_at") else None,
                claim_keys=["milestone_id", "milestone_name", "milestone_status", "planned_date"],
            )
        )
    if not milestones:
        quality_issues.append(
            DataQualityIssue(
                source="milestones",
                state=DataQualityState.UNAVAILABLE,
                detail="No milestones found for the authorized project.",
                observed_at=None,
            )
        )
        limitations.append("Milestone plan is unavailable; next milestone cannot be determined.")
    else:
        quality_issues.append(
            DataQualityIssue(
                source="milestones",
                state=DataQualityState.COMPLETE,
                detail=f"Loaded {len(milestones)} milestone row(s).",
                observed_at=None,
            )
        )

    next_milestone_id = _select_next_milestone_id(milestone_facts, as_of=as_of)

    throughput_facts = await _project_throughput(
        session,
        project.id,
        as_of=as_of,
        client_safe=client_safe,
        policy=policy,
        evidence=evidence,
        quality_issues=quality_issues,
        limitations=limitations,
        visibility_limitations=visibility_limitations,
    )

    confidence_facts = await _project_confidence(
        session,
        project.id,
        as_of_end=as_of_end,
        client_safe=client_safe,
        policy=policy,
        evidence=evidence,
        quality_issues=quality_issues,
        limitations=limitations,
        visibility_limitations=visibility_limitations,
    )

    risk_facts, bottleneck_facts = await _project_risks_and_bottlenecks(
        session,
        project.id,
        as_of=as_of,
        as_of_end=as_of_end,
        today=today,
        client_safe=client_safe,
        evidence=evidence,
        quality_issues=quality_issues,
        limitations=limitations,
        visibility_limitations=visibility_limitations,
    )

    if client_safe:
        evidence = [item for item in evidence if item.visibility == EvidenceVisibility.CLIENT_SAFE]

    delivery = DeliveryEvidenceFacts(
        latest_throughput=throughput_facts,
        latest_delivery_confidence=confidence_facts,
        milestones=milestone_facts,
        next_milestone_id=next_milestone_id,
        open_risks=risk_facts,
        open_bottlenecks=bottleneck_facts,
    )
    return delivery, evidence, quality_issues, limitations, visibility_limitations


async def _project_throughput(
    session: AsyncSession,
    project_id: UUID,
    *,
    as_of: date,
    client_safe: bool,
    policy: ClientVisibilityPolicy | None,
    evidence: list[ClientEvidenceReference],
    quality_issues: list[DataQualityIssue],
    limitations: list[str],
    visibility_limitations: list[VisibilityLimitation],
) -> ThroughputSnapshotFacts | None:
    if client_safe:
        assert policy is not None
        if not policy.allows_any_throughput():
            visibility_limitations.append(
                VisibilityLimitation(
                    source="throughput_snapshots",
                    reason="not_configured",
                    detail=(
                        "No client-visible throughput metrics are configured; "
                        "throughput facts are redacted."
                    ),
                )
            )
            return None

    throughput = await _load_latest_throughput(session, project_id, as_of=as_of)
    if throughput is None:
        quality_issues.append(
            DataQualityIssue(
                source="throughput_snapshots",
                state=DataQualityState.UNAVAILABLE,
                detail="No throughput snapshot at or before the requested as_of date.",
                observed_at=None,
            )
        )
        limitations.append("Latest throughput is unavailable.")
        return None

    if client_safe:
        assert policy is not None
        rolling = (
            throughput.rolling_7day_units
            if policy.allows(ClientVisibleMetric.THROUGHPUT_ROLLING_7D)
            else None
        )
        # units_completed / units_forecast have no known authorizing metric keys yet.
        claim_keys = ["snapshot_date"]
        if rolling is not None:
            claim_keys.append("rolling_7day_units")
        else:
            visibility_limitations.append(
                VisibilityLimitation(
                    source="throughput_snapshots",
                    reason="field_redacted",
                    detail=(
                        "Throughput snapshot exists but no authorized client-visible "
                        "throughput fields are configured."
                    ),
                )
            )
            return None

        evidence.append(
            ClientEvidenceReference(
                source_agent=SourceAgent.DELIVERY_PERFORMANCE,
                source_table="throughput_snapshots",
                source_row_id=throughput.id,
                description=(
                    f"Latest throughput snapshot on {throughput.snapshot_date.isoformat()}."
                ),
                visibility=EvidenceVisibility.CLIENT_SAFE,
                observed_at=datetime.combine(throughput.snapshot_date, time.min, tzinfo=UTC),
                claim_keys=claim_keys,
            )
        )
        quality_issues.append(
            DataQualityIssue(
                source="throughput_snapshots",
                state=DataQualityState.PARTIAL,
                detail=(
                    "Throughput row present; freshness evaluation is unresolved because no "
                    "platform stale-data threshold is configured for Client Intelligence."
                ),
                observed_at=datetime.combine(throughput.snapshot_date, time.min, tzinfo=UTC),
            )
        )
        return ThroughputSnapshotFacts(
            id=throughput.id,
            snapshot_date=throughput.snapshot_date,
            units_completed=None,
            units_forecast=None,
            rolling_7day_units=rolling,
        )

    evidence.append(
        ClientEvidenceReference(
            source_agent=SourceAgent.DELIVERY_PERFORMANCE,
            source_table="throughput_snapshots",
            source_row_id=throughput.id,
            description=(f"Latest throughput snapshot on {throughput.snapshot_date.isoformat()}."),
            visibility=EvidenceVisibility.INTERNAL,
            observed_at=datetime.combine(throughput.snapshot_date, time.min, tzinfo=UTC),
            claim_keys=[
                "units_completed",
                "units_forecast",
                "rolling_7day_units",
                "snapshot_date",
            ],
        )
    )
    quality_issues.append(
        DataQualityIssue(
            source="throughput_snapshots",
            state=DataQualityState.PARTIAL,
            detail=(
                "Throughput row present; freshness evaluation is unresolved because no "
                "platform stale-data threshold is configured for Client Intelligence."
            ),
            observed_at=datetime.combine(throughput.snapshot_date, time.min, tzinfo=UTC),
        )
    )
    return ThroughputSnapshotFacts(
        id=throughput.id,
        snapshot_date=throughput.snapshot_date,
        units_completed=throughput.units_completed,
        units_forecast=throughput.units_forecast,
        rolling_7day_units=throughput.rolling_7day_units,
    )


async def _project_confidence(
    session: AsyncSession,
    project_id: UUID,
    *,
    as_of_end: datetime,
    client_safe: bool,
    policy: ClientVisibilityPolicy | None,
    evidence: list[ClientEvidenceReference],
    quality_issues: list[DataQualityIssue],
    limitations: list[str],
    visibility_limitations: list[VisibilityLimitation],
) -> DeliveryConfidenceFacts | None:
    if client_safe:
        assert policy is not None
        if not policy.allows(ClientVisibleMetric.DELIVERY_CONFIDENCE):
            visibility_limitations.append(
                VisibilityLimitation(
                    source="delivery_confidence_scores",
                    reason="not_configured",
                    detail=(
                        "Delivery confidence is not configured as client-visible; "
                        "confidence facts are redacted."
                    ),
                )
            )
            return None

    confidence = await _load_latest_confidence(session, project_id, as_of_end=as_of_end)
    if confidence is None:
        quality_issues.append(
            DataQualityIssue(
                source="delivery_confidence_scores",
                state=DataQualityState.UNAVAILABLE,
                detail="No delivery confidence score at or before the requested as_of date.",
                observed_at=None,
            )
        )
        limitations.append("Delivery confidence score is unavailable; no score was invented.")
        return None

    if client_safe:
        evidence.append(
            ClientEvidenceReference(
                source_agent=SourceAgent.DELIVERY_PERFORMANCE,
                source_table="delivery_confidence_scores",
                source_row_id=confidence.id,
                description="Latest Delivery-owned confidence score at or before as_of.",
                visibility=EvidenceVisibility.CLIENT_SAFE,
                observed_at=confidence.created_at,
                claim_keys=["score_pct", "confidence_status", "forecast_completion_date"],
            )
        )
        quality_issues.append(
            DataQualityIssue(
                source="delivery_confidence_scores",
                state=DataQualityState.PARTIAL,
                detail=(
                    "Confidence row present; freshness evaluation is unresolved because no "
                    "platform stale-data threshold is configured for Client Intelligence."
                ),
                observed_at=confidence.created_at,
            )
        )
        return DeliveryConfidenceFacts(
            id=confidence.id,
            milestone_id=confidence.milestone_id,
            score_pct=confidence.score_pct,
            status=_enum_str(confidence.status),
            forecast_completion_date=confidence.forecast_completion_date,
            model_version=None,
            observed_at=confidence.created_at,
        )

    evidence.append(
        ClientEvidenceReference(
            source_agent=SourceAgent.DELIVERY_PERFORMANCE,
            source_table="delivery_confidence_scores",
            source_row_id=confidence.id,
            description="Latest Delivery-owned confidence score at or before as_of.",
            visibility=EvidenceVisibility.INTERNAL,
            observed_at=confidence.created_at,
            claim_keys=[
                "score_pct",
                "confidence_status",
                "forecast_completion_date",
                "model_version",
            ],
        )
    )
    quality_issues.append(
        DataQualityIssue(
            source="delivery_confidence_scores",
            state=DataQualityState.PARTIAL,
            detail=(
                "Confidence row present; freshness evaluation is unresolved because no "
                "platform stale-data threshold is configured for Client Intelligence."
            ),
            observed_at=confidence.created_at,
        )
    )
    return DeliveryConfidenceFacts(
        id=confidence.id,
        milestone_id=confidence.milestone_id,
        score_pct=confidence.score_pct,
        status=_enum_str(confidence.status),
        forecast_completion_date=confidence.forecast_completion_date,
        model_version=confidence.model_version,
        observed_at=confidence.created_at,
    )


async def _project_risks_and_bottlenecks(
    session: AsyncSession,
    project_id: UUID,
    *,
    as_of: date,
    as_of_end: datetime,
    today: date,
    client_safe: bool,
    evidence: list[ClientEvidenceReference],
    quality_issues: list[DataQualityIssue],
    limitations: list[str],
    visibility_limitations: list[VisibilityLimitation],
) -> tuple[list[RiskAlertFacts], list[BottleneckFacts]]:
    if client_safe:
        visibility_limitations.append(
            VisibilityLimitation(
                source="risk_alerts",
                reason="not_configured",
                detail=("Client-safe risk visibility is not configured; risk rows are excluded."),
            )
        )
        visibility_limitations.append(
            VisibilityLimitation(
                source="bottlenecks",
                reason="not_configured",
                detail=(
                    "Client-safe bottleneck visibility is not configured; "
                    "bottleneck rows are excluded."
                ),
            )
        )
        return [], []

    if as_of < today:
        limitations.append(_HISTORICAL_STATUS_LIMITATION)

    risks = await _load_open_risks(session, project_id, as_of_end=as_of_end)
    risk_facts: list[RiskAlertFacts] = []
    if not risks:
        quality_issues.append(
            DataQualityIssue(
                source="risk_alerts",
                state=DataQualityState.COMPLETE,
                detail="No open risk alerts at or before as_of.",
                observed_at=None,
            )
        )
    else:
        for row in risks:
            risk_facts.append(
                RiskAlertFacts(
                    id=row.id,
                    alert_type=_enum_str(row.alert_type),
                    risk_tier=_enum_str(row.risk_tier),
                    title=row.title,
                    status=_enum_str(row.status),
                    milestone_id=row.milestone_id,
                    detail=row.detail,
                    observed_at=row.created_at,
                )
            )
            evidence.append(
                ClientEvidenceReference(
                    source_agent=SourceAgent.DELIVERY_PERFORMANCE,
                    source_table="risk_alerts",
                    source_row_id=row.id,
                    description="Open risk alert (internal fields included).",
                    visibility=EvidenceVisibility.INTERNAL,
                    observed_at=row.created_at,
                    claim_keys=[
                        "risk_id",
                        "risk_title",
                        "risk_tier",
                        "alert_type",
                        "status",
                        "risk_detail",
                    ],
                )
            )
        quality_issues.append(
            DataQualityIssue(
                source="risk_alerts",
                state=DataQualityState.COMPLETE,
                detail=f"Loaded {len(risks)} open risk alert(s).",
                observed_at=None,
            )
        )

    bottlenecks = await _load_open_bottlenecks(session, project_id, as_of_end=as_of_end)
    bottleneck_facts: list[BottleneckFacts] = []
    if not bottlenecks:
        quality_issues.append(
            DataQualityIssue(
                source="bottlenecks",
                state=DataQualityState.COMPLETE,
                detail="No open bottlenecks at or before as_of.",
                observed_at=None,
            )
        )
    else:
        for row in bottlenecks:
            bottleneck_facts.append(
                BottleneckFacts(
                    id=row.id,
                    title=row.title,
                    status=_enum_str(row.status),
                    detail=row.detail,
                    observed_at=row.created_at,
                )
            )
            evidence.append(
                ClientEvidenceReference(
                    source_agent=SourceAgent.DELIVERY_PERFORMANCE,
                    source_table="bottlenecks",
                    source_row_id=row.id,
                    description="Open bottleneck (internal fields included).",
                    visibility=EvidenceVisibility.INTERNAL,
                    observed_at=row.created_at,
                    claim_keys=[
                        "bottleneck_id",
                        "bottleneck_title",
                        "status",
                        "bottleneck_detail",
                    ],
                )
            )
        quality_issues.append(
            DataQualityIssue(
                source="bottlenecks",
                state=DataQualityState.COMPLETE,
                detail=f"Loaded {len(bottlenecks)} open bottleneck(s).",
                observed_at=None,
            )
        )

    return risk_facts, bottleneck_facts


async def _load_milestones(session: AsyncSession, project_id: UUID) -> list[Milestone]:
    rows = (
        await session.execute(
            select(Milestone)
            .where(
                Milestone.project_id == project_id,
                Milestone.deleted_at.is_(None),
            )
            .order_by(Milestone.planned_date.asc(), Milestone.id.asc())
            .limit(_MAX_MILESTONES)
        )
    ).scalars()
    return list(rows)


async def _load_latest_throughput(
    session: AsyncSession,
    project_id: UUID,
    *,
    as_of: date,
) -> ThroughputSnapshot | None:
    return (
        await session.execute(
            select(ThroughputSnapshot)
            .where(
                ThroughputSnapshot.project_id == project_id,
                ThroughputSnapshot.snapshot_date <= as_of,
            )
            .order_by(ThroughputSnapshot.snapshot_date.desc(), ThroughputSnapshot.id.desc())
            .limit(1)
        )
    ).scalar_one_or_none()


async def _load_latest_confidence(
    session: AsyncSession,
    project_id: UUID,
    *,
    as_of_end: datetime,
) -> DeliveryConfidenceScore | None:
    return (
        await session.execute(
            select(DeliveryConfidenceScore)
            .where(
                DeliveryConfidenceScore.project_id == project_id,
                DeliveryConfidenceScore.created_at <= as_of_end,
            )
            .order_by(
                DeliveryConfidenceScore.created_at.desc(),
                DeliveryConfidenceScore.id.desc(),
            )
            .limit(1)
        )
    ).scalar_one_or_none()


async def _load_open_risks(
    session: AsyncSession,
    project_id: UUID,
    *,
    as_of_end: datetime,
) -> list[RiskAlert]:
    rows = (
        await session.execute(
            select(RiskAlert)
            .where(
                RiskAlert.project_id == project_id,
                RiskAlert.deleted_at.is_(None),
                RiskAlert.status.in_(_OPEN_ALERT_STATUSES),
                RiskAlert.created_at <= as_of_end,
            )
            .order_by(RiskAlert.created_at.desc(), RiskAlert.id.desc())
            .limit(_MAX_OPEN_RISKS)
        )
    ).scalars()
    return list(rows)


async def _load_open_bottlenecks(
    session: AsyncSession,
    project_id: UUID,
    *,
    as_of_end: datetime,
) -> list[Bottleneck]:
    rows = (
        await session.execute(
            select(Bottleneck)
            .where(
                Bottleneck.project_id == project_id,
                Bottleneck.deleted_at.is_(None),
                Bottleneck.status.in_(_OPEN_ALERT_STATUSES),
                Bottleneck.created_at <= as_of_end,
            )
            .order_by(Bottleneck.created_at.desc(), Bottleneck.id.desc())
            .limit(_MAX_OPEN_BOTTLENECKS)
        )
    ).scalars()
    return list(rows)
