"""Unit + SQL-text tests for provenance helpers (not DB integration)."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from uuid import UUID, uuid4

import pytest

from app.agents.client_intelligence.contracts import EvidenceVisibility
from app.agents.client_intelligence.evidence_fingerprint import (
    compute_source_fingerprint_from_pack,
)
from app.agents.client_intelligence.evidence_validation import (
    finalize_evidence_references,
)
from app.api.routes import communications as communications_route
from app.core.exceptions import ApiError
from app.db.models import CommunicationStatus, CommunicationType
from app.schemas.common import EvidenceLinkRead
from app.schemas.domain import CommunicationApprove, CommunicationDraftCreate
from app.services.communications import (
    LIMITATION_LEGACY_EVIDENCE_FINGERPRINT_MISSING,
    _assert_evidence_fingerprint_for_lifecycle,
    approve,
    create_draft,
)
from app.services.evidence import (
    ERROR_EVIDENCE_PROVENANCE_CONFLICT,
    ERROR_EVIDENCE_PROVENANCE_INCOMPLETE,
    ERROR_EVIDENCE_PROVENANCE_UNMATCHED,
    EvidenceInput,
    dedupe_evidence_inputs,
)
from tests.conftest import FakeSession
from tests.test_client_intelligence_delivery_confidence import (
    _complete_pack,
    _with_domain_facts,
)
from tests.test_communication_lifecycle import RecordingSession, _communication, _user

ORG_ID = UUID("aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa")
PROJECT_ID = UUID("cccccccc-cccc-4ccc-8ccc-cccccccccccc")
_MIGRATION = (
    Path(__file__).resolve().parents[2]
    / "supabase"
    / "migrations"
    / "20260717140000_client_intelligence_evidence_provenance.sql"
)


def test_migration_sql_text_dedupes_before_unique_indexes() -> None:
    """Static SQL-text assertions only — not live Postgres migration execution."""
    sql = _MIGRATION.read_text(encoding="utf-8")
    assert "ADD COLUMN IF NOT EXISTS evidence_source_fingerprint" in sql
    assert "~ '^[0-9a-f]{64}$'" in sql
    assert "visibility IN ('internal', 'client_safe')" in sql
    assert "jsonb_typeof(claim_keys) = 'array'" in sql
    assert sql.index("DELETE FROM communication_evidence_links") < sql.index(
        "communication_evidence_links_parent_source_uidx"
    )
    assert sql.index("DELETE FROM agent_query_evidence_links") < sql.index(
        "agent_query_evidence_links_parent_source_uidx"
    )
    assert "evidence_source_fingerprint TEXT NOT NULL" not in sql
    assert "does not create a cross-tenant policy bypass" in sql


def test_live_postgresql_migration_execution_unavailable_in_this_suite() -> None:
    """Explicit limitation: no Postgres migration fixture exists in this repository.

    Fresh/upgraded/duplicate migration execution, unique-index creation against a
    live database, CHECK rejection, and live RLS enforcement are unresolved
    verification gaps until a database-backed migration harness is added.
    """
    assert _MIGRATION.exists()
    conftest = Path(__file__).resolve().parent / "conftest.py"
    assert conftest.exists()
    text = conftest.read_text(encoding="utf-8")
    assert "create_async_engine" not in text
    assert "FakeSession" in text


def test_unit_pack_fingerprint_changes_with_facts_not_ordering() -> None:
    """Unit test against fixture packs — does not call build_client_evidence_pack."""
    pack_a = _with_domain_facts(
        _complete_pack(project_id=PROJECT_ID, org_id=ORG_ID),
        throughput=True,
    )
    fp_a = compute_source_fingerprint_from_pack(pack_a)
    pack_a_reordered = pack_a.model_copy(
        update={"evidence": finalize_evidence_references(list(reversed(pack_a.evidence)))}
    )
    assert compute_source_fingerprint_from_pack(pack_a_reordered) == fp_a
    target = next(
        ref for ref in pack_a.evidence if ref.source_table == "throughput_snapshots"
    )
    mutated = pack_a.model_copy(
        update={
            "evidence": [
                (
                    target.model_copy(
                        update={"claim_keys": [*target.claim_keys, "units_forecast"]}
                    )
                    if ref.source_row_id == target.source_row_id
                    else ref
                )
                for ref in pack_a.evidence
            ]
        }
    )
    assert compute_source_fingerprint_from_pack(mutated) != fp_a


@pytest.mark.asyncio
async def test_unit_draft_fingerprint_comparison_via_pack_monkeypatch(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Unit test: comparison logic with fixture packs (builder monkeypatched)."""
    pack = _with_domain_facts(
        _complete_pack(project_id=PROJECT_ID, org_id=ORG_ID),
        throughput=True,
    )
    fingerprint = compute_source_fingerprint_from_pack(pack)
    pack = pack.model_copy(update={"source_fingerprint": fingerprint})
    throughput = next(
        ref for ref in pack.evidence if ref.source_table == "throughput_snapshots"
    )
    draft = await create_draft(
        RecordingSession(),
        SimpleNamespace(id=PROJECT_ID, org_id=ORG_ID),
        "Subject",
        "Body",
        "ad_hoc",
        [
            EvidenceInput(
                source_table=throughput.source_table,
                source_row_id=throughput.source_row_id,
                description=throughput.description,
                visibility=throughput.visibility.value,
                observed_at=throughput.observed_at
                or datetime(2026, 6, 18, tzinfo=UTC),
                claim_keys=tuple(throughput.claim_keys),
                pack_source_fingerprint=fingerprint,
            )
        ],
        evidence_source_fingerprint=fingerprint,
    )
    assert draft.evidence_source_fingerprint == fingerprint

    async def _same(*_a: Any, **_k: Any) -> Any:
        return pack

    monkeypatch.setattr(
        "app.agents.client_intelligence.evidence_pack.build_client_evidence_pack",
        _same,
    )
    user = _user()
    approved = await approve(
        RecordingSession(),
        _communication(
            status=CommunicationStatus.IN_REVIEW,
            body_approved="Reviewed body",
            evidence_source_fingerprint=fingerprint,
            project_id=PROJECT_ID,
        ),
        CommunicationApprove(body_approved="Reviewed body"),
        user,
    )
    assert approved.status == CommunicationStatus.APPROVED


@pytest.mark.asyncio
async def test_legacy_missing_fingerprint_disclosed_without_auto_reapproval() -> None:
    user = _user()
    legacy = _communication(
        status=CommunicationStatus.IN_REVIEW,
        body_approved="Reviewed body",
        evidence_source_fingerprint=None,
    )
    disclosed = await _assert_evidence_fingerprint_for_lifecycle(
        FakeSession(),
        legacy,
        user,
        action="approve",
    )
    assert disclosed == LIMITATION_LEGACY_EVIDENCE_FINGERPRINT_MISSING
    assert legacy.status == CommunicationStatus.IN_REVIEW
    assert legacy.sent_at is None


@pytest.mark.asyncio
async def test_draft_route_pack_failure_before_persistence_no_commit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    commits: list[str] = []

    class FailSession(FakeSession):
        def __init__(self) -> None:
            self.added: list[Any] = []

        def add(self, obj: Any) -> None:
            self.added.append(obj)

        async def commit(self) -> None:
            commits.append("commit")

        async def rollback(self) -> None:
            commits.append("rollback")

    async def _boom(*_a: Any, **_k: Any) -> Any:
        raise RuntimeError("pack assembly failed")

    monkeypatch.setattr(
        "app.agents.client_intelligence.evidence_pack.build_client_evidence_pack",
        _boom,
    )

    class _Project:
        async def __call__(self, *_a: Any, **_k: Any) -> Any:
            return SimpleNamespace(id=PROJECT_ID, org_id=ORG_ID)

    monkeypatch.setattr(
        "app.api.routes.communications.get_visible_project",
        _Project(),
    )
    session = FailSession()
    with pytest.raises(RuntimeError, match="pack assembly failed"):
        await communications_route.draft_communication(
            PROJECT_ID,
            CommunicationDraftCreate(
                comm_type=CommunicationType.AD_HOC,
                subject="Subject",
            ),
            session,
            _user(),
        )
    assert "commit" not in commits
    assert not session.added


@pytest.mark.asyncio
async def test_draft_route_rolls_back_when_evidence_link_persistence_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.agents.client_intelligence.evidence_fingerprint import (
        compute_source_fingerprint_from_pack,
    )

    pack = _with_domain_facts(
        _complete_pack(project_id=PROJECT_ID, org_id=ORG_ID),
        throughput=True,
    )
    fingerprint = compute_source_fingerprint_from_pack(pack)
    pack = pack.model_copy(update={"source_fingerprint": fingerprint})
    throughput_ref = next(
        ref for ref in pack.evidence if ref.source_table == "throughput_snapshots"
    )
    throughput_row = SimpleNamespace(
        id=throughput_ref.source_row_id,
        project_id=PROJECT_ID,
        snapshot_date=datetime(2026, 6, 18, tzinfo=UTC).date(),
        units_completed=120,
        units_forecast=130,
        rolling_7day_units=80,
    )

    class TrackingSession(FakeSession):
        def __init__(self) -> None:
            self.added: list[Any] = []
            self.commits = 0
            self.rollbacks = 0

        def add(self, obj: Any) -> None:
            if obj.__class__.__name__ == "CommunicationEvidenceLink":
                raise RuntimeError("link persistence failed")
            self.added.append(obj)

        async def execute(self, *_a: Any, **_k: Any) -> Any:
            class _R:
                def scalar_one_or_none(self_inner: Any) -> Any:
                    return throughput_row

                def scalars(self_inner: Any) -> Any:
                    return iter([])

            return _R()

        async def commit(self) -> None:
            self.commits += 1

        async def rollback(self) -> None:
            self.rollbacks += 1
            self.added.clear()

        async def flush(self) -> None:
            return None

        async def refresh(self, *_a: Any, **_k: Any) -> None:
            return None

    async def _pack(*_a: Any, **_k: Any) -> Any:
        return pack

    async def _project(*_a: Any, **_k: Any) -> Any:
        return SimpleNamespace(id=PROJECT_ID, org_id=ORG_ID, name="P")

    async def _body(*_a: Any, **_k: Any) -> str:
        return "Body"

    monkeypatch.setattr(
        "app.agents.client_intelligence.evidence_pack.build_client_evidence_pack",
        _pack,
    )
    monkeypatch.setattr(
        "app.api.routes.communications.get_visible_project",
        _project,
    )
    monkeypatch.setattr(
        "app.api.routes.communications.generate_comms_draft_body",
        _body,
    )
    session = TrackingSession()
    with pytest.raises(RuntimeError, match="link persistence failed"):
        await communications_route.draft_communication(
            PROJECT_ID,
            CommunicationDraftCreate(
                comm_type=CommunicationType.AD_HOC,
                subject="Subject",
            ),
            session,
            _user(),
        )
    assert session.commits == 0
    assert session.rollbacks == 1
    assert not any(
        item.__class__.__name__ == "ClientCommunication" for item in session.added
    )
    assert not any(
        item.__class__.__name__ == "CommunicationEvidenceLink" for item in session.added
    )


def test_conflicting_duplicate_provenance_fails_closed() -> None:
    row = uuid4()
    fingerprint = "f" * 64
    observed = datetime(2026, 7, 16, tzinfo=UTC)
    left = EvidenceInput(
        "quality_snapshots",
        row,
        "a",
        visibility=EvidenceVisibility.INTERNAL.value,
        observed_at=observed,
        claim_keys=("iso_year", "iso_week"),
        pack_source_fingerprint=fingerprint,
    )
    right = EvidenceInput(
        "quality_snapshots",
        row,
        "a",
        visibility=EvidenceVisibility.CLIENT_SAFE.value,
        observed_at=observed,
        claim_keys=("iso_year", "iso_week"),
        pack_source_fingerprint=fingerprint,
    )
    with pytest.raises(ApiError) as exc:
        dedupe_evidence_inputs([left, right])
    assert exc.value.code == ERROR_EVIDENCE_PROVENANCE_CONFLICT


def test_stable_provenance_error_codes() -> None:
    assert ERROR_EVIDENCE_PROVENANCE_UNMATCHED == "EVIDENCE_PROVENANCE_UNMATCHED"
    assert ERROR_EVIDENCE_PROVENANCE_INCOMPLETE == "EVIDENCE_PROVENANCE_INCOMPLETE"


def test_helper_internal_vs_client_projection() -> None:
    """Unit helper projection check — route-level redaction is covered separately."""
    communication = _communication(
        evidence_source_fingerprint="a" * 64,
        status=CommunicationStatus.SENT,
    )
    complete_link = EvidenceLinkRead(
        id=uuid4(),
        source_table="throughput_snapshots",
        source_row_id=uuid4(),
        description="Latest",
        visibility=EvidenceVisibility.INTERNAL.value,
        observed_at=datetime(2026, 7, 16, tzinfo=UTC),
        claim_keys=["snapshot_date"],
        pack_source_fingerprint="a" * 64,
        evidence_provenance_complete=True,
    )
    internal = communications_route._communication_read_with_links(
        communication,
        [complete_link],
        include_provenance=True,
    )
    assert internal.evidence_source_fingerprint == "a" * 64
    client = communications_route._communication_read_with_links(
        communication,
        [
            EvidenceLinkRead(
                id=complete_link.id,
                source_table=complete_link.source_table,
                source_row_id=complete_link.source_row_id,
                description=complete_link.description,
            )
        ],
        include_provenance=False,
    )
    assert client.evidence_source_fingerprint is None
    assert client.evidence_links[0].claim_keys == []


def test_route_source_has_no_stale_evidence_bypass() -> None:
    source = Path(communications_route.__file__).read_text(encoding="utf-8")
    assert "except Exception:" in source
    assert "await session.rollback()" in source
    assert "quality_summaries" not in source
    assert "EVIDENCE_FINGERPRINT_REQUIRED" in source
