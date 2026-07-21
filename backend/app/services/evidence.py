from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from app.core.exceptions import ApiError

LIMITATION_EVIDENCE_PROVENANCE_INCOMPLETE = "EVIDENCE_PROVENANCE_INCOMPLETE"
ERROR_EVIDENCE_PROVENANCE_INCOMPLETE = "EVIDENCE_PROVENANCE_INCOMPLETE"
ERROR_EVIDENCE_PROVENANCE_CONFLICT = "EVIDENCE_PROVENANCE_CONFLICT"
ERROR_EVIDENCE_PROVENANCE_UNMATCHED = "EVIDENCE_PROVENANCE_UNMATCHED"


@dataclass(frozen=True)
class EvidenceInput:
    """Evidence link input. Provenance fields are server-authored only.

    Callers must not accept provenance from frontend payloads. Legacy rows may
    omit optional fields; readers must disclose incomplete provenance rather
    than fabricating values.
    """

    source_table: str
    source_row_id: UUID
    description: str
    visibility: str | None = None
    observed_at: datetime | None = None
    claim_keys: tuple[str, ...] | None = None
    pack_source_fingerprint: str | None = None


def require_evidence(evidence: list[EvidenceInput]) -> None:
    if not evidence:
        raise ApiError(409, "EVIDENCE_REQUIRED", "AI output requires at least one evidence link.")


def evidence_provenance_complete(item: EvidenceInput) -> bool:
    """New writes require visibility, observed_at, pack fingerprint, and claim keys."""
    return bool(
        item.visibility
        and item.observed_at is not None
        and item.pack_source_fingerprint
        and item.claim_keys
        and len(item.claim_keys) > 0
    )


def require_complete_evidence_provenance(evidence: list[EvidenceInput]) -> None:
    require_evidence(evidence)
    for item in evidence:
        if not evidence_provenance_complete(item):
            raise ApiError(
                409,
                ERROR_EVIDENCE_PROVENANCE_INCOMPLETE,
                (
                    "Client Intelligence evidence links require server-authored "
                    "visibility, observed timestamp, non-empty claim keys, and "
                    "pack source fingerprint."
                ),
                {
                    "source_table": item.source_table,
                    "source_row_id": str(item.source_row_id),
                },
            )


def _provenance_signature(item: EvidenceInput) -> tuple[object, ...]:
    return (
        item.visibility,
        item.observed_at,
        item.claim_keys,
        item.pack_source_fingerprint,
        item.description,
    )


def dedupe_evidence_inputs(evidence: list[EvidenceInput]) -> list[EvidenceInput]:
    """Deterministic dedupe by canonical source identity (table + row).

    Identical duplicates keep the first ordered item. Conflicting provenance for
    the same identity fails closed.
    """
    seen: dict[tuple[str, UUID], EvidenceInput] = {}
    ordered = sorted(
        evidence,
        key=lambda item: (item.source_table, str(item.source_row_id), item.description),
    )
    for item in ordered:
        key = (item.source_table, item.source_row_id)
        existing = seen.get(key)
        if existing is None:
            seen[key] = item
            continue
        if _provenance_signature(existing) != _provenance_signature(item):
            raise ApiError(
                409,
                ERROR_EVIDENCE_PROVENANCE_CONFLICT,
                (
                    "Conflicting evidence provenance for the same source identity "
                    "cannot be persisted."
                ),
                {
                    "source_table": item.source_table,
                    "source_row_id": str(item.source_row_id),
                },
            )
    return list(seen.values())
