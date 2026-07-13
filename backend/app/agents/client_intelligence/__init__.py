"""Client Intelligence Agent — public contracts and evidence-pack assembler."""

from app.agents.client_intelligence.contracts import (
    BottleneckFacts,
    ClientEvidencePack,
    ClientEvidenceReference,
    DataQualityIssue,
    DataQualityState,
    DeliveryConfidenceFacts,
    DeliveryEvidenceFacts,
    EvidenceVisibility,
    MilestoneFacts,
    ProjectIdentityFacts,
    QualityEvidenceFacts,
    QualitySnapshotFacts,
    ReportingPeriod,
    RiskAlertFacts,
    SourceAgent,
    ThroughputSnapshotFacts,
    VisibilityLimitation,
)
from app.agents.client_intelligence.evidence_pack import build_client_evidence_pack
from app.agents.client_intelligence.quality_adapter import load_quality_evidence
from app.agents.client_intelligence.reporting_period import resolve_reporting_period
from app.agents.client_intelligence.visibility import (
    ClientVisibilityPolicy,
    ClientVisibleMetric,
    load_client_visibility_policy,
)

__all__ = [
    "BottleneckFacts",
    "ClientEvidencePack",
    "ClientEvidenceReference",
    "ClientVisibilityPolicy",
    "ClientVisibleMetric",
    "DataQualityIssue",
    "DataQualityState",
    "DeliveryConfidenceFacts",
    "DeliveryEvidenceFacts",
    "EvidenceVisibility",
    "MilestoneFacts",
    "ProjectIdentityFacts",
    "QualityEvidenceFacts",
    "QualitySnapshotFacts",
    "ReportingPeriod",
    "RiskAlertFacts",
    "SourceAgent",
    "ThroughputSnapshotFacts",
    "VisibilityLimitation",
    "build_client_evidence_pack",
    "load_client_visibility_policy",
    "load_quality_evidence",
    "resolve_reporting_period",
]
