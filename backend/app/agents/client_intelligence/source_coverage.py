"""Canonical CI-D01–CI-D15 source coverage registry for Client Intelligence.

Each entry describes the governed source contract for Phase 1 evidence assembly.
Adapters must consume an authoritative source when one exists, or return the
stable unavailable reason declared here. Freshness SLAs that are not approved
remain unresolved and must not invent stale classifications by age alone.

CI-D03 Throughput Logs remain partial even when the separate governed plan
series is unavailable; plan absence is a sibling limitation, not a claim that
throughput itself is unavailable.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from app.agents.client_intelligence.contracts import (
    DataQualityIssue,
    DataQualityState,
    EvidenceVisibility,
    SourceAgent,
)
from app.agents.client_intelligence.delivery_trend_contracts import (
    LIMITATION_PLAN_SERIES_UNAVAILABLE,
)
from app.agents.client_intelligence.evidence_validation import _ALLOWED_SOURCE_TABLES


class SourceImplementationState(StrEnum):
    COMPLETE = "complete"
    PARTIAL = "partial"
    UNAVAILABLE = "unavailable"


class SourceStructure(StrEnum):
    STRUCTURED = "structured"
    UNSTRUCTURED = "unstructured"
    HYBRID = "hybrid"


class SourceSensitivity(StrEnum):
    CLIENT_SAFE = "client_safe"
    INTERNAL = "internal"
    MIXED = "mixed"


LIMITATION_WORKFLOW_STATUS_UNAVAILABLE = "WORKFLOW_STATUS_UNAVAILABLE"
LIMITATION_BACKLOG_QUEUE_UNAVAILABLE = "BACKLOG_QUEUE_UNAVAILABLE"
LIMITATION_CLIENT_COMMUNICATION_NOTES_UNAVAILABLE = (
    "CLIENT_COMMUNICATION_NOTES_UNAVAILABLE"
)
LIMITATION_FRESHNESS_SLA_UNRESOLVED = "FRESHNESS_SLA_UNRESOLVED"

# CI-D07 decision evidence: project.status is project identity (CI-D01);
# bottlenecks are risk/bottleneck facts (CI-D10), not an approved Workflow Status
# source contract. No dedicated workflow-status table exists in adapters.
_CI_D07_UNAVAILABLE_DETAIL = (
    "WORKFLOW_STATUS_UNAVAILABLE: no approved Workflow Status source contract. "
    "project.status is CI-D01 identity; bottlenecks remain CI-D10 risk/bottleneck "
    "facts and must not be reused as workflow status."
)


@dataclass(frozen=True, slots=True)
class SourceCoverageEntry:
    requirement_id: str
    title: str
    canonical_owner: SourceAgent
    contributing_owners: tuple[SourceAgent, ...]
    allowed_source_tables: tuple[str, ...]
    structure: SourceStructure
    supported_visibility: tuple[EvidenceVisibility, ...]
    sensitivity: SourceSensitivity
    expected_ownership: str
    freshness_expectation: str
    implementation_state: SourceImplementationState
    unavailable_reason: str | None = None


SOURCE_COVERAGE_REGISTRY: tuple[SourceCoverageEntry, ...] = (
    SourceCoverageEntry(
        requirement_id="CI-D01",
        title="Delivery Tracker",
        canonical_owner=SourceAgent.DELIVERY_PERFORMANCE,
        contributing_owners=(SourceAgent.DELIVERY_PERFORMANCE,),
        allowed_source_tables=(
            "projects",
            "throughput_snapshots",
            "delivery_confidence_scores",
        ),
        structure=SourceStructure.STRUCTURED,
        supported_visibility=(EvidenceVisibility.INTERNAL, EvidenceVisibility.CLIENT_SAFE),
        sensitivity=SourceSensitivity.MIXED,
        expected_ownership="exact project_id and org_id",
        freshness_expectation="unresolved",
        implementation_state=SourceImplementationState.PARTIAL,
        unavailable_reason=None,
    ),
    SourceCoverageEntry(
        requirement_id="CI-D02",
        title="Milestone Plan",
        canonical_owner=SourceAgent.DELIVERY_PERFORMANCE,
        contributing_owners=(SourceAgent.DELIVERY_PERFORMANCE,),
        allowed_source_tables=("milestones",),
        structure=SourceStructure.STRUCTURED,
        supported_visibility=(EvidenceVisibility.INTERNAL, EvidenceVisibility.CLIENT_SAFE),
        sensitivity=SourceSensitivity.MIXED,
        expected_ownership="exact project_id and org_id",
        freshness_expectation="unresolved",
        implementation_state=SourceImplementationState.PARTIAL,
        unavailable_reason=None,
    ),
    SourceCoverageEntry(
        requirement_id="CI-D03",
        title="Throughput Logs",
        canonical_owner=SourceAgent.DELIVERY_PERFORMANCE,
        contributing_owners=(SourceAgent.DELIVERY_PERFORMANCE,),
        allowed_source_tables=("throughput_snapshots",),
        structure=SourceStructure.STRUCTURED,
        supported_visibility=(EvidenceVisibility.INTERNAL, EvidenceVisibility.CLIENT_SAFE),
        sensitivity=SourceSensitivity.MIXED,
        expected_ownership="exact project_id and org_id",
        freshness_expectation="unresolved",
        implementation_state=SourceImplementationState.PARTIAL,
        # Plan series is a separate sibling limitation — not CI-D03 unavailable.
        unavailable_reason=None,
    ),
    SourceCoverageEntry(
        requirement_id="CI-D04",
        title="QA and Rework Data",
        canonical_owner=SourceAgent.QUALITY_INTELLIGENCE,
        contributing_owners=(SourceAgent.QUALITY_INTELLIGENCE,),
        allowed_source_tables=("quality_snapshots",),
        structure=SourceStructure.STRUCTURED,
        supported_visibility=(EvidenceVisibility.INTERNAL, EvidenceVisibility.CLIENT_SAFE),
        sensitivity=SourceSensitivity.MIXED,
        expected_ownership="exact project_id and org_id",
        freshness_expectation="unresolved",
        implementation_state=SourceImplementationState.PARTIAL,
        unavailable_reason=None,
    ),
    SourceCoverageEntry(
        requirement_id="CI-D05",
        title="Resource Allocation",
        canonical_owner=SourceAgent.WORKFORCE_CAPABILITY,
        contributing_owners=(SourceAgent.WORKFORCE_CAPABILITY,),
        allowed_source_tables=("teams", "utilization_snapshots"),
        structure=SourceStructure.STRUCTURED,
        supported_visibility=(EvidenceVisibility.INTERNAL, EvidenceVisibility.CLIENT_SAFE),
        sensitivity=SourceSensitivity.MIXED,
        expected_ownership="exact project_id and org_id",
        freshness_expectation="unresolved",
        implementation_state=SourceImplementationState.PARTIAL,
        unavailable_reason=None,
    ),
    SourceCoverageEntry(
        requirement_id="CI-D06",
        title="SME Coverage",
        canonical_owner=SourceAgent.WORKFORCE_CAPABILITY,
        contributing_owners=(SourceAgent.WORKFORCE_CAPABILITY,),
        allowed_source_tables=("project_skill_requirements", "capability_gaps"),
        structure=SourceStructure.STRUCTURED,
        supported_visibility=(EvidenceVisibility.INTERNAL, EvidenceVisibility.CLIENT_SAFE),
        sensitivity=SourceSensitivity.MIXED,
        expected_ownership="exact project_id and org_id",
        freshness_expectation="unresolved",
        implementation_state=SourceImplementationState.PARTIAL,
        unavailable_reason=None,
    ),
    SourceCoverageEntry(
        requirement_id="CI-D07",
        title="Workflow Status",
        canonical_owner=SourceAgent.DELIVERY_PERFORMANCE,
        contributing_owners=(SourceAgent.DELIVERY_PERFORMANCE,),
        allowed_source_tables=(),
        structure=SourceStructure.STRUCTURED,
        supported_visibility=(EvidenceVisibility.INTERNAL,),
        sensitivity=SourceSensitivity.INTERNAL,
        expected_ownership="exact project_id and org_id",
        freshness_expectation="unresolved",
        implementation_state=SourceImplementationState.UNAVAILABLE,
        unavailable_reason=LIMITATION_WORKFLOW_STATUS_UNAVAILABLE,
    ),
    SourceCoverageEntry(
        requirement_id="CI-D08",
        title="Capacity vs Demand",
        canonical_owner=SourceAgent.WORKFORCE_CAPABILITY,
        contributing_owners=(SourceAgent.WORKFORCE_CAPABILITY,),
        allowed_source_tables=("utilization_snapshots",),
        structure=SourceStructure.STRUCTURED,
        supported_visibility=(EvidenceVisibility.INTERNAL, EvidenceVisibility.CLIENT_SAFE),
        sensitivity=SourceSensitivity.MIXED,
        expected_ownership="exact project_id and org_id",
        freshness_expectation="unresolved",
        implementation_state=SourceImplementationState.PARTIAL,
        unavailable_reason=None,
    ),
    SourceCoverageEntry(
        requirement_id="CI-D09",
        title="Backlog Queue",
        canonical_owner=SourceAgent.DELIVERY_PERFORMANCE,
        contributing_owners=(SourceAgent.DELIVERY_PERFORMANCE,),
        allowed_source_tables=(),
        structure=SourceStructure.STRUCTURED,
        supported_visibility=(EvidenceVisibility.INTERNAL,),
        sensitivity=SourceSensitivity.INTERNAL,
        expected_ownership="exact project_id and org_id",
        freshness_expectation="unresolved",
        implementation_state=SourceImplementationState.UNAVAILABLE,
        unavailable_reason=LIMITATION_BACKLOG_QUEUE_UNAVAILABLE,
    ),
    SourceCoverageEntry(
        requirement_id="CI-D10",
        title="Risk Registers",
        canonical_owner=SourceAgent.DELIVERY_PERFORMANCE,
        contributing_owners=(
            SourceAgent.DELIVERY_PERFORMANCE,
            SourceAgent.PROJECT_GOVERNANCE,
            SourceAgent.QUALITY_INTELLIGENCE,
        ),
        allowed_source_tables=(
            "risk_alerts",
            "bottlenecks",
            "governance_escalations",
            "project_dependencies",
        ),
        structure=SourceStructure.STRUCTURED,
        supported_visibility=(EvidenceVisibility.INTERNAL,),
        sensitivity=SourceSensitivity.INTERNAL,
        expected_ownership="exact project_id and org_id",
        freshness_expectation="unresolved",
        implementation_state=SourceImplementationState.PARTIAL,
        unavailable_reason=None,
    ),
    SourceCoverageEntry(
        requirement_id="CI-D11",
        title="Client SOPs",
        canonical_owner=SourceAgent.OPERATIONAL_KNOWLEDGE,
        contributing_owners=(SourceAgent.OPERATIONAL_KNOWLEDGE,),
        allowed_source_tables=("knowledge_documents", "knowledge_document_chunks"),
        structure=SourceStructure.UNSTRUCTURED,
        supported_visibility=(EvidenceVisibility.INTERNAL, EvidenceVisibility.CLIENT_SAFE),
        sensitivity=SourceSensitivity.MIXED,
        expected_ownership="exact project/org scope via approved Knowledge contracts",
        freshness_expectation="unresolved",
        implementation_state=SourceImplementationState.PARTIAL,
        unavailable_reason=None,
    ),
    SourceCoverageEntry(
        requirement_id="CI-D12",
        title="Training Documents",
        canonical_owner=SourceAgent.OPERATIONAL_KNOWLEDGE,
        contributing_owners=(
            SourceAgent.OPERATIONAL_KNOWLEDGE,
            SourceAgent.WORKFORCE_CAPABILITY,
        ),
        allowed_source_tables=(
            "knowledge_documents",
            "knowledge_document_chunks",
            "training_programs",
            "training_records",
        ),
        structure=SourceStructure.HYBRID,
        supported_visibility=(EvidenceVisibility.INTERNAL, EvidenceVisibility.CLIENT_SAFE),
        sensitivity=SourceSensitivity.MIXED,
        expected_ownership="exact project/org scope via approved Knowledge contracts",
        freshness_expectation="unresolved",
        implementation_state=SourceImplementationState.PARTIAL,
        unavailable_reason=None,
    ),
    SourceCoverageEntry(
        requirement_id="CI-D13",
        title="Project Charters",
        canonical_owner=SourceAgent.OPERATIONAL_KNOWLEDGE,
        contributing_owners=(
            SourceAgent.OPERATIONAL_KNOWLEDGE,
            SourceAgent.PROJECT_GOVERNANCE,
        ),
        allowed_source_tables=(
            "knowledge_documents",
            "project_charters",
            "project_scope_states",
        ),
        structure=SourceStructure.HYBRID,
        supported_visibility=(EvidenceVisibility.INTERNAL, EvidenceVisibility.CLIENT_SAFE),
        sensitivity=SourceSensitivity.MIXED,
        expected_ownership="exact project_id and org_id",
        freshness_expectation="unresolved",
        implementation_state=SourceImplementationState.PARTIAL,
        unavailable_reason=None,
    ),
    SourceCoverageEntry(
        requirement_id="CI-D14",
        title="Client Communication Notes",
        canonical_owner=SourceAgent.OPERATIONAL_KNOWLEDGE,
        contributing_owners=(SourceAgent.OPERATIONAL_KNOWLEDGE,),
        allowed_source_tables=(),
        structure=SourceStructure.UNSTRUCTURED,
        supported_visibility=(EvidenceVisibility.INTERNAL,),
        sensitivity=SourceSensitivity.INTERNAL,
        expected_ownership="exact project_id and org_id",
        freshness_expectation="unresolved",
        implementation_state=SourceImplementationState.UNAVAILABLE,
        unavailable_reason=LIMITATION_CLIENT_COMMUNICATION_NOTES_UNAVAILABLE,
    ),
    SourceCoverageEntry(
        requirement_id="CI-D15",
        title="Escalation Notes",
        canonical_owner=SourceAgent.OPERATIONAL_KNOWLEDGE,
        contributing_owners=(
            SourceAgent.OPERATIONAL_KNOWLEDGE,
            SourceAgent.PROJECT_GOVERNANCE,
        ),
        allowed_source_tables=(
            "knowledge_documents",
            "governance_escalations",
            "governance_actions",
        ),
        structure=SourceStructure.HYBRID,
        supported_visibility=(EvidenceVisibility.INTERNAL, EvidenceVisibility.CLIENT_SAFE),
        sensitivity=SourceSensitivity.MIXED,
        expected_ownership="exact project_id and org_id",
        freshness_expectation="unresolved",
        implementation_state=SourceImplementationState.PARTIAL,
        unavailable_reason=None,
    ),
)


def source_coverage_by_id() -> dict[str, SourceCoverageEntry]:
    return {entry.requirement_id: entry for entry in SOURCE_COVERAGE_REGISTRY}


def adapter_name_for_owner(owner: SourceAgent) -> str:
    return {
        SourceAgent.DELIVERY_PERFORMANCE: "delivery_adapter",
        SourceAgent.QUALITY_INTELLIGENCE: "quality_adapter",
        SourceAgent.WORKFORCE_CAPABILITY: "workforce_adapter",
        SourceAgent.PROJECT_GOVERNANCE: "governance_adapter",
        SourceAgent.OPERATIONAL_KNOWLEDGE: "knowledge_adapter",
    }[owner]


def requirement_accepts_source(
    requirement_id: str,
    *,
    source_table: str,
    source_agent: SourceAgent,
) -> bool:
    """Exact requirement↔table↔owner acceptance (not a union check)."""
    entry = source_coverage_by_id().get(requirement_id)
    if entry is None:
        return False
    if entry.implementation_state == SourceImplementationState.UNAVAILABLE:
        return False
    if source_table not in entry.allowed_source_tables:
        return False
    return source_agent in entry.contributing_owners


def exact_requirement_mappings() -> tuple[dict[str, object], ...]:
    """One mapping row per requirement for contract-closure tests."""
    rows: list[dict[str, object]] = []
    for entry in SOURCE_COVERAGE_REGISTRY:
        rows.append(
            {
                "requirement_id": entry.requirement_id,
                "title": entry.title,
                "canonical_owner": entry.canonical_owner,
                "contributing_owners": entry.contributing_owners,
                "allowed_source_tables": entry.allowed_source_tables,
                "adapter": adapter_name_for_owner(entry.canonical_owner),
                "supported_visibility": entry.supported_visibility,
                "implementation_state": entry.implementation_state,
                "unavailable_reason": entry.unavailable_reason,
            }
        )
    return tuple(rows)


def pack_evidence_requirement_pairs(
    evidence: list,
) -> list[tuple[str, str, SourceAgent]]:
    """Return (requirement_id, source_table, source_agent) matches for pack refs."""
    matches: list[tuple[str, str, SourceAgent]] = []
    for ref in evidence:
        found = False
        for entry in SOURCE_COVERAGE_REGISTRY:
            if requirement_accepts_source(
                entry.requirement_id,
                source_table=ref.source_table,
                source_agent=ref.source_agent,
            ):
                matches.append(
                    (entry.requirement_id, ref.source_table, ref.source_agent)
                )
                found = True
        if not found and ref.source_table:
            matches.append(("UNMAPPED", ref.source_table, ref.source_agent))
    return matches


def blocked_source_entries() -> tuple[SourceCoverageEntry, ...]:
    return tuple(
        entry
        for entry in SOURCE_COVERAGE_REGISTRY
        if entry.implementation_state == SourceImplementationState.UNAVAILABLE
    )


def registry_allowed_source_tables() -> frozenset[str]:
    tables: set[str] = set()
    for entry in SOURCE_COVERAGE_REGISTRY:
        tables.update(entry.allowed_source_tables)
    return frozenset(tables)


def adapter_allowed_source_tables() -> frozenset[str]:
    tables: set[str] = set()
    for owned in _ALLOWED_SOURCE_TABLES.values():
        tables.update(owned)
    return frozenset(tables)


def explicit_unavailable_pack_signals() -> tuple[list[str], list[DataQualityIssue]]:
    """Stable limitations and DQ issues for blocked sources and sibling gaps."""
    limitations: list[str] = [
        LIMITATION_PLAN_SERIES_UNAVAILABLE,
        LIMITATION_FRESHNESS_SLA_UNRESOLVED,
    ]
    issues: list[DataQualityIssue] = [
        DataQualityIssue(
            source="throughput_plan_series",
            state=DataQualityState.UNAVAILABLE,
            detail=(
                "Governed plan series is unavailable; throughput actual/forecast "
                "(CI-D03) must not be interpreted as plan."
            ),
            observed_at=None,
        ),
        DataQualityIssue(
            source="freshness_sla",
            state=DataQualityState.PARTIAL,
            detail=(
                "No approved freshness SLA is configured; Client Intelligence does not "
                "classify sources stale by age alone."
            ),
            observed_at=None,
        ),
    ]
    for entry in blocked_source_entries():
        reason = entry.unavailable_reason or f"{entry.requirement_id}_UNAVAILABLE"
        limitations.append(reason)
        detail = (
            _CI_D07_UNAVAILABLE_DETAIL
            if entry.requirement_id == "CI-D07"
            else (
                f"{entry.requirement_id} ({entry.title}) is explicitly unavailable: "
                f"{reason}."
            )
        )
        issues.append(
            DataQualityIssue(
                source=entry.requirement_id.lower().replace("-", "_"),
                state=DataQualityState.UNAVAILABLE,
                detail=detail,
                observed_at=None,
            )
        )
    return limitations, issues
