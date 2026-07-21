"""Canonical ClientEvidencePack source-fingerprint computation.

Single authoritative algorithm shared by pack assembly and validation.
Never includes generated_at, source_fingerprint, or policy_fingerprint.
"""

from __future__ import annotations

import hashlib
import json
from datetime import date
from uuid import UUID

from app.agents.client_intelligence.contracts import (
    ClientEvidencePack,
    ClientEvidenceReference,
    DataQualityIssue,
    DataQualityState,
    DeliveryEvidenceFacts,
    EvidenceVisibility,
    GovernanceEvidenceFacts,
    KnowledgeEvidenceFacts,
    ProjectIdentityFacts,
    QualityEvidenceFacts,
    ReportingPeriod,
    VisibilityLimitation,
    WorkforceEvidenceFacts,
)

_DATA_QUALITY_RANK: dict[DataQualityState, int] = {
    DataQualityState.COMPLETE: 0,
    DataQualityState.PARTIAL: 1,
    DataQualityState.STALE: 2,
    DataQualityState.CONFLICTING: 3,
    DataQualityState.UNAVAILABLE: 4,
}


def worst_data_quality_state(states: list[DataQualityState]) -> DataQualityState:
    """Deterministic worst-state selection by established precedence."""
    if not states:
        return DataQualityState.COMPLETE
    return max(states, key=lambda state: _DATA_QUALITY_RANK[state])


def workforce_fingerprint_projection(workforce: WorkforceEvidenceFacts) -> dict:
    return workforce.model_dump(mode="json")


def governance_fingerprint_projection(governance: GovernanceEvidenceFacts) -> dict:
    return governance.model_dump(mode="json")


def knowledge_fingerprint_projection(knowledge: KnowledgeEvidenceFacts) -> dict:
    """Knowledge projection for fingerprinting — hashes, not raw chunk/title text."""
    payload = knowledge.model_dump(mode="json")
    for chunk in payload.get("chunks", []):
        chunk.pop("untrusted_text", None)
    for document in payload.get("documents", []):
        document.pop("document_title", None)
    return payload


def _evidence_fingerprint_items(evidence: list[ClientEvidenceReference]) -> list[dict]:
    items: list[dict] = []
    for item in evidence:
        observed = item.observed_at
        items.append(
            {
                "source_agent": item.source_agent.value,
                "source_table": item.source_table,
                "source_row_id": str(item.source_row_id),
                "visibility": item.visibility.value,
                "observed_at": observed.isoformat() if observed is not None else None,
                "claim_keys": sorted({key for key in item.claim_keys if key}),
            }
        )
    return items


def compute_source_fingerprint(
    *,
    project: ProjectIdentityFacts,
    reporting_period: ReportingPeriod,
    visibility_mode: EvidenceVisibility,
    delivery: DeliveryEvidenceFacts,
    quality: QualityEvidenceFacts,
    workforce: WorkforceEvidenceFacts,
    governance: GovernanceEvidenceFacts,
    knowledge: KnowledgeEvidenceFacts,
    evidence: list[ClientEvidenceReference],
    data_quality: list[DataQualityIssue],
    overall_data_quality: DataQualityState,
    visibility_limitations: list[VisibilityLimitation],
    limitations: list[str],
) -> str:
    """Return lowercase SHA-256 of the canonical finalized Phase 1 source payload."""
    payload = {
        "project": project.model_dump(mode="json"),
        "reporting_period": reporting_period.model_dump(mode="json"),
        "visibility_mode": visibility_mode.value,
        "delivery": delivery.model_dump(mode="json"),
        "quality": quality.model_dump(mode="json"),
        "workforce": workforce_fingerprint_projection(workforce),
        "governance": governance_fingerprint_projection(governance),
        "knowledge": knowledge_fingerprint_projection(knowledge),
        "evidence": _evidence_fingerprint_items(evidence),
        "data_quality": [issue.model_dump(mode="json") for issue in data_quality],
        "overall_data_quality": overall_data_quality.value,
        "visibility_limitations": [
            item.model_dump(mode="json") for item in visibility_limitations
        ],
        "limitations": list(limitations),
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def compute_source_fingerprint_from_pack(pack: ClientEvidencePack) -> str:
    """Recompute the canonical digest from a pack (ignores generated_at / fingerprints)."""
    return compute_source_fingerprint(
        project=pack.project,
        reporting_period=pack.reporting_period,
        visibility_mode=pack.visibility_mode,
        delivery=pack.delivery,
        quality=pack.quality,
        workforce=pack.workforce,
        governance=pack.governance,
        knowledge=pack.knowledge,
        evidence=pack.evidence,
        data_quality=pack.data_quality,
        overall_data_quality=pack.overall_data_quality,
        visibility_limitations=pack.visibility_limitations,
        limitations=pack.limitations,
    )


_FIXTURE_ORG_ID = UUID("00000000-0000-4000-8000-000000000001")


def legacy_component_fingerprint(
    *,
    project_id: UUID,
    reporting_period: ReportingPeriod,
    visibility_mode: EvidenceVisibility,
    evidence: list[ClientEvidenceReference],
    workforce: WorkforceEvidenceFacts | None = None,
    governance: GovernanceEvidenceFacts | None = None,
    knowledge: KnowledgeEvidenceFacts | None = None,
    as_of: date | None = None,
) -> str:
    """Canonical fingerprint with empty sibling sections for adapter-level tests."""
    effective_as_of = as_of or reporting_period.as_of
    return compute_source_fingerprint(
        project=ProjectIdentityFacts(
            project_id=project_id,
            org_id=_FIXTURE_ORG_ID,
            project_name="fingerprint-fixture",
            project_status="active",
        ),
        reporting_period=reporting_period,
        visibility_mode=visibility_mode,
        delivery=DeliveryEvidenceFacts(),
        quality=QualityEvidenceFacts(
            current_period=[],
            previous_period=[],
            current_iso_year=effective_as_of.isocalendar().year,
            current_iso_week=effective_as_of.isocalendar().week,
            previous_iso_year=effective_as_of.isocalendar().year,
            previous_iso_week=max(effective_as_of.isocalendar().week - 1, 1),
        ),
        workforce=workforce or WorkforceEvidenceFacts(as_of=effective_as_of),
        governance=governance or GovernanceEvidenceFacts(as_of=effective_as_of),
        knowledge=knowledge
        or KnowledgeEvidenceFacts(
            documents=[],
            chunks=[],
            source_availability=[],
            as_of=effective_as_of,
            project_scope_key="",
        ),
        evidence=evidence,
        data_quality=[],
        overall_data_quality=DataQualityState.COMPLETE,
        visibility_limitations=[],
        limitations=[],
    )
