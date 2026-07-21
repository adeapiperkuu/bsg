"""Integration tests: real build_client_evidence_pack + mutable source session.

Uses the repository's established table-routed FakeSession pattern (no Postgres
fixture exists). Does not monkeypatch ``build_client_evidence_pack``. Changes
authoritative persisted source facts on the session, not claim_keys alone.
"""

from __future__ import annotations

import re
from datetime import UTC, date, datetime
from decimal import Decimal
from types import SimpleNamespace
from typing import Any
from uuid import UUID, uuid4

import pytest

from app.agents.client_intelligence.contracts import EvidenceVisibility
from app.agents.client_intelligence.evidence_pack import build_client_evidence_pack
from app.agents.client_intelligence.evidence_validation import (
    finalize_evidence_references,
)
from app.core.exceptions import ApiError
from app.core.security import CurrentUser
from app.db.models import (
    AppRole,
    CommunicationStatus,
    MilestoneStatus,
    ProjectStatus,
)
from app.schemas.domain import CommunicationApprove
from app.services.communications import (
    ERROR_COMMUNICATION_EVIDENCE_CHANGED,
    approve,
    create_draft,
    send,
)
from app.services.evidence import EvidenceInput
from tests.test_communication_lifecycle import RecordingSession, _communication


class _Scalars:
    def __init__(self, items: list[object]) -> None:
        self._items = items

    def __iter__(self):
        return iter(self._items)

    def all(self) -> list[object]:
        return list(self._items)


class _Result:
    def __init__(self, value: object = None, items: list[object] | None = None) -> None:
        self._value = value
        self._items = items or []

    def scalar_one_or_none(self) -> object:
        return self._value

    def scalars(self) -> _Scalars:
        return _Scalars(self._items)

    def all(self) -> list[object]:
        return list(self._items)


class IntegrationSourceSession:
    """Mutable project-scoped source store consumed by real pack assembly."""

    def __init__(
        self,
        *,
        project: SimpleNamespace,
        milestones: list[object],
        throughput: object,
        throughput_series: list[object] | None = None,
        confidence: object | None = None,
        other_project_throughput: object | None = None,
    ) -> None:
        self.project = project
        self.milestones = milestones
        self.throughput = throughput
        self.throughput_series = throughput_series or [throughput]
        self.confidence = confidence
        self.other_project_throughput = other_project_throughput
        self.added: list[Any] = []

    def add(self, obj: Any) -> None:
        self.added.append(obj)

    async def flush(self) -> None:
        return None

    async def commit(self) -> None:
        return None

    async def refresh(self, *_a: Any, **_k: Any) -> None:
        return None

    async def execute(self, stmt) -> _Result:
        compiled = str(stmt.compile(compile_kwargs={"literal_binds": True}))
        if "FROM milestones" in compiled:
            return _Result(None, self.milestones)
        if "FROM throughput_snapshots" in compiled:
            upper = compiled.upper()
            if "SNAPSHOT_DATE ASC" in upper and "LIMIT" not in upper:
                return _Result(None, list(self.throughput_series))
            return _Result(self.throughput)
        if "FROM delivery_confidence_scores" in compiled:
            return _Result(self.confidence)
        if "FROM risk_alerts" in compiled:
            return _Result(None, [])
        if "FROM bottlenecks" in compiled:
            return _Result(None, [])
        if "FROM metric_configurations" in compiled:
            return _Result(None, [])
        if "FROM teams" in compiled:
            return _Result(None, [])
        if "FROM annotators" in compiled:
            return _Result(None, [])
        if "FROM utilization_snapshots" in compiled:
            return _Result(None, [])
        if "FROM project_skill_requirements" in compiled:
            return _Result(None, [])
        if "FROM skills" in compiled:
            return _Result(None, [])
        if "FROM annotator_skills" in compiled:
            return _Result(None, [])
        if "FROM training_programs" in compiled:
            return _Result(None, [])
        if "FROM training_records" in compiled:
            return _Result(None, [])
        if "FROM capability_gaps" in compiled:
            return _Result(None, [])
        if "FROM knowledge_documents" in compiled:
            return _Result(None, [])
        if "FROM knowledge_document_versions" in compiled:
            return _Result(None, [])
        if "FROM knowledge_document_chunks" in compiled:
            return _Result(None, [])
        if "FROM knowledge_document_embeddings" in compiled:
            raise AssertionError("embeddings must not be queried")
        if "FROM client_communications" in compiled:
            raise AssertionError("client_communications must not be queried by pack")
        if "FROM project_scope_states" in compiled:
            return _Result(None, [])
        if "FROM project_charters" in compiled:
            return _Result(None, [])
        if "FROM project_dependencies" in compiled:
            return _Result(None, [])
        if "FROM governance_actions" in compiled:
            return _Result(None, [])
        if "FROM governance_escalations" in compiled:
            return _Result(None, [])
        if "FROM governance_weekly_summaries" in compiled:
            raise AssertionError("weekly summaries must not be queried")
        if re.search(r"\bselect\s+1\b", compiled, re.IGNORECASE):
            return _Result(None, [])
        return _Result(None, [])


def _user(org_id: UUID) -> CurrentUser:
    return CurrentUser(
        id=uuid4(),
        org_id=org_id,
        email="ci-integration@example.com",
        role=AppRole.DELIVERY_MANAGER,
        is_active=True,
    )


def _seed() -> tuple[
    IntegrationSourceSession,
    CurrentUser,
    SimpleNamespace,
    SimpleNamespace,
    date,
]:
    org_id = uuid4()
    as_of = datetime.now(UTC).date()
    project = SimpleNamespace(
        id=uuid4(),
        org_id=org_id,
        name="Aurora Labeling",
        status=ProjectStatus.ACTIVE,
        description="internal",
    )
    other_project_id = uuid4()
    milestone = SimpleNamespace(
        id=uuid4(),
        project_id=project.id,
        name="Batch 14",
        description="note",
        planned_date=as_of,
        actual_date=None,
        status=MilestoneStatus.ON_TRACK,
        deleted_at=None,
        updated_at=datetime.now(UTC),
    )
    throughput = SimpleNamespace(
        id=uuid4(),
        project_id=project.id,
        snapshot_date=as_of,
        units_completed=120,
        units_forecast=130,
        rolling_7day_units=80,
    )
    other_throughput = SimpleNamespace(
        id=uuid4(),
        project_id=other_project_id,
        snapshot_date=as_of,
        units_completed=999,
        units_forecast=999,
        rolling_7day_units=999,
    )
    confidence = SimpleNamespace(
        id=uuid4(),
        project_id=project.id,
        milestone_id=milestone.id,
        score_pct=Decimal("92.50"),
        status=MilestoneStatus.ON_TRACK,
        forecast_completion_date=as_of,
        model_version="delivery-v1",
        created_at=datetime.now(UTC),
    )
    session = IntegrationSourceSession(
        project=project,
        milestones=[milestone],
        throughput=throughput,
        throughput_series=[throughput],
        confidence=confidence,
        other_project_throughput=other_throughput,
    )
    return session, _user(org_id), project, throughput, as_of


@pytest.mark.asyncio
async def test_integration_stale_evidence_from_persisted_source_facts(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session, user, project, throughput, as_of = _seed()

    async def _visible(*_a: Any, **_k: Any) -> Any:
        return project

    monkeypatch.setattr(
        "app.agents.client_intelligence.evidence_pack.get_visible_project",
        _visible,
    )

    pack1 = await build_client_evidence_pack(
        session,  # type: ignore[arg-type]
        user,
        project.id,
        visibility_mode=EvidenceVisibility.INTERNAL,
    )
    fp1 = pack1.source_fingerprint
    assert fp1 and len(fp1) == 64
    assert pack1.reporting_period.as_of == as_of

    throughput_ref = next(
        ref for ref in pack1.evidence if ref.source_table == "throughput_snapshots"
    )
    assert throughput_ref.source_row_id == throughput.id

    draft = await create_draft(
        RecordingSession(),
        project,
        "Subject",
        "Body",
        "ad_hoc",
        [
            EvidenceInput(
                source_table=throughput_ref.source_table,
                source_row_id=throughput_ref.source_row_id,
                description=throughput_ref.description,
                visibility=throughput_ref.visibility.value,
                observed_at=throughput_ref.observed_at
                or datetime.combine(as_of, datetime.min.time(), tzinfo=UTC),
                claim_keys=tuple(throughput_ref.claim_keys),
                pack_source_fingerprint=fp1,
            )
        ],
        evidence_source_fingerprint=fp1,
    )
    assert draft.evidence_source_fingerprint == fp1

    communication = _communication(
        status=CommunicationStatus.IN_REVIEW,
        body_approved="Reviewed body",
        evidence_source_fingerprint=fp1,
        project_id=project.id,
        org_id=project.org_id,
    )
    approved = await approve(
        session,  # type: ignore[arg-type]
        communication,
        CommunicationApprove(body_approved="Reviewed body"),
        user,
    )
    assert approved.status == CommunicationStatus.APPROVED

    pack_order_rebuilt = await build_client_evidence_pack(
        session,  # type: ignore[arg-type]
        user,
        project.id,
        visibility_mode=EvidenceVisibility.INTERNAL,
    )
    assert pack_order_rebuilt.source_fingerprint == fp1
    _ = finalize_evidence_references(list(reversed(pack1.evidence)))

    if session.other_project_throughput is not None:
        session.other_project_throughput.units_completed = 1
    pack_other = await build_client_evidence_pack(
        session,  # type: ignore[arg-type]
        user,
        project.id,
        visibility_mode=EvidenceVisibility.INTERNAL,
    )
    assert pack_other.source_fingerprint == fp1

    throughput.units_completed = 240
    pack2 = await build_client_evidence_pack(
        session,  # type: ignore[arg-type]
        user,
        project.id,
        visibility_mode=EvidenceVisibility.INTERNAL,
    )
    assert pack2.source_fingerprint != fp1

    with pytest.raises(ApiError) as approve_exc:
        await approve(
            session,  # type: ignore[arg-type]
            _communication(
                status=CommunicationStatus.IN_REVIEW,
                body_approved="Reviewed body",
                evidence_source_fingerprint=fp1,
                project_id=project.id,
                org_id=project.org_id,
            ),
            CommunicationApprove(body_approved="Reviewed body"),
            user,
        )
    assert approve_exc.value.code == ERROR_COMMUNICATION_EVIDENCE_CHANGED

    throughput.units_completed = 120
    pack_restored = await build_client_evidence_pack(
        session,  # type: ignore[arg-type]
        user,
        project.id,
        visibility_mode=EvidenceVisibility.INTERNAL,
    )
    assert pack_restored.source_fingerprint == fp1
    ready = _communication(
        status=CommunicationStatus.IN_REVIEW,
        body_approved="Reviewed body",
        evidence_source_fingerprint=fp1,
        project_id=project.id,
        org_id=project.org_id,
    )
    await approve(
        session,  # type: ignore[arg-type]
        ready,
        CommunicationApprove(body_approved="Reviewed body"),
        user,
    )
    throughput.units_completed = 300
    with pytest.raises(ApiError) as send_exc:
        await send(session, ready, user)  # type: ignore[arg-type]
    assert send_exc.value.code == ERROR_COMMUNICATION_EVIDENCE_CHANGED
