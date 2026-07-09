"""Citation validation for evidence-grounded quality NL responses (BR-02)."""

from __future__ import annotations

import re
from uuid import UUID

from app.services.evidence import EvidenceInput

_UUID_PATTERN = re.compile(
    r"\b[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\b",
    re.IGNORECASE,
)


def allowed_evidence_ids(evidence: list[EvidenceInput]) -> set[str]:
    return {str(item.source_row_id) for item in evidence}


def strip_ungrounded_citations(answer_text: str, evidence: list[EvidenceInput]) -> str:
    """Remove UUID citations that are not in the evidence set."""
    allowed = allowed_evidence_ids(evidence)
    if not allowed:
        return answer_text

    def _replace(match: re.Match[str]) -> str:
        uid = match.group(0)
        return uid if uid in allowed else "[citation removed — not in evidence]"

    return _UUID_PATTERN.sub(_replace, answer_text)


def append_evidence_index(answer_text: str, evidence: list[EvidenceInput]) -> str:
    if not evidence:
        return answer_text
    lines = ["", "Evidence:"]
    for item in evidence[:12]:
        lines.append(f"- {item.source_table}:{item.source_row_id} — {item.description}")
    return answer_text + "\n".join(lines)
