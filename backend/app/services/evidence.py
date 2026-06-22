from dataclasses import dataclass
from uuid import UUID

from app.core.exceptions import ApiError


@dataclass(frozen=True)
class EvidenceInput:
    source_table: str
    source_row_id: UUID
    description: str


def require_evidence(evidence: list[EvidenceInput]) -> None:
    if not evidence:
        raise ApiError(409, "EVIDENCE_REQUIRED", "AI output requires at least one evidence link.")
