"""Citation enforcement tests for quality NL responses (BR-02)."""

from uuid import uuid4

from app.agents.quality_intelligence.citations import (
    allowed_evidence_ids,
    strip_ungrounded_citations,
)
from app.services.evidence import EvidenceInput


def test_strip_ungrounded_citations_removes_hallucinated_ids() -> None:
    real_id = uuid4()
    fake_id = uuid4()
    evidence = [
        EvidenceInput(
            source_table="quality_snapshots",
            source_row_id=real_id,
            description="snapshot",
        )
    ]
    text = f"Drift linked to evidence {real_id} and also {fake_id}."
    cleaned = strip_ungrounded_citations(text, evidence)
    assert str(real_id) in cleaned
    assert str(fake_id) not in cleaned
    assert "citation removed" in cleaned


def test_allowed_evidence_ids() -> None:
    ids = {uuid4(), uuid4()}
    evidence = [
        EvidenceInput(source_table="t", source_row_id=i, description="d") for i in ids
    ]
    assert allowed_evidence_ids(evidence) == {str(i) for i in ids}
