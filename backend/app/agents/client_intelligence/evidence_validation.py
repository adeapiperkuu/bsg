"""Deterministic ClientEvidencePack integrity, redaction, and consistency validation.

Defense-in-depth only: project/org authorization remains upstream via
``get_visible_project``. This module never invents intelligence and never
embeds raw source text, titles, names, or notes into validation details.

Finalization never repairs or clamps timestamps — invalid stamps remain for
fail-closed validation.
"""

from __future__ import annotations

import hmac
import re
from datetime import UTC, date, datetime, time
from typing import Any
from uuid import UUID

from app.agents.client_intelligence.contracts import (
    ClientEvidencePack,
    ClientEvidenceReference,
    DataQualityIssue,
    DataQualityState,
    EvidencePackValidationResult,
    EvidenceValidationIssue,
    EvidenceVisibility,
    KnowledgeEvidenceFacts,
    SourceAgent,
    VisibilityLimitation,
)
from app.agents.client_intelligence.evidence_fingerprint import (
    compute_source_fingerprint_from_pack,
    worst_data_quality_state,
)
from app.db.models import AppRole

_SHA256_HEX = re.compile(r"^[0-9a-f]{64}$")

# Phase 1 source-agent / source-table allowlist (explicit; no arbitrary tables).
_ALLOWED_SOURCE_TABLES: dict[SourceAgent, frozenset[str]] = {
    SourceAgent.DELIVERY_PERFORMANCE: frozenset(
        {
            "projects",
            "milestones",
            "throughput_snapshots",
            "delivery_confidence_scores",
            "risk_alerts",
            "bottlenecks",
        }
    ),
    SourceAgent.QUALITY_INTELLIGENCE: frozenset({"quality_snapshots"}),
    SourceAgent.WORKFORCE_CAPABILITY: frozenset(
        {
            "utilization_snapshots",
            "project_skill_requirements",
            "training_programs",
            "training_records",
            "capability_gaps",
        }
    ),
    SourceAgent.PROJECT_GOVERNANCE: frozenset(
        {
            "project_scope_states",
            "project_charters",
            "project_dependencies",
            "governance_actions",
            "governance_escalations",
        }
    ),
    SourceAgent.OPERATIONAL_KNOWLEDGE: frozenset(
        {
            "knowledge_documents",
            "knowledge_document_chunks",
        }
    ),
}

# Allowed claim keys per source table. internal_only keys are forbidden in CLIENT_SAFE.
_CLAIM_KEY_REGISTRY: dict[str, dict[str, frozenset[str]]] = {
    "projects": {
        "allowed": frozenset({"project_id", "project_name", "project_status"}),
        "required": frozenset({"project_id", "project_name", "project_status"}),
        "internal_only": frozenset(),
    },
    "milestones": {
        "allowed": frozenset(
            {"milestone_id", "milestone_name", "milestone_status", "planned_date", "actual_date"}
        ),
        "required": frozenset(
            {"milestone_id", "milestone_name", "milestone_status", "planned_date"}
        ),
        "internal_only": frozenset(),
    },
    "throughput_snapshots": {
        "allowed": frozenset(
            {"snapshot_date", "rolling_7day_units", "units_completed", "units_forecast"}
        ),
        "required": frozenset({"snapshot_date"}),
        "internal_only": frozenset({"units_completed", "units_forecast"}),
    },
    "delivery_confidence_scores": {
        "allowed": frozenset(
            {
                "score_pct",
                "confidence_status",
                "forecast_completion_date",
                "model_version",
            }
        ),
        "required": frozenset({"score_pct", "confidence_status", "forecast_completion_date"}),
        "internal_only": frozenset({"model_version"}),
    },
    "risk_alerts": {
        "allowed": frozenset(
            {"risk_id", "risk_title", "risk_tier", "alert_type", "status", "risk_detail"}
        ),
        "required": frozenset({"risk_id", "risk_title", "risk_tier", "alert_type", "status"}),
        "internal_only": frozenset({"risk_detail"}),
    },
    "bottlenecks": {
        "allowed": frozenset(
            {"bottleneck_id", "bottleneck_title", "status", "bottleneck_detail"}
        ),
        "required": frozenset({"bottleneck_id", "bottleneck_title", "status"}),
        "internal_only": frozenset({"bottleneck_detail"}),
    },
    "quality_snapshots": {
        "allowed": frozenset(
            {
                "iso_year",
                "iso_week",
                "gold_set_accuracy_pct",
                "rework_rate_pct",
                "team_id",
                "iaa_krippendorff_alpha",
                "evaluated_item_count",
                "has_drift_alert",
                "confidence_level",
            }
        ),
        "required": frozenset({"iso_year", "iso_week"}),
        "internal_only": frozenset(
            {
                "team_id",
                "iaa_krippendorff_alpha",
                "evaluated_item_count",
                "has_drift_alert",
                "confidence_level",
            }
        ),
    },
    "utilization_snapshots": {
        "allowed": frozenset(
            {
                "latest_snapshot_date",
                "allocated_hours_total",
                "available_hours_total",
                "utilization_pct",
                "teams_with_utilization",
                "teams_without_utilization",
            }
        ),
        "required": frozenset(),
        "internal_only": frozenset(),
    },
    "project_skill_requirements": {
        "allowed": frozenset(
            {
                "requirement_count",
                "covered_requirement_count",
                "partial_requirement_count",
                "gap_requirement_count",
                "unavailable_requirement_count",
                "required_headcount_slots",
                "available_headcount_slots",
                "required_sme_slots",
                "available_sme_slots",
                "requirement_id",
                "skill_id",
                "required_proficiency_level",
                "priority",
                "required_headcount",
                "available_headcount",
                "required_sme_count",
                "available_sme_count",
                "coverage_status",
            }
        ),
        "required": frozenset(),
        "internal_only": frozenset(
            {
                "requirement_id",
                "skill_id",
                "required_proficiency_level",
                "priority",
                "required_headcount",
                "available_headcount",
                "required_sme_count",
                "available_sme_count",
                "coverage_status",
            }
        ),
        "required_internal": frozenset({"requirement_id"}),
    },
    "training_programs": {
        "allowed": frozenset(
            {
                "mandatory_program_count",
                "required_assignment_count",
                "completed_assignment_count",
                "incomplete_assignment_count",
                "expired_or_failed_assignment_count",
                "completion_pct",
            }
        ),
        "required": frozenset(),
        "internal_only": frozenset(),
    },
    "training_records": {
        "allowed": frozenset(
            {
                "mandatory_program_count",
                "required_assignment_count",
                "completed_assignment_count",
                "incomplete_assignment_count",
                "expired_or_failed_assignment_count",
                "completion_pct",
            }
        ),
        "required": frozenset(),
        "internal_only": frozenset(),
    },
    "capability_gaps": {
        "allowed": frozenset(
            {
                "open_gap_counts",
                "gap_id",
                "gap_type",
                "severity",
                "status",
                "team_id",
                "skill_id",
                "detected_at",
                "resolved_at",
            }
        ),
        "required": frozenset(),
        "internal_only": frozenset(
            {
                "gap_id",
                "gap_type",
                "severity",
                "status",
                "team_id",
                "skill_id",
                "detected_at",
                "resolved_at",
            }
        ),
        "required_internal": frozenset({"gap_id"}),
    },
    "project_scope_states": {
        "allowed": frozenset({"scope_status", "version_label", "scope_present"}),
        "required": frozenset({"scope_status", "version_label", "scope_present"}),
        "internal_only": frozenset(),
    },
    "project_charters": {
        "allowed": frozenset(
            {
                "version",
                "status",
                "visibility",
                "approved_at",
                "approved_charter_present",
                "client_safe_charter_present",
            }
        ),
        "required": frozenset({"version", "status", "visibility"}),
        "internal_only": frozenset(),
    },
    "project_dependencies": {
        "allowed": frozenset(
            {
                "dependency_count",
                "open_dependency_count",
                "blocking_dependency_count",
                "overdue_dependency_count",
                "client_action_dependency_count",
                "dependency_id",
                "dependency_type",
                "status",
                "due_date",
                "resolved_at",
            }
        ),
        "required": frozenset(),
        "internal_only": frozenset(
            {"dependency_id", "dependency_type", "status", "due_date", "resolved_at"}
        ),
        "required_internal": frozenset({"dependency_id"}),
    },
    "governance_actions": {
        "allowed": frozenset(
            {
                "action_count",
                "open_action_count",
                "overdue_action_count",
                "action_id",
                "status",
                "due_date",
                "completed_at",
            }
        ),
        "required": frozenset(),
        "internal_only": frozenset({"action_id", "status", "due_date", "completed_at"}),
        "required_internal": frozenset({"action_id"}),
    },
    "governance_escalations": {
        "allowed": frozenset(
            {
                "escalation_count",
                "open_escalation_count",
                "critical_escalation_count",
                "escalation_id",
                "severity",
                "status",
                "raised_at",
                "resolved_at",
                "source_type",
            }
        ),
        "required": frozenset(),
        "internal_only": frozenset(
            {
                "escalation_id",
                "severity",
                "status",
                "raised_at",
                "resolved_at",
                "source_type",
            }
        ),
        "required_internal": frozenset({"escalation_id"}),
    },
    "knowledge_documents": {
        "allowed": frozenset(
            {
                "source_type",
                "document_type",
                "version",
                "visibility",
                "effective_date",
                "approved_at",
                "indexed_at",
                "active_version_id",
                "document_title",
            }
        ),
        "required": frozenset(
            {
                "source_type",
                "version",
                "visibility",
                "approved_at",
                "indexed_at",
                "active_version_id",
            }
        ),
        "internal_only": frozenset({"document_title"}),
    },
    "knowledge_document_chunks": {
        "allowed": frozenset(
            {
                "source_type",
                "document_version",
                "chunk_index",
                "page_number",
                "content_sha256",
                "section_label",
            }
        ),
        "required": frozenset(
            {"source_type", "document_version", "chunk_index", "content_sha256"}
        ),
        "internal_only": frozenset({"section_label"}),
    },
}

_CLIENT_SAFE_FORBIDDEN_KEYS = frozenset(
    {
        "document_title",
        "section_label",
        "file_name",
        "file_url",
        "storage_path",
        "checksum",
        "checksum_sha256",
        "content_checksum",
        "embedding",
        "embeddings",
        "token_count",
        "extracted_text",
        "executive_summary",
        "key_procedures",
        "owner_approver",
        "approved_by",
        "uploaded_by",
        "reviewer_id",
        "reviewer_ids",
        "reviewer_name",
        "annotator_id",
        "annotator_ids",
        "annotator_name",
        "full_name",
        "worker_id",
        "user_id",
        "team_name",
        "notes",
        "mitigation_detail",
        "mitigation_details",
        "generated_text",
        "model_version",
        "scope_state_id",
        "project_linkage",
        "folder_id",
    }
)

_UNTRUSTED_TEXT_ALLOWED_PATH = "knowledge.chunks.*.untrusted_text"
_KNOWLEDGE_REQUIREMENT_IDS = ("CI-D11", "CI-D12", "CI-D13", "CI-D14", "CI-D15")


class EvidencePackIntegrityError(Exception):
    """Security/integrity failure for a ClientEvidencePack.

    Messages must remain generic — never include raw source values.
    """

    def __init__(self, result: EvidencePackValidationResult) -> None:
        self.result = result
        super().__init__("Client evidence pack failed integrity validation.")


def _as_of_end(as_of: date) -> datetime:
    return datetime.combine(as_of, time.max, tzinfo=UTC)


def _observed_sort_key(value: datetime | None) -> tuple[int, str]:
    if value is None:
        return (0, "")
    return (1, value.isoformat())


def finalize_evidence_references(
    evidence: list[ClientEvidenceReference],
) -> list[ClientEvidenceReference]:
    """Sort and deterministically merge compatible duplicates; preserve conflicts.

    Never clamps, erases, or timezone-repairs ``observed_at``.
    """
    normalized: list[ClientEvidenceReference] = []
    for item in evidence:
        keys = sorted({key for key in item.claim_keys if key})
        normalized.append(item.model_copy(update={"claim_keys": keys}))

    normalized.sort(
        key=lambda item: (
            item.source_agent.value,
            item.source_table,
            str(item.source_row_id),
            item.visibility.value,
            item.description,
            _observed_sort_key(item.observed_at),
            tuple(item.claim_keys),
        )
    )

    result: list[ClientEvidenceReference] = []
    index = 0
    while index < len(normalized):
        current = normalized[index]
        group_key = (
            current.source_agent.value,
            current.source_table,
            str(current.source_row_id),
            current.visibility.value,
        )
        group = [current]
        index += 1
        while index < len(normalized):
            candidate = normalized[index]
            candidate_key = (
                candidate.source_agent.value,
                candidate.source_table,
                str(candidate.source_row_id),
                candidate.visibility.value,
            )
            if candidate_key != group_key:
                break
            group.append(candidate)
            index += 1

        if len(group) == 1:
            result.append(group[0])
            continue

        descriptions = {item.description for item in group}
        timestamps = {item.observed_at for item in group}
        if len(descriptions) == 1 and len(timestamps) == 1:
            merged_keys = sorted({key for item in group for key in item.claim_keys})
            result.append(group[0].model_copy(update={"claim_keys": merged_keys}))
            continue

        # Conflicting metadata — preserve all members in deterministic order for
        # fail-closed validation (duplicate key after finalization).
        result.extend(group)

    return result


def finalize_data_quality_issues(
    issues: list[DataQualityIssue],
) -> list[DataQualityIssue]:
    """Deterministic sort only — never alters observed_at."""
    return sorted(
        issues,
        key=lambda item: (
            item.source,
            item.state.value,
            item.detail,
            _observed_sort_key(item.observed_at),
        ),
    )


def finalize_visibility_limitations(
    limitations: list[VisibilityLimitation],
) -> list[VisibilityLimitation]:
    return sorted(
        limitations,
        key=lambda item: (item.source, item.reason, item.detail),
    )


def finalize_general_limitations(limitations: list[str]) -> list[str]:
    """Return a deterministic sorted unique collection."""
    return sorted(set(limitations))


def finalize_pack_collections(
    *,
    evidence: list[ClientEvidenceReference],
    data_quality: list[DataQualityIssue],
    visibility_limitations: list[VisibilityLimitation],
    limitations: list[str],
    as_of: date | None = None,
) -> tuple[
    list[ClientEvidenceReference],
    list[DataQualityIssue],
    list[VisibilityLimitation],
    list[str],
]:
    """Canonical finalization applied before fingerprinting and return.

    ``as_of`` is accepted for call-site compatibility and is not used to mutate
    timestamps.
    """
    _ = as_of
    return (
        finalize_evidence_references(evidence),
        finalize_data_quality_issues(data_quality),
        finalize_visibility_limitations(visibility_limitations),
        finalize_general_limitations(limitations),
    )


def validate_client_evidence_pack(
    pack: ClientEvidencePack,
    *,
    role: AppRole,
) -> EvidencePackValidationResult:
    """Validate pack integrity, visibility, and Phase 1 cross-adapter consistency."""
    errors: list[EvidenceValidationIssue] = []
    warnings: list[EvidenceValidationIssue] = []

    _validate_core_invariants(pack, errors)
    _validate_role_visibility(pack, role=role, errors=errors)
    _validate_source_allowlist(pack, errors)
    _validate_claim_keys(pack, errors)
    _validate_project_evidence(pack, errors)
    _validate_delivery_evidence(pack, errors)
    _validate_quality_evidence(pack, errors)
    _validate_workforce_evidence(pack, errors)
    _validate_governance_evidence(pack, errors)
    _validate_knowledge_evidence(pack, errors)
    _validate_fact_timestamps(pack, errors)
    _validate_cross_adapter_client_safe(pack, errors, warnings)
    if pack.visibility_mode == EvidenceVisibility.CLIENT_SAFE:
        _validate_client_safe_redaction(pack, errors)
    _validate_overall_data_quality(pack, errors)
    _validate_delivery_confidence_quality_consistency(pack, errors)
    _validate_source_fingerprint_integrity(pack, errors)

    return EvidencePackValidationResult(
        is_valid=len(errors) == 0,
        errors=errors,
        warnings=warnings,
    )


def _issue(
    code: str,
    detail: str,
    *,
    source: str | None = None,
    evidence_id: UUID | None = None,
) -> EvidenceValidationIssue:
    return EvidenceValidationIssue(
        code=code,
        detail=detail,
        source=source,
        evidence_id=evidence_id,
    )


def _check_observed_at(
    value: datetime | None,
    *,
    as_of_end: datetime,
    code_prefix: str,
    source: str,
    evidence_id: UUID | None,
    errors: list[EvidenceValidationIssue],
) -> None:
    if value is None:
        return
    if value.tzinfo is None:
        errors.append(
            _issue(
                f"{code_prefix}_naive_observed_at",
                "observed_at must be timezone-aware.",
                source=source,
                evidence_id=evidence_id,
            )
        )
        return
    if value > as_of_end:
        errors.append(
            _issue(
                f"{code_prefix}_future_observed_at",
                "observed_at is after the reporting-period as_of end.",
                source=source,
                evidence_id=evidence_id,
            )
        )


def _validate_overall_data_quality(
    pack: ClientEvidencePack,
    errors: list[EvidenceValidationIssue],
) -> None:
    expected = worst_data_quality_state([issue.state for issue in pack.data_quality])
    if pack.overall_data_quality != expected:
        errors.append(
            _issue(
                "overall_data_quality_mismatch",
                "overall_data_quality does not match the derived data-quality state.",
                source="overall_data_quality",
            )
        )


def _validate_delivery_confidence_quality_consistency(
    pack: ClientEvidencePack,
    errors: list[EvidenceValidationIssue],
) -> None:
    """Fail closed when Delivery Confidence presence disagrees with pack quality."""
    aliases = frozenset({"delivery_confidence", "delivery_confidence_scores"})
    issues = [item for item in pack.data_quality if item.source in aliases]
    if not issues:
        return
    states = {item.state for item in issues}
    if len(states) != 1:
        errors.append(
            _issue(
                "delivery_confidence_quality_ambiguous",
                "Delivery Confidence data-quality records conflict.",
                source="delivery_confidence_scores",
            )
        )
        return
    state = next(iter(states))
    present = pack.delivery.latest_delivery_confidence is not None
    if state == DataQualityState.UNAVAILABLE and present:
        errors.append(
            _issue(
                "delivery_confidence_quality_presence_mismatch",
                "Delivery Confidence fact presence disagrees with UNAVAILABLE quality.",
                source="delivery_confidence_scores",
            )
        )
    elif state != DataQualityState.UNAVAILABLE and not present:
        errors.append(
            _issue(
                "delivery_confidence_quality_absence_mismatch",
                "Delivery Confidence is absent without matching UNAVAILABLE quality.",
                source="delivery_confidence_scores",
            )
        )


def _validate_source_fingerprint_integrity(
    pack: ClientEvidencePack,
    errors: list[EvidenceValidationIssue],
) -> None:
    if not _SHA256_HEX.match(pack.source_fingerprint):
        return
    expected = compute_source_fingerprint_from_pack(pack)
    if not hmac.compare_digest(pack.source_fingerprint, expected):
        errors.append(
            _issue(
                "fingerprint_mismatch",
                "source_fingerprint does not match the finalized pack contents.",
                source="source_fingerprint",
            )
        )


def _validate_core_invariants(
    pack: ClientEvidencePack,
    errors: list[EvidenceValidationIssue],
) -> None:
    period = pack.reporting_period
    if not (period.start_date <= period.as_of <= period.end_date):
        errors.append(
            _issue(
                "reporting_period_as_of",
                "reporting_period.as_of is outside the reporting period window.",
                source="reporting_period",
            )
        )
    if not _SHA256_HEX.match(pack.source_fingerprint):
        errors.append(
            _issue(
                "fingerprint_invalid",
                "source_fingerprint must be a 64-character lowercase SHA-256 hex digest.",
                source="source_fingerprint",
            )
        )
    if pack.policy_fingerprint is not None and not _SHA256_HEX.match(pack.policy_fingerprint):
        errors.append(
            _issue(
                "policy_fingerprint_invalid",
                "policy_fingerprint must be null or a 64-character lowercase SHA-256 hex digest.",
                source="policy_fingerprint",
            )
        )
    if pack.generated_at.tzinfo is None:
        errors.append(
            _issue(
                "generated_at_naive",
                "generated_at must be timezone-aware.",
                source="generated_at",
            )
        )

    as_of_end = _as_of_end(period.as_of)
    seen_refs: set[tuple[str, str, str, str]] = set()
    for item in pack.evidence:
        if not item.source_table.strip():
            errors.append(
                _issue(
                    "evidence_table_empty",
                    "Evidence reference source_table must be non-empty.",
                    source="evidence",
                )
            )
        if not item.claim_keys:
            errors.append(
                _issue(
                    "evidence_claim_keys_empty",
                    "Evidence reference claim_keys must be non-empty.",
                    source=item.source_table,
                    evidence_id=item.source_row_id,
                )
            )
        if len(item.claim_keys) != len(set(item.claim_keys)):
            errors.append(
                _issue(
                    "evidence_claim_keys_duplicate",
                    "Evidence reference claim_keys contain duplicates.",
                    source=item.source_table,
                    evidence_id=item.source_row_id,
                )
            )
        key = (
            item.source_agent.value,
            item.source_table,
            str(item.source_row_id),
            item.visibility.value,
        )
        if key in seen_refs:
            errors.append(
                _issue(
                    "evidence_duplicate_conflict",
                    "Conflicting or duplicate evidence references remain after finalization.",
                    source=item.source_table,
                    evidence_id=item.source_row_id,
                )
            )
        seen_refs.add(key)
        _check_observed_at(
            item.observed_at,
            as_of_end=as_of_end,
            code_prefix="evidence",
            source=item.source_table,
            evidence_id=item.source_row_id,
            errors=errors,
        )

    for issue in pack.data_quality:
        _check_observed_at(
            issue.observed_at,
            as_of_end=as_of_end,
            code_prefix="data_quality",
            source=issue.source,
            evidence_id=None,
            errors=errors,
        )

    if pack.evidence != finalize_evidence_references(pack.evidence):
        errors.append(
            _issue(
                "evidence_order",
                "Evidence references are not in deterministic finalized order.",
                source="evidence",
            )
        )
    if pack.data_quality != finalize_data_quality_issues(pack.data_quality):
        errors.append(
            _issue(
                "data_quality_order",
                "Data-quality issues are not in deterministic finalized order.",
                source="data_quality",
            )
        )
    if pack.visibility_limitations != finalize_visibility_limitations(
        pack.visibility_limitations
    ):
        errors.append(
            _issue(
                "visibility_limitation_order",
                "Visibility limitations are not in deterministic finalized order.",
                source="visibility_limitations",
            )
        )
    if pack.limitations != finalize_general_limitations(pack.limitations):
        errors.append(
            _issue(
                "limitation_order",
                "General limitations are not in deterministic finalized order.",
                source="limitations",
            )
        )


def _validate_role_visibility(
    pack: ClientEvidencePack,
    *,
    role: AppRole,
    errors: list[EvidenceValidationIssue],
) -> None:
    if role == AppRole.CLIENT and pack.visibility_mode != EvidenceVisibility.CLIENT_SAFE:
        errors.append(
            _issue(
                "client_role_internal_pack",
                "CLIENT role may only receive CLIENT_SAFE evidence packs.",
                source="visibility_mode",
            )
        )
    if pack.visibility_mode == EvidenceVisibility.CLIENT_SAFE:
        for item in pack.evidence:
            if item.visibility != EvidenceVisibility.CLIENT_SAFE:
                errors.append(
                    _issue(
                        "internal_evidence_in_client_safe",
                        "CLIENT_SAFE packs must not contain INTERNAL evidence references.",
                        source=item.source_table,
                        evidence_id=item.source_row_id,
                    )
                )


def _validate_source_allowlist(
    pack: ClientEvidencePack,
    errors: list[EvidenceValidationIssue],
) -> None:
    for item in pack.evidence:
        allowed = _ALLOWED_SOURCE_TABLES.get(item.source_agent)
        if allowed is None or item.source_table not in allowed:
            errors.append(
                _issue(
                    "source_mapping_invalid",
                    "Unsupported source-agent and source-table combination.",
                    source=item.source_table,
                    evidence_id=item.source_row_id,
                )
            )


def _validate_claim_keys(
    pack: ClientEvidencePack,
    errors: list[EvidenceValidationIssue],
) -> None:
    client_safe = pack.visibility_mode == EvidenceVisibility.CLIENT_SAFE
    for item in pack.evidence:
        policy = _CLAIM_KEY_REGISTRY.get(item.source_table)
        if policy is None:
            errors.append(
                _issue(
                    "claim_key_registry_missing",
                    "Source table has no claim-key registry entry.",
                    source=item.source_table,
                    evidence_id=item.source_row_id,
                )
            )
            continue
        allowed = policy["allowed"]
        internal_only = policy.get("internal_only", frozenset())
        required = set(policy.get("required", frozenset()))
        if not client_safe:
            required |= set(policy.get("required_internal", frozenset()))
        for key in item.claim_keys:
            if key not in allowed:
                errors.append(
                    _issue(
                        "claim_key_invalid",
                        "Evidence claim key is not allowed for this source table.",
                        source=item.source_table,
                        evidence_id=item.source_row_id,
                    )
                )
            elif client_safe and key in internal_only:
                errors.append(
                    _issue(
                        "claim_key_internal_in_client_safe",
                        "CLIENT_SAFE evidence claims an internal-only field.",
                        source=item.source_table,
                        evidence_id=item.source_row_id,
                    )
                )
        missing = required - set(item.claim_keys)
        # Row-level internal required keys apply when internal identity keys are claimed
        # or when visibility is INTERNAL for tables that always project row facts.
        if missing and (
            not client_safe
            or policy.get("required")
        ):
            if client_safe:
                missing &= set(policy.get("required", frozenset()))
            if missing:
                errors.append(
                    _issue(
                        "claim_key_required_missing",
                        "Evidence reference is missing required claim keys.",
                        source=item.source_table,
                        evidence_id=item.source_row_id,
                    )
                )


def claim_key_is_allowed(
    source_table: str,
    claim_key: str,
    *,
    client_safe: bool,
) -> bool:
    """Return whether ``claim_key`` is allowed for ``source_table`` in this mode.

    Uses the canonical claim-key registry (single source of truth).
    """
    policy = _CLAIM_KEY_REGISTRY.get(source_table)
    if policy is None:
        return False
    if claim_key not in policy["allowed"]:
        return False
    return not (
        client_safe and claim_key in policy.get("internal_only", frozenset())
    )


def source_agent_owns_table(source_agent: SourceAgent, source_table: str) -> bool:
    """True when the canonical Phase 1 source-agent allowlist owns ``source_table``."""
    allowed = _ALLOWED_SOURCE_TABLES.get(source_agent)
    return allowed is not None and source_table in allowed


def reference_supports_claim_keys(
    reference: ClientEvidenceReference,
    claim_keys: list[str] | tuple[str, ...] | frozenset[str],
    *,
    client_safe: bool,
) -> bool:
    """True when every requested claim key is on the reference and registry-allowed."""
    if not claim_keys:
        return False
    present = set(reference.claim_keys)
    for key in claim_keys:
        if key not in present:
            return False
        if not claim_key_is_allowed(
            reference.source_table, key, client_safe=client_safe
        ):
            return False
    return True


def _evidence_for(pack: ClientEvidencePack, table: str) -> list[ClientEvidenceReference]:
    return [item for item in pack.evidence if item.source_table == table]


def _evidence_ids(pack: ClientEvidencePack, table: str) -> set[UUID]:
    return {item.source_row_id for item in _evidence_for(pack, table)}


def _validate_project_evidence(
    pack: ClientEvidencePack,
    errors: list[EvidenceValidationIssue],
) -> None:
    refs = _evidence_for(pack, "projects")
    if len(refs) != 1:
        errors.append(
            _issue(
                "project_evidence_count",
                "Pack must include exactly one projects evidence reference.",
                source="projects",
            )
        )
        return
    ref = refs[0]
    if ref.source_agent != SourceAgent.DELIVERY_PERFORMANCE:
        errors.append(
            _issue(
                "project_evidence_agent",
                "projects evidence must use the Delivery Performance source agent.",
                source="projects",
                evidence_id=ref.source_row_id,
            )
        )
    if ref.source_row_id != pack.project.project_id:
        errors.append(
            _issue(
                "project_evidence_row_mismatch",
                "projects evidence row ID must match pack.project.project_id.",
                source="projects",
                evidence_id=ref.source_row_id,
            )
        )
    required = {"project_id", "project_name", "project_status"}
    if not required.issubset(set(ref.claim_keys)):
        errors.append(
            _issue(
                "project_evidence_claim_keys",
                "projects evidence must claim projected project identity fields.",
                source="projects",
                evidence_id=ref.source_row_id,
            )
        )


def _validate_delivery_evidence(
    pack: ClientEvidencePack,
    errors: list[EvidenceValidationIssue],
) -> None:
    delivery = pack.delivery
    milestone_ids = {item.id for item in delivery.milestones}
    milestone_evidence = _evidence_ids(pack, "milestones")
    if milestone_ids != milestone_evidence:
        errors.append(
            _issue(
                "milestone_evidence_mismatch",
                "Milestone facts and milestone evidence references must match exactly.",
                source="milestones",
            )
        )
    if delivery.next_milestone_id is not None and delivery.next_milestone_id not in milestone_ids:
        errors.append(
            _issue(
                "next_milestone_missing",
                "next_milestone_id does not match a projected milestone fact.",
                source="milestones",
            )
        )

    throughput_evidence = _evidence_ids(pack, "throughput_snapshots")
    if delivery.latest_throughput is None:
        if throughput_evidence:
            errors.append(
                _issue(
                    "throughput_evidence_orphaned",
                    "Throughput evidence exists without a projected throughput fact.",
                    source="throughput_snapshots",
                )
            )
    elif {delivery.latest_throughput.id} != throughput_evidence:
        errors.append(
            _issue(
                "throughput_evidence_mismatch",
                "Throughput fact and evidence references must match exactly.",
                source="throughput_snapshots",
            )
        )

    confidence_evidence = _evidence_ids(pack, "delivery_confidence_scores")
    if delivery.latest_delivery_confidence is None:
        if confidence_evidence:
            errors.append(
                _issue(
                    "confidence_evidence_orphaned",
                    "Delivery confidence evidence exists without a projected fact.",
                    source="delivery_confidence_scores",
                )
            )
    elif {delivery.latest_delivery_confidence.id} != confidence_evidence:
        errors.append(
            _issue(
                "confidence_evidence_mismatch",
                "Delivery confidence fact and evidence references must match exactly.",
                source="delivery_confidence_scores",
            )
        )

    if {item.id for item in delivery.open_risks} != _evidence_ids(pack, "risk_alerts"):
        errors.append(
            _issue(
                "risk_evidence_mismatch",
                "Open risk facts and risk evidence references must match exactly.",
                source="risk_alerts",
            )
        )
    if {item.id for item in delivery.open_bottlenecks} != _evidence_ids(pack, "bottlenecks"):
        errors.append(
            _issue(
                "bottleneck_evidence_mismatch",
                "Open bottleneck facts and bottleneck evidence references must match exactly.",
                source="bottlenecks",
            )
        )


def _validate_quality_evidence(
    pack: ClientEvidencePack,
    errors: list[EvidenceValidationIssue],
) -> None:
    quality_ids = {
        item.snapshot_id
        for item in [*pack.quality.current_period, *pack.quality.previous_period]
    }
    if quality_ids != _evidence_ids(pack, "quality_snapshots"):
        errors.append(
            _issue(
                "quality_evidence_mismatch",
                "Quality snapshot facts and evidence references must match exactly.",
                source="quality_snapshots",
            )
        )


def _validate_workforce_evidence(
    pack: ClientEvidencePack,
    errors: list[EvidenceValidationIssue],
) -> None:
    client_safe = pack.visibility_mode == EvidenceVisibility.CLIENT_SAFE
    workforce = pack.workforce
    util_ids = _evidence_ids(pack, "utilization_snapshots")
    team_snap_ids = {item.snapshot_id for item in workforce.team_capacity}
    skill_ids = _evidence_ids(pack, "project_skill_requirements")
    req_ids = {item.requirement_id for item in workforce.skill_requirements}
    gap_ids = _evidence_ids(pack, "capability_gaps")
    open_gap_ids = {item.gap_id for item in workforce.open_gaps}
    training_program_ids = _evidence_ids(pack, "training_programs")
    training_record_ids = _evidence_ids(pack, "training_records")

    if client_safe:
        if workforce.team_capacity or workforce.skill_requirements or workforce.open_gaps:
            errors.append(
                _issue(
                    "client_safe_workforce_rows",
                    "CLIENT_SAFE workforce must omit team, skill-requirement, and gap rows.",
                    source="workforce",
                )
            )
        if util_ids and workforce.capacity.latest_snapshot_date is None:
            errors.append(
                _issue(
                    "workforce_util_aggregate_missing",
                    "Utilization evidence requires a supporting capacity aggregate.",
                    source="utilization_snapshots",
                )
            )
        if skill_ids and workforce.skill_coverage.requirement_count <= 0:
            errors.append(
                _issue(
                    "workforce_skill_aggregate_missing",
                    "Skill-requirement evidence requires a supporting coverage aggregate.",
                    source="project_skill_requirements",
                )
            )
        if gap_ids and not workforce.open_gap_counts:
            errors.append(
                _issue(
                    "workforce_gap_aggregate_missing",
                    "Capability-gap evidence requires supporting aggregate gap counts.",
                    source="capability_gaps",
                )
            )
        if (
            (training_program_ids or training_record_ids)
            and workforce.training.mandatory_program_count is None
            and workforce.training.completion_pct is None
            and workforce.training.required_assignment_count is None
        ):
            errors.append(
                _issue(
                    "workforce_training_aggregate_missing",
                    "Training evidence requires a supporting training aggregate.",
                    source="training_programs",
                )
            )
    else:
        if team_snap_ids != util_ids:
            errors.append(
                _issue(
                    "workforce_util_evidence_mismatch",
                    "Team capacity snapshot IDs and utilization evidence must match.",
                    source="utilization_snapshots",
                )
            )
        if req_ids != skill_ids:
            errors.append(
                _issue(
                    "workforce_skill_evidence_mismatch",
                    "Skill-requirement facts and evidence must match exactly.",
                    source="project_skill_requirements",
                )
            )
        if open_gap_ids != gap_ids:
            errors.append(
                _issue(
                    "workforce_gap_evidence_mismatch",
                    "Capability-gap facts and evidence must match exactly.",
                    source="capability_gaps",
                )
            )

    # Unavailable skills must not be projected as factual zero headcount.
    for requirement in workforce.skill_requirements:
        if (
            requirement.coverage_status == "unavailable"
            and (
                requirement.available_headcount is not None
                or requirement.available_sme_count is not None
            )
        ):
            errors.append(
                _issue(
                    "workforce_unavailable_skill_zero",
                    "Unavailable skill coverage must omit available counts.",
                    source="project_skill_requirements",
                    evidence_id=requirement.requirement_id,
                )
            )


def _validate_governance_evidence(
    pack: ClientEvidencePack,
    errors: list[EvidenceValidationIssue],
) -> None:
    client_safe = pack.visibility_mode == EvidenceVisibility.CLIENT_SAFE
    governance = pack.governance
    scope_ids = _evidence_ids(pack, "project_scope_states")
    charter_ids = _evidence_ids(pack, "project_charters")
    dep_ids = _evidence_ids(pack, "project_dependencies")
    action_ids = _evidence_ids(pack, "governance_actions")
    escalation_ids = _evidence_ids(pack, "governance_escalations")

    if governance.scope is None:
        if scope_ids:
            errors.append(
                _issue(
                    "governance_scope_orphaned",
                    "Scope evidence exists without a projected scope fact.",
                    source="project_scope_states",
                )
            )
    else:
        if len(scope_ids) != 1:
            errors.append(
                _issue(
                    "governance_scope_evidence_count",
                    "Projected scope requires exactly one scope evidence reference.",
                    source="project_scope_states",
                )
            )
        elif (
            not client_safe
            and governance.scope.scope_state_id not in scope_ids
        ):
            errors.append(
                _issue(
                    "governance_scope_mismatch",
                    "Scope fact ID and evidence reference must match.",
                    source="project_scope_states",
                )
            )
        if client_safe and governance.scope.scope_state_id is not None:
            errors.append(
                _issue(
                    "client_safe_scope_state_id",
                    "CLIENT_SAFE governance scope must omit scope_state_id.",
                    source="project_scope_states",
                )
            )

    if governance.charter is None:
        if charter_ids:
            errors.append(
                _issue(
                    "governance_charter_orphaned",
                    "Charter evidence exists without a projected charter fact.",
                    source="project_charters",
                )
            )
    else:
        if {governance.charter.charter_id} != charter_ids:
            errors.append(
                _issue(
                    "governance_charter_mismatch",
                    "Charter fact ID and evidence references must match.",
                    source="project_charters",
                )
            )

    fact_dep_ids = {item.dependency_id for item in governance.dependencies}
    fact_action_ids = {item.action_id for item in governance.actions}
    fact_escalation_ids = {item.escalation_id for item in governance.escalations}

    if client_safe:
        if governance.dependencies or governance.actions or governance.escalations:
            errors.append(
                _issue(
                    "client_safe_governance_details",
                    "CLIENT_SAFE governance must omit dependency, action, and escalation rows.",
                    source="governance",
                )
            )
        if dep_ids and governance.summary.dependency_count <= 0:
            errors.append(
                _issue(
                    "governance_dependency_aggregate_missing",
                    "Dependency evidence requires a supporting aggregate summary.",
                    source="project_dependencies",
                )
            )
        if action_ids and governance.summary.action_count <= 0:
            errors.append(
                _issue(
                    "governance_action_aggregate_missing",
                    "Action evidence requires a supporting aggregate summary.",
                    source="governance_actions",
                )
            )
        if escalation_ids and governance.summary.escalation_count <= 0:
            errors.append(
                _issue(
                    "governance_escalation_aggregate_missing",
                    "Escalation evidence requires a supporting aggregate summary.",
                    source="governance_escalations",
                )
            )
    else:
        if fact_dep_ids != dep_ids:
            errors.append(
                _issue(
                    "governance_dependency_mismatch",
                    "Dependency facts and evidence must match exactly.",
                    source="project_dependencies",
                )
            )
        if fact_action_ids != action_ids:
            errors.append(
                _issue(
                    "governance_action_mismatch",
                    "Action facts and evidence must match exactly.",
                    source="governance_actions",
                )
            )
        if fact_escalation_ids != escalation_ids:
            errors.append(
                _issue(
                    "governance_escalation_mismatch",
                    "Escalation facts and evidence must match exactly.",
                    source="governance_escalations",
                )
            )


def _validate_knowledge_evidence(
    pack: ClientEvidencePack,
    errors: list[EvidenceValidationIssue],
) -> None:
    knowledge = pack.knowledge
    if {item.document_id for item in knowledge.documents} != _evidence_ids(
        pack, "knowledge_documents"
    ):
        errors.append(
            _issue(
                "knowledge_document_evidence_mismatch",
                "Knowledge document facts and evidence must match exactly.",
                source="knowledge_documents",
            )
        )
    if {item.chunk_id for item in knowledge.chunks} != _evidence_ids(
        pack, "knowledge_document_chunks"
    ):
        errors.append(
            _issue(
                "knowledge_chunk_evidence_mismatch",
                "Knowledge chunk facts and evidence must match exactly.",
                source="knowledge_document_chunks",
            )
        )
    _validate_knowledge_section(
        knowledge,
        client_safe=pack.visibility_mode == EvidenceVisibility.CLIENT_SAFE,
        errors=errors,
    )


def _validate_fact_timestamps(
    pack: ClientEvidencePack,
    errors: list[EvidenceValidationIssue],
) -> None:
    as_of = pack.reporting_period.as_of
    as_of_end = _as_of_end(as_of)

    delivery = pack.delivery
    if (
        delivery.latest_throughput is not None
        and delivery.latest_throughput.snapshot_date > as_of
    ):
        errors.append(
            _issue(
                "throughput_snapshot_after_as_of",
                "Throughput snapshot_date must not be after as_of.",
                source="throughput_snapshots",
                evidence_id=delivery.latest_throughput.id,
            )
        )
    if delivery.latest_delivery_confidence is not None:
        _check_observed_at(
            delivery.latest_delivery_confidence.observed_at,
            as_of_end=as_of_end,
            code_prefix="confidence_fact",
            source="delivery_confidence_scores",
            evidence_id=delivery.latest_delivery_confidence.id,
            errors=errors,
        )
    for risk in delivery.open_risks:
        _check_observed_at(
            risk.observed_at,
            as_of_end=as_of_end,
            code_prefix="risk_fact",
            source="risk_alerts",
            evidence_id=risk.id,
            errors=errors,
        )
    for bottleneck in delivery.open_bottlenecks:
        _check_observed_at(
            bottleneck.observed_at,
            as_of_end=as_of_end,
            code_prefix="bottleneck_fact",
            source="bottlenecks",
            evidence_id=bottleneck.id,
            errors=errors,
        )

    for snap in [*pack.quality.current_period, *pack.quality.previous_period]:
        _check_observed_at(
            snap.observed_at,
            as_of_end=as_of_end,
            code_prefix="quality_fact",
            source="quality_snapshots",
            evidence_id=snap.snapshot_id,
            errors=errors,
        )

    workforce = pack.workforce
    if (
        workforce.capacity.latest_snapshot_date is not None
        and workforce.capacity.latest_snapshot_date > as_of
    ):
        errors.append(
            _issue(
                "workforce_snapshot_after_as_of",
                "Workforce latest_snapshot_date must not be after as_of.",
                source="utilization_snapshots",
            )
        )
    for team in workforce.team_capacity:
        if team.snapshot_date > as_of:
            errors.append(
                _issue(
                    "workforce_team_snapshot_after_as_of",
                    "Workforce team snapshot_date must not be after as_of.",
                    source="utilization_snapshots",
                    evidence_id=team.snapshot_id,
                )
            )
        _check_observed_at(
            team.observed_at,
            as_of_end=as_of_end,
            code_prefix="workforce_team_fact",
            source="utilization_snapshots",
            evidence_id=team.snapshot_id,
            errors=errors,
        )
    for requirement in workforce.skill_requirements:
        _check_observed_at(
            requirement.observed_at,
            as_of_end=as_of_end,
            code_prefix="workforce_skill_fact",
            source="project_skill_requirements",
            evidence_id=requirement.requirement_id,
            errors=errors,
        )
    _check_observed_at(
        workforce.training.observed_at,
        as_of_end=as_of_end,
        code_prefix="workforce_training_fact",
        source="training_programs",
        evidence_id=None,
        errors=errors,
    )
    for gap in workforce.open_gaps:
        _check_observed_at(
            gap.observed_at,
            as_of_end=as_of_end,
            code_prefix="workforce_gap_fact",
            source="capability_gaps",
            evidence_id=gap.gap_id,
            errors=errors,
        )

    governance = pack.governance
    if governance.scope is not None:
        _check_observed_at(
            governance.scope.observed_at,
            as_of_end=as_of_end,
            code_prefix="governance_scope_fact",
            source="project_scope_states",
            evidence_id=governance.scope.scope_state_id,
            errors=errors,
        )
    if governance.charter is not None:
        _check_observed_at(
            governance.charter.observed_at,
            as_of_end=as_of_end,
            code_prefix="governance_charter_fact",
            source="project_charters",
            evidence_id=governance.charter.charter_id,
            errors=errors,
        )
    for dependency in governance.dependencies:
        _check_observed_at(
            dependency.observed_at,
            as_of_end=as_of_end,
            code_prefix="governance_dependency_fact",
            source="project_dependencies",
            evidence_id=dependency.dependency_id,
            errors=errors,
        )
    for action in governance.actions:
        _check_observed_at(
            action.observed_at,
            as_of_end=as_of_end,
            code_prefix="governance_action_fact",
            source="governance_actions",
            evidence_id=action.action_id,
            errors=errors,
        )
    for escalation in governance.escalations:
        _check_observed_at(
            escalation.observed_at,
            as_of_end=as_of_end,
            code_prefix="governance_escalation_fact",
            source="governance_escalations",
            evidence_id=escalation.escalation_id,
            errors=errors,
        )

    for document in pack.knowledge.documents:
        _check_observed_at(
            document.observed_at,
            as_of_end=as_of_end,
            code_prefix="knowledge_document_fact",
            source="knowledge_documents",
            evidence_id=document.document_id,
            errors=errors,
        )
    for chunk in pack.knowledge.chunks:
        _check_observed_at(
            chunk.observed_at,
            as_of_end=as_of_end,
            code_prefix="knowledge_chunk_fact",
            source="knowledge_document_chunks",
            evidence_id=chunk.chunk_id,
            errors=errors,
        )


def _validate_cross_adapter_client_safe(
    pack: ClientEvidencePack,
    errors: list[EvidenceValidationIssue],
    warnings: list[EvidenceValidationIssue],
) -> None:
    client_safe = pack.visibility_mode == EvidenceVisibility.CLIENT_SAFE
    if client_safe:
        delivery = pack.delivery
        if delivery.open_risks or delivery.open_bottlenecks:
            errors.append(
                _issue(
                    "client_safe_delivery_risks",
                    "CLIENT_SAFE packs must not include open risk or bottleneck facts.",
                    source="delivery",
                )
            )
        for milestone in delivery.milestones:
            if milestone.description is not None:
                errors.append(
                    _issue(
                        "client_safe_milestone_description",
                        "CLIENT_SAFE milestone description must be absent.",
                        source="milestones",
                        evidence_id=milestone.id,
                    )
                )
        confidence = delivery.latest_delivery_confidence
        if confidence is not None and confidence.model_version is not None:
            errors.append(
                _issue(
                    "client_safe_model_version",
                    "CLIENT_SAFE delivery confidence must omit model_version.",
                    source="delivery_confidence_scores",
                    evidence_id=confidence.id,
                )
            )

    if any(issue.state.value == "unavailable" for issue in pack.data_quality):
        warnings.append(
            _issue(
                "source_unavailable",
                "One or more sources are unavailable; pack remains valid when otherwise safe.",
                source="data_quality",
            )
        )


def _validate_knowledge_section(
    knowledge: KnowledgeEvidenceFacts,
    *,
    client_safe: bool,
    errors: list[EvidenceValidationIssue],
) -> None:
    if len(knowledge.source_availability) != 5:
        errors.append(
            _issue(
                "knowledge_availability_count",
                "Knowledge source_availability must contain exactly five rows.",
                source="knowledge",
            )
        )
    requirement_ids = [item.requirement_id for item in knowledge.source_availability]
    if requirement_ids != list(_KNOWLEDGE_REQUIREMENT_IDS):
        errors.append(
            _issue(
                "knowledge_availability_order",
                "Knowledge source_availability must cover CI-D11 through CI-D15 in order.",
                source="knowledge",
            )
        )
    d14 = next(
        (item for item in knowledge.source_availability if item.requirement_id == "CI-D14"),
        None,
    )
    if d14 is None or d14.state.value != "unavailable":
        errors.append(
            _issue(
                "knowledge_ci_d14",
                "CI-D14 must remain UNAVAILABLE in Phase 1.",
                source="knowledge",
            )
        )
    if client_safe:
        for document in knowledge.documents:
            if document.document_title is not None:
                errors.append(
                    _issue(
                        "client_safe_document_title",
                        "CLIENT_SAFE Knowledge documents must omit document_title.",
                        source="knowledge_documents",
                        evidence_id=document.document_id,
                    )
                )
        for chunk in knowledge.chunks:
            if chunk.section_label is not None:
                errors.append(
                    _issue(
                        "client_safe_section_label",
                        "CLIENT_SAFE Knowledge chunks must omit section_label.",
                        source="knowledge_document_chunks",
                        evidence_id=chunk.chunk_id,
                    )
                )


def _validate_client_safe_redaction(
    pack: ClientEvidencePack,
    errors: list[EvidenceValidationIssue],
) -> None:
    payload = pack.model_dump(mode="json")
    _walk_forbidden_keys(payload, path="", errors=errors)


def _walk_forbidden_keys(
    value: Any,
    *,
    path: str,
    errors: list[EvidenceValidationIssue],
) -> None:
    if isinstance(value, dict):
        for key, child in value.items():
            child_path = f"{path}.{key}" if path else key
            if key == "untrusted_text":
                if not _path_matches_untrusted_allowed(child_path):
                    errors.append(
                        _issue(
                            "untrusted_text_path",
                            "untrusted_text is only permitted under knowledge.chunks.",
                            source="knowledge",
                        )
                    )
                continue
            if key in _CLIENT_SAFE_FORBIDDEN_KEYS and child is not None:
                errors.append(
                    _issue(
                        "client_safe_forbidden_field",
                        (
                            "Forbidden CLIENT_SAFE field present at schema path "
                            f"'{_safe_path(child_path)}'."
                        ),
                        source=_safe_path(child_path).split(".")[0],
                    )
                )
                continue
            _walk_forbidden_keys(child, path=child_path, errors=errors)
        return
    if isinstance(value, list):
        for index, child in enumerate(value):
            child_path = f"{path}.*" if path else "*"
            _ = index
            _walk_forbidden_keys(child, path=child_path, errors=errors)


def _path_matches_untrusted_allowed(path: str) -> bool:
    return path == _UNTRUSTED_TEXT_ALLOWED_PATH


def _safe_path(path: str) -> str:
    parts = []
    for part in path.split("."):
        if part.isdigit():
            parts.append("*")
        else:
            parts.append(part)
    return ".".join(parts)
