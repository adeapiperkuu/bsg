"""Client Intelligence readiness, go-live, recommendations, and report builder tests."""

from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal
from uuid import UUID, uuid4

import pytest

from app.agents.client_intelligence import (
    ClientEvidencePack,
    ClientEvidenceReference,
    DataQualityIssue,
    DataQualityState,
    DeliveryEvidenceFacts,
    EvidenceVisibility,
    GovernanceEvidenceFacts,
    GovernanceSummaryFacts,
    KnowledgeEvidenceFacts,
    KnowledgeSourceAvailabilityFacts,
    MilestoneFacts,
    ProjectIdentityFacts,
    QualityEvidenceFacts,
    QualitySnapshotFacts,
    RiskAlertFacts,
    SourceAgent,
    TrainingCompletionFacts,
    WorkforceCapacityFacts,
    WorkforceEvidenceFacts,
    assess_go_live_readiness,
    assess_project_readiness,
    build_client_report,
    export_client_report,
    finalize_pack_collections,
    generate_readiness_recommendations,
    resolve_reporting_period,
)
from app.agents.client_intelligence.evidence_fingerprint import (
    compute_source_fingerprint,
    worst_data_quality_state,
)
from app.agents.client_intelligence.go_live_contracts import GoLiveDecision
from app.agents.client_intelligence.readiness_contracts import ReadinessStatus
from app.agents.client_intelligence.report_builder import (
    ReportBuilderRequest,
    ReportExportFormat,
    ReportSectionConfig,
    ReportSectionKey,
)
from app.agents.client_intelligence.explainability import confidence_band_for

_AS_OF = date(2026, 6, 18)
_ORG = UUID("44444444-4444-4444-8444-444444444444")
_PROJECT = UUID("55555555-5555-5555-8555-555555555555")


def _knowledge_availability() -> list[KnowledgeSourceAvailabilityFacts]:
    rows: list[KnowledgeSourceAvailabilityFacts] = []
    for requirement_id, source_type, state, count in (
        ("CI-D11", "sop", DataQualityState.COMPLETE, 1),
        ("CI-D12", "training_document", DataQualityState.COMPLETE, 1),
        ("CI-D13", "project_charter", DataQualityState.COMPLETE, 1),
        ("CI-D14", "client_communication", DataQualityState.UNAVAILABLE, 0),
        ("CI-D15", "escalation_note", DataQualityState.UNAVAILABLE, 0),
    ):
        rows.append(
            KnowledgeSourceAvailabilityFacts(
                requirement_id=requirement_id,
                source_type=source_type,
                document_count=count,
                chunk_count=count,
                state=state,
                limitation=None if state == DataQualityState.COMPLETE else "Unavailable.",
            )
        )
    return rows


def _pack(
    *,
    critical_risks: int = 0,
    training_pct: Decimal | None = Decimal("95"),
    blocking_deps: int = 0,
    gold_accuracy: Decimal | None = Decimal("92"),
) -> ClientEvidencePack:
    period = resolve_reporting_period(_AS_OF)
    milestone_id = uuid4()
    quality_id = uuid4()
    refs = [
        ClientEvidenceReference(
            source_agent=SourceAgent.DELIVERY_PERFORMANCE,
            source_table="projects",
            source_row_id=_PROJECT,
            description="project",
            visibility=EvidenceVisibility.CLIENT_SAFE,
            claim_keys=["project_id", "project_name", "project_status"],
        ),
        ClientEvidenceReference(
            source_agent=SourceAgent.DELIVERY_PERFORMANCE,
            source_table="milestones",
            source_row_id=milestone_id,
            description="Milestone",
            visibility=EvidenceVisibility.INTERNAL,
            claim_keys=["milestone_id", "milestone_name", "milestone_status", "planned_date"],
        ),
        ClientEvidenceReference(
            source_agent=SourceAgent.QUALITY_INTELLIGENCE,
            source_table="quality_snapshots",
            source_row_id=quality_id,
            description="Quality snapshot",
            visibility=EvidenceVisibility.INTERNAL,
            claim_keys=["iso_year", "iso_week", "gold_set_accuracy_pct", "rework_rate_pct"],
            observed_at=datetime(2026, 6, 18, 12, 0, tzinfo=UTC),
        ),
    ]
    open_risks: list[RiskAlertFacts] = []
    for _ in range(critical_risks):
        rid = uuid4()
        open_risks.append(
            RiskAlertFacts(
                id=rid,
                alert_type="delivery_risk",
                risk_tier="critical",
                title="Critical blocker",
                status="open",
            )
        )
        refs.append(
            ClientEvidenceReference(
                source_agent=SourceAgent.DELIVERY_PERFORMANCE,
                source_table="risk_alerts",
                source_row_id=rid,
                description="Risk",
                visibility=EvidenceVisibility.INTERNAL,
                claim_keys=["risk_id", "risk_title", "risk_tier", "alert_type", "status"],
            )
        )

    quality_snap = QualitySnapshotFacts(
        snapshot_id=quality_id,
        iso_year=2026,
        iso_week=25,
        gold_set_accuracy_pct=gold_accuracy,
        rework_rate_pct=Decimal("5"),
        evaluated_item_count=100,
        has_drift_alert=False,
        observed_at=datetime(2026, 6, 18, 12, 0, tzinfo=UTC),
    )
    dq = [
        DataQualityIssue(
            source="milestones",
            state=DataQualityState.COMPLETE,
            detail="Milestones present.",
        ),
        DataQualityIssue(
            source="risk_alerts",
            state=DataQualityState.COMPLETE,
            detail="Risks present.",
        ),
        DataQualityIssue(
            source="quality_snapshots",
            state=DataQualityState.COMPLETE,
            detail="Quality present.",
        ),
        DataQualityIssue(
            source="workforce_capacity",
            state=DataQualityState.COMPLETE,
            detail="Workforce present.",
        ),
        DataQualityIssue(
            source="training",
            state=DataQualityState.COMPLETE,
            detail="Training present.",
        ),
        DataQualityIssue(
            source="governance",
            state=DataQualityState.COMPLETE,
            detail="Governance present.",
        ),
        DataQualityIssue(
            source="knowledge_documents",
            state=DataQualityState.COMPLETE,
            detail="Knowledge present.",
        ),
    ]
    refs, dq, vis, lim = finalize_pack_collections(
        evidence=refs,
        data_quality=dq,
        visibility_limitations=[],
        limitations=[],
    )
    delivery = DeliveryEvidenceFacts(
        milestones=[
            MilestoneFacts(
                id=milestone_id,
                name="Go Live",
                planned_date=_AS_OF,
                status="on_track",
            )
        ],
        next_milestone_id=milestone_id,
        open_risks=open_risks,
    )
    quality = QualityEvidenceFacts(
        current_period=[quality_snap],
        previous_period=[],
        current_iso_year=2026,
        current_iso_week=25,
        previous_iso_year=2026,
        previous_iso_week=24,
    )
    workforce = WorkforceEvidenceFacts(
        as_of=_AS_OF,
        capacity=WorkforceCapacityFacts(
            active_team_count=2,
            active_worker_count=10,
            certified_sme_count=2,
            utilization_pct=Decimal("75"),
        ),
        training=TrainingCompletionFacts(
            mandatory_program_count=2,
            required_assignment_count=10,
            completed_assignment_count=9 if training_pct and training_pct >= 90 else 4,
            incomplete_assignment_count=1,
            completion_pct=training_pct,
        ),
    )
    governance = GovernanceEvidenceFacts(
        as_of=_AS_OF,
        summary=GovernanceSummaryFacts(
            dependency_count=blocking_deps + 1,
            open_dependency_count=blocking_deps,
            blocking_dependency_count=blocking_deps,
            scope_present=True,
            approved_charter_present=True,
        ),
    )
    knowledge = KnowledgeEvidenceFacts(
        documents=[],
        chunks=[],
        source_availability=_knowledge_availability(),
        as_of=_AS_OF,
        project_scope_key="abc",
    )
    project = ProjectIdentityFacts(
        project_id=_PROJECT,
        org_id=_ORG,
        project_name="Aurora Labeling",
        project_status="active",
    )
    overall = worst_data_quality_state([issue.state for issue in dq])
    fp = compute_source_fingerprint(
        project=project,
        reporting_period=period,
        visibility_mode=EvidenceVisibility.INTERNAL,
        delivery=delivery,
        quality=quality,
        workforce=workforce,
        governance=governance,
        knowledge=knowledge,
        evidence=refs,
        data_quality=dq,
        overall_data_quality=overall,
        visibility_limitations=vis,
        limitations=lim,
    )
    return ClientEvidencePack(
        project=project,
        reporting_period=period,
        visibility_mode=EvidenceVisibility.INTERNAL,
        delivery=delivery,
        quality=quality,
        workforce=workforce,
        governance=governance,
        knowledge=knowledge,
        evidence=refs,
        data_quality=dq,
        overall_data_quality=overall,
        generated_at=datetime(2026, 6, 18, 12, 0, tzinfo=UTC),
        source_fingerprint=fp,
        policy_fingerprint=None,
        visibility_limitations=vis,
        limitations=lim,
    )


def test_readiness_assessment_scores_eight_categories() -> None:
    assessment = assess_project_readiness(_pack())
    assert len(assessment.categories) == 8
    assert assessment.overall_score_pct is not None
    assert assessment.overall_score_pct >= Decimal("75")
    assert assessment.status in {
        ReadinessStatus.READY,
        ReadinessStatus.READY_WITH_MINOR_RISKS,
        ReadinessStatus.CONDITIONALLY_READY,
    }
    assert assessment.explainability is not None
    assert assessment.explainability.confidence_score == assessment.assessment_confidence
    assert "readiness_score_pct" in assessment.explainability.affected_kpis


def test_critical_risk_forces_not_ready_and_no_go() -> None:
    pack = _pack(critical_risks=1, training_pct=Decimal("40"))
    readiness = assess_project_readiness(pack)
    assert readiness.status == ReadinessStatus.NOT_READY
    assert readiness.major_blockers
    go_live = assess_go_live_readiness(pack)
    assert go_live.decision == GoLiveDecision.NO_GO
    assert go_live.blocking_items
    assert go_live.explainability is not None


def test_recommendations_include_explainability() -> None:
    pack = _pack(training_pct=Decimal("40"), blocking_deps=1)
    recs = generate_readiness_recommendations(pack)
    assert recs.recommendations
    for rec in recs.recommendations:
        assert rec.explainability.why_generated
        assert rec.explainability.confidence_score == rec.confidence
        assert rec.explainability.affected_kpis
        assert rec.priority.value in {"critical", "high", "medium", "low"}


def test_report_builder_respects_disabled_sections_and_exports() -> None:
    pack = _pack()
    report = build_client_report(
        pack,
        request=ReportBuilderRequest(
            title="Weekly Client Report",
            sections=[
                ReportSectionConfig(section=ReportSectionKey.EXECUTIVE_SUMMARY, enabled=True),
                ReportSectionConfig(section=ReportSectionKey.RISKS, enabled=False),
                ReportSectionConfig(section=ReportSectionKey.READINESS, enabled=True),
            ],
        ),
    )
    assert "Executive Summary" in report.markdown
    assert "## Risks" not in report.markdown
    assert "Readiness" in report.markdown

    pdf, media, ext = export_client_report(report, export_format=ReportExportFormat.PDF)
    assert ext == "pdf"
    assert media == "application/pdf"
    assert pdf.startswith(b"%PDF")

    docx, media, ext = export_client_report(report, export_format=ReportExportFormat.DOCX)
    assert ext == "docx"
    assert "wordprocessingml" in media
    assert docx[:2] == b"PK"


def test_confidence_band_mapping() -> None:
    assert confidence_band_for(Decimal("0.20")).value == "insufficient"
    assert confidence_band_for(Decimal("0.50")).value == "low"
    assert confidence_band_for(Decimal("0.70")).value == "medium"
    assert confidence_band_for(Decimal("0.90")).value == "high"
