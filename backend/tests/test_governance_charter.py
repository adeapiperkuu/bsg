from uuid import uuid4

from app.agents.governance.services.charter_service import (
    CharterEvidenceItem,
    build_template_charter,
    has_sufficient_charter_evidence,
)
from app.db.models import GovernanceEvidenceSourceType


def _item(source_type: GovernanceEvidenceSourceType) -> CharterEvidenceItem:
    source_id = uuid4()
    return CharterEvidenceItem(
        source_type=source_type,
        source_id=source_id,
        evidence_ref=f"{source_type.value}:{source_id}",
        label="Scope v1",
        category="scope_state",
        project_name="Phoenix",
        detail="scope_status=approved, version=v1",
    )


def test_charter_evidence_requires_governance_or_knowledge_source() -> None:
    assert not has_sufficient_charter_evidence([])
    assert not has_sufficient_charter_evidence(
        [_item(GovernanceEvidenceSourceType.DELIVERY_SIGNAL)]
    )
    assert has_sufficient_charter_evidence([_item(GovernanceEvidenceSourceType.SCOPE_STATE)])


def test_build_template_charter_includes_required_sections_and_evidence() -> None:
    source_id = uuid4()
    ref = f"scope_state:{source_id}"
    item = CharterEvidenceItem(
        source_type=GovernanceEvidenceSourceType.SCOPE_STATE,
        source_id=source_id,
        evidence_ref=ref,
        label="Scope v1",
        category="scope_state",
        project_name="Phoenix",
        detail="scope_status=approved, version=v1",
    )
    context = {
        "project": {
            "id": str(uuid4()),
            "name": "Phoenix",
            "description": "Test project",
            "vertical": "Data",
            "status": "active",
            "start_date": "2026-06-01",
            "target_end_date": "2026-07-01",
            "actual_end_date": None,
            "daily_target_units": 100,
        },
        "charter": {"version": "v2"},
        "scope": {
            "evidence_ref": ref,
            "scope_status": "approved",
            "version_label": "v1",
            "notes": "Baseline approved scope.",
        },
        "dependencies": [],
        "actions": [],
        "escalations": [],
        "weekly_summaries": [],
        "delivery_signals": [],
        "knowledge_documents": [],
        "stakeholders": [],
    }
    text = build_template_charter(context, [item])
    assert "## Executive Summary" in text
    assert "## Approval Section" in text
    assert "## Evidence Appendix" in text
    assert ref in text
    assert "- Version: v2" in text
