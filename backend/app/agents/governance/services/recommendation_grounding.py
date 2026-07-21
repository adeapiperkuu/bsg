"""Grounding validation for Governance AI recommendation candidates."""

from __future__ import annotations

import re
from uuid import UUID

from app.agents.governance.schemas.governance import GovernanceAIRecommendationCandidate
from app.agents.governance.services.recommendation_evidence import (
    GovernanceRecommendationEvidenceBundle,
)
from app.db.models import GovernanceAIRecommendationScope

_UUID_PATTERN = re.compile(
    r"\b[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\b",
    re.IGNORECASE,
)
_DATE_PATTERN = re.compile(r"\b\d{4}-\d{2}-\d{2}\b")
_COUNT_CLAIM_PATTERN = re.compile(
    r"\b(\d+)\s+(blocking dependencies|critical escalations|overdue actions|open escalations|"
    r"pending scope|dependencies|escalations|actions)\b",
    re.IGNORECASE,
)
_OWNER_CLAIM_PATTERN = re.compile(
    r"\b(?:owned by|assigned to|owner)\s+([A-Z][a-z]+(?:\s+[A-Z][a-z]+)+)\b"
)
_PROJECT_NAME_CLAIM_PATTERN = re.compile(
    r"\bProject\s+([A-Z][A-Za-z0-9_-]{1,40})\b"
)


def _normalize_title(text: str) -> str:
    return " ".join(text.lower().split())


def recommendation_fingerprint(
    *,
    recommendation_type: str,
    project_id: UUID | None,
    title: str,
    evidence_hash: str,
) -> str:
    import hashlib

    payload = "|".join(
        [
            recommendation_type,
            str(project_id) if project_id else "portfolio",
            _normalize_title(title),
            evidence_hash,
        ]
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def titles_are_near_duplicates(left: str, right: str, *, threshold: float = 0.75) -> bool:
    left_tokens = set(_normalize_title(left).split())
    right_tokens = set(_normalize_title(right).split())
    if not left_tokens or not right_tokens:
        return False
    overlap = len(left_tokens & right_tokens)
    union = len(left_tokens | right_tokens)
    return (overlap / union) >= threshold


def validate_candidate_grounding(
    candidate: GovernanceAIRecommendationCandidate,
    bundle: GovernanceRecommendationEvidenceBundle,
) -> tuple[bool, list[str]]:
    reasons: list[str] = []
    evidence_by_id = {item.evidence_id: item for item in bundle.evidence}
    allowed_project_ids = {
        item.project_id for item in bundle.evidence if item.project_id is not None
    }
    allowed_entity_ids = {
        item.entity_id for item in bundle.evidence if item.entity_id is not None
    }

    if not candidate.evidence_ids:
        reasons.append("missing_evidence_ids")

    for evidence_id in candidate.evidence_ids:
        if evidence_id not in evidence_by_id:
            reasons.append(f"unknown_evidence_id:{evidence_id}")

    if candidate.scope == "project":
        if candidate.project_id is None:
            reasons.append("project_scope_missing_project_id")
        elif candidate.project_id not in allowed_project_ids and candidate.project_id != bundle.project_id:
            reasons.append(f"unknown_project_id:{candidate.project_id}")
        if bundle.scope != GovernanceAIRecommendationScope.PROJECT and candidate.project_id not in allowed_project_ids:
            reasons.append("project_not_in_bundle")
    elif candidate.scope == "portfolio":
        if candidate.project_id is not None and candidate.project_id not in allowed_project_ids:
            reasons.append(f"portfolio_inaccessible_project:{candidate.project_id}")

    combined_text = f"{candidate.title}\n{candidate.narrative}\n{candidate.rationale}"
    for owner_match in _OWNER_CLAIM_PATTERN.finditer(combined_text):
        owner = owner_match.group(1).strip()
        if owner and owner not in bundle.owner_names:
            reasons.append(f"unsupported_owner:{owner}")

    for date_match in _DATE_PATTERN.finditer(combined_text):
        value = date_match.group(0)
        if value not in bundle.dates:
            reasons.append(f"unsupported_date:{value}")

    for uuid_match in _UUID_PATTERN.finditer(combined_text):
        try:
            uid = UUID(uuid_match.group(0))
        except ValueError:
            continue
        if uid not in allowed_entity_ids and uid not in allowed_project_ids:
            if candidate.project_id != uid:
                reasons.append(f"unsupported_uuid:{uid}")

    for count_match in _COUNT_CLAIM_PATTERN.finditer(combined_text):
        claimed = int(count_match.group(1))
        label = count_match.group(2).lower()
        key = None
        if "blocking" in label:
            key = "blocking_dependencies"
        elif "critical" in label:
            key = "critical_escalations"
        elif "overdue" in label:
            key = "overdue_actions"
        if key and key in bundle.counts and claimed != bundle.counts[key]:
            reasons.append(f"unsupported_count:{key}:{claimed}")

    # Project name check — reject names that look like proper nouns not in evidence
    project_name_claims = _PROJECT_NAME_CLAIM_PATTERN.findall(combined_text)
    for claimed_name in project_name_claims:
        cleaned = claimed_name.strip()
        if cleaned and cleaned not in bundle.project_names and cleaned != bundle.project_name:
            # Allow substring matches against known project names
            if not any(cleaned in known or known in cleaned for known in bundle.project_names):
                reasons.append(f"unsupported_project_name:{cleaned}")

    for action in candidate.suggested_actions:
        if action.target_entity_id is not None and action.target_entity_id not in allowed_entity_ids:
            if action.target_entity_id not in allowed_project_ids:
                reasons.append(f"unsupported_action_target:{action.target_entity_id}")

    return (len(reasons) == 0, reasons)
