from datetime import UTC, date, datetime
from uuid import uuid4

from app.agents.governance.services.audit_service import governance_snapshot
from app.agents.governance.services.monitoring_service import _percentile
from app.db.models import GovernanceAction, GovernanceActionStatus


def test_governance_snapshot_serializes_audit_values() -> None:
    action = GovernanceAction(
        id=uuid4(),
        org_id=uuid4(),
        project_id=uuid4(),
        title="Approve charter",
        status=GovernanceActionStatus.OPEN,
        due_date=date(2026, 6, 30),
        completed_at=datetime(2026, 6, 30, 12, 0, tzinfo=UTC),
    )

    snapshot = governance_snapshot(
        action,
        ("id", "project_id", "status", "due_date", "completed_at"),
    )

    assert isinstance(snapshot["id"], str)
    assert isinstance(snapshot["project_id"], str)
    assert snapshot["status"] == "open"
    assert snapshot["due_date"] == "2026-06-30"
    assert snapshot["completed_at"] == "2026-06-30T12:00:00+00:00"


def test_percentile_handles_empty_and_p95_values() -> None:
    assert _percentile([], 0.95) is None
    assert _percentile([10, 20, 30, 40, 50], 0.95) == 50
