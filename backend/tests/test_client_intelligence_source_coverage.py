"""Focused tests for CI-D01–CI-D15 source coverage and evidence gap closure."""

from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any
from uuid import UUID, uuid4

import pytest

from app.agents.client_intelligence.contracts import (
    DataQualityState,
    EvidenceVisibility,
    SourceAgent,
)
from app.agents.client_intelligence.delivery_trend_contracts import (
    LIMITATION_PLAN_SERIES_UNAVAILABLE,
)
from app.agents.client_intelligence.source_coverage import (
    LIMITATION_BACKLOG_QUEUE_UNAVAILABLE,
    LIMITATION_CLIENT_COMMUNICATION_NOTES_UNAVAILABLE,
    LIMITATION_FRESHNESS_SLA_UNRESOLVED,
    LIMITATION_WORKFLOW_STATUS_UNAVAILABLE,
    SOURCE_COVERAGE_REGISTRY,
    SourceImplementationState,
    adapter_allowed_source_tables,
    blocked_source_entries,
    explicit_unavailable_pack_signals,
    registry_allowed_source_tables,
    source_coverage_by_id,
)
from app.core.exceptions import ApiError
from app.schemas.domain import CommunicationApprove
from app.services.communications import (
    ERROR_COMMUNICATION_EVIDENCE_CHANGED,
    LIMITATION_LEGACY_EVIDENCE_FINGERPRINT_MISSING,
    approve,
    create_draft,
    send,
)
from app.services.evidence import (
    ERROR_EVIDENCE_PROVENANCE_CONFLICT,
    ERROR_EVIDENCE_PROVENANCE_INCOMPLETE,
    EvidenceInput,
    dedupe_evidence_inputs,
    evidence_provenance_complete,
    require_complete_evidence_provenance,
)
from tests.conftest import FakeSession
from tests.test_communication_lifecycle import RecordingSession, _communication, _user

ORG_ID = UUID("aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa")
PROJECT_ID = UUID("cccccccc-cccc-4ccc-8ccc-cccccccccccc")


def test_source_coverage_registry_covers_ci_d01_through_ci_d15_exactly() -> None:
    ids = [entry.requirement_id for entry in SOURCE_COVERAGE_REGISTRY]
    assert ids == [f"CI-D{str(i).zfill(2)}" for i in range(1, 16)]
    assert len(set(ids)) == 15
    by_id = source_coverage_by_id()
    assert set(by_id) == set(ids)
    for entry in SOURCE_COVERAGE_REGISTRY:
        assert entry.canonical_owner in SourceAgent
        assert entry.canonical_owner in entry.contributing_owners
        assert entry.supported_visibility
        assert entry.sensitivity
        assert entry.implementation_state in SourceImplementationState
        assert entry.freshness_expectation == "unresolved"
        assert entry.expected_ownership
        if entry.implementation_state == SourceImplementationState.UNAVAILABLE:
            assert entry.unavailable_reason
            assert entry.allowed_source_tables == ()
        else:
            assert entry.unavailable_reason is None


def test_ci_d02_is_milestone_plan_and_ci_d03_is_throughput_logs() -> None:
    by_id = source_coverage_by_id()
    assert by_id["CI-D02"].title == "Milestone Plan"
    assert by_id["CI-D02"].allowed_source_tables == ("milestones",)
    assert by_id["CI-D03"].title == "Throughput Logs"
    assert by_id["CI-D03"].allowed_source_tables == ("throughput_snapshots",)
    assert by_id["CI-D03"].implementation_state == SourceImplementationState.PARTIAL
    assert by_id["CI-D03"].unavailable_reason is None


def test_multi_owner_requirements_keep_contributing_owners() -> None:
    by_id = source_coverage_by_id()
    assert SourceAgent.PROJECT_GOVERNANCE in by_id["CI-D10"].contributing_owners
    assert SourceAgent.QUALITY_INTELLIGENCE in by_id["CI-D10"].contributing_owners
    assert SourceAgent.WORKFORCE_CAPABILITY in by_id["CI-D12"].contributing_owners
    assert SourceAgent.PROJECT_GOVERNANCE in by_id["CI-D13"].contributing_owners
    assert SourceAgent.PROJECT_GOVERNANCE in by_id["CI-D15"].contributing_owners


def test_registry_and_adapter_allowed_tables_agree_exactly() -> None:
    """Union parity remains required, but is not sufficient alone."""
    registry = registry_allowed_source_tables()
    adapters = adapter_allowed_source_tables()
    assert registry == adapters


def test_exact_requirement_table_owner_adapter_mapping() -> None:
    from app.agents.client_intelligence.evidence_validation import (
        source_agent_owns_table,
    )
    from app.agents.client_intelligence.source_coverage import (
        adapter_name_for_owner,
        exact_requirement_mappings,
        requirement_accepts_source,
    )

    mappings = exact_requirement_mappings()
    assert len(mappings) == 15
    for row in mappings:
        req = str(row["requirement_id"])
        entry = source_coverage_by_id()[req]
        assert row["title"] == entry.title
        assert row["canonical_owner"] == entry.canonical_owner
        assert row["contributing_owners"] == entry.contributing_owners
        assert row["allowed_source_tables"] == entry.allowed_source_tables
        assert row["supported_visibility"] == entry.supported_visibility
        assert row["adapter"] == adapter_name_for_owner(entry.canonical_owner)
        assert row["implementation_state"] == entry.implementation_state

        if entry.implementation_state == SourceImplementationState.UNAVAILABLE:
            assert entry.allowed_source_tables == ()
            assert requirement_accepts_source(
                req,
                source_table="throughput_snapshots",
                source_agent=entry.canonical_owner,
            ) is False
            continue

        for table in entry.allowed_source_tables:
            assert requirement_accepts_source(
                req,
                source_table=table,
                source_agent=entry.canonical_owner,
            )
            # Wrong owner fails even when table is listed on the requirement.
            wrong_owners = [
                agent
                for agent in SourceAgent
                if agent not in entry.contributing_owners
                and not source_agent_owns_table(agent, table)
            ]
            if wrong_owners:
                assert (
                    requirement_accepts_source(
                        req,
                        source_table=table,
                        source_agent=wrong_owners[0],
                    )
                    is False
                )

        # Wrong requirement assignment fails.
        other = next(
            item
            for item in SOURCE_COVERAGE_REGISTRY
            if item.requirement_id != req
            and item.allowed_source_tables
            and set(item.allowed_source_tables).isdisjoint(entry.allowed_source_tables)
        )
        foreign_table = other.allowed_source_tables[0]
        assert (
            requirement_accepts_source(
                req,
                source_table=foreign_table,
                source_agent=entry.canonical_owner,
            )
            is False
        )


def test_unavailable_requirements_accept_no_populated_evidence() -> None:
    from app.agents.client_intelligence.source_coverage import requirement_accepts_source

    for req in ("CI-D07", "CI-D09", "CI-D14"):
        entry = source_coverage_by_id()[req]
        assert entry.implementation_state == SourceImplementationState.UNAVAILABLE
        assert entry.allowed_source_tables == ()
        for agent in SourceAgent:
            assert (
                requirement_accepts_source(
                    req,
                    source_table="projects",
                    source_agent=agent,
                )
                is False
            )


def test_pack_evidence_maps_to_exact_requirement_owner_pairs() -> None:
    from app.agents.client_intelligence.source_coverage import (
        pack_evidence_requirement_pairs,
        requirement_accepts_source,
    )
    from tests.test_client_intelligence_delivery_confidence import (
        _complete_pack,
        _with_domain_facts,
    )

    pack = _with_domain_facts(_complete_pack(), throughput=True, risk=True, quality=True)
    pairs = pack_evidence_requirement_pairs(pack.evidence)
    assert pairs
    assert all(req != "UNMAPPED" for req, _table, _agent in pairs)
    for req, table, agent in pairs:
        assert requirement_accepts_source(
            req, source_table=table, source_agent=agent
        )


def test_ci_d03_throughput_plan_series_is_sibling_limitation() -> None:
    entry = source_coverage_by_id()["CI-D03"]
    assert entry.title == "Throughput Logs"
    assert entry.implementation_state == SourceImplementationState.PARTIAL
    assert entry.unavailable_reason is None
    limitations, _ = explicit_unavailable_pack_signals()
    assert LIMITATION_PLAN_SERIES_UNAVAILABLE in limitations


def test_blocked_sources_are_explicitly_unavailable_with_stable_reasons() -> None:
    blocked = blocked_source_entries()
    reasons = {entry.requirement_id: entry.unavailable_reason for entry in blocked}
    assert set(reasons) == {"CI-D07", "CI-D09", "CI-D14"}
    assert reasons["CI-D07"] == LIMITATION_WORKFLOW_STATUS_UNAVAILABLE
    assert reasons["CI-D09"] == LIMITATION_BACKLOG_QUEUE_UNAVAILABLE
    assert reasons["CI-D14"] == LIMITATION_CLIENT_COMMUNICATION_NOTES_UNAVAILABLE
    limitations, issues = explicit_unavailable_pack_signals()
    assert LIMITATION_PLAN_SERIES_UNAVAILABLE in limitations
    assert LIMITATION_BACKLOG_QUEUE_UNAVAILABLE in limitations
    assert LIMITATION_WORKFLOW_STATUS_UNAVAILABLE in limitations
    assert LIMITATION_CLIENT_COMMUNICATION_NOTES_UNAVAILABLE in limitations
    assert LIMITATION_FRESHNESS_SLA_UNRESOLVED in limitations
    assert any(item.state == DataQualityState.UNAVAILABLE for item in issues)
    assert all(item.detail for item in issues)
    # Plan-series sibling limitation must not mark CI-D03 unavailable.
    assert source_coverage_by_id()["CI-D03"].unavailable_reason is None
    ci_d07_issue = next(item for item in issues if item.source == "ci_d07")
    assert "project.status is CI-D01" in ci_d07_issue.detail
    assert "bottlenecks remain CI-D10" in ci_d07_issue.detail


def test_plan_series_is_sibling_limitation_not_throughput_unavailable() -> None:
    entry_throughput = source_coverage_by_id()["CI-D03"]
    entry_backlog = source_coverage_by_id()["CI-D09"]
    assert entry_throughput.implementation_state == SourceImplementationState.PARTIAL
    assert entry_throughput.unavailable_reason is None
    assert entry_backlog.implementation_state == SourceImplementationState.UNAVAILABLE
    assert entry_backlog.allowed_source_tables == ()
    limitations, _ = explicit_unavailable_pack_signals()
    assert LIMITATION_PLAN_SERIES_UNAVAILABLE in limitations


def test_evidence_inputs_dedupe_identical_and_fail_on_conflict() -> None:
    row = uuid4()
    fingerprint = "a" * 64
    observed = datetime(2026, 7, 16, tzinfo=UTC)
    complete = EvidenceInput(
        "throughput_snapshots",
        row,
        "same",
        visibility=EvidenceVisibility.INTERNAL.value,
        observed_at=observed,
        claim_keys=("snapshot_date",),
        pack_source_fingerprint=fingerprint,
    )
    items = dedupe_evidence_inputs([complete, complete])
    assert len(items) == 1

    conflicting = EvidenceInput(
        "throughput_snapshots",
        row,
        "different description",
        visibility=EvidenceVisibility.INTERNAL.value,
        observed_at=observed,
        claim_keys=("snapshot_date",),
        pack_source_fingerprint=fingerprint,
    )
    with pytest.raises(ApiError) as exc:
        dedupe_evidence_inputs([complete, conflicting])
    assert exc.value.code == ERROR_EVIDENCE_PROVENANCE_CONFLICT


def test_empty_claim_keys_are_not_complete_provenance() -> None:
    item = EvidenceInput(
        "throughput_snapshots",
        uuid4(),
        "x",
        visibility=EvidenceVisibility.INTERNAL.value,
        observed_at=datetime(2026, 7, 16, tzinfo=UTC),
        claim_keys=(),
        pack_source_fingerprint="a" * 64,
    )
    assert evidence_provenance_complete(item) is False
    with pytest.raises(ApiError) as exc:
        require_complete_evidence_provenance([item])
    assert exc.value.code == ERROR_EVIDENCE_PROVENANCE_INCOMPLETE


@pytest.mark.asyncio
async def test_create_draft_persists_provenance_and_rejects_invalid_fingerprint() -> None:
    session = RecordingSession()
    project = SimpleNamespace(id=PROJECT_ID, org_id=ORG_ID)
    row_id = uuid4()
    fingerprint = "a" * 64
    observed = datetime(2026, 7, 16, tzinfo=UTC)
    draft = await create_draft(
        session,
        project,
        "Subject",
        "Body",
        "weekly_summary",
        [
            EvidenceInput(
                source_table="throughput_snapshots",
                source_row_id=row_id,
                description="Latest throughput",
                visibility=EvidenceVisibility.INTERNAL.value,
                observed_at=observed,
                claim_keys=("snapshot_date", "units_completed"),
                pack_source_fingerprint=fingerprint,
            ),
            EvidenceInput(
                source_table="throughput_snapshots",
                source_row_id=row_id,
                description="Latest throughput",
                visibility=EvidenceVisibility.INTERNAL.value,
                observed_at=observed,
                claim_keys=("snapshot_date", "units_completed"),
                pack_source_fingerprint=fingerprint,
            ),
        ],
        evidence_source_fingerprint=fingerprint,
    )
    assert draft.evidence_source_fingerprint == fingerprint
    links = [
        item
        for item in session.added
        if item.__class__.__name__ == "CommunicationEvidenceLink"
    ]
    assert len(links) == 1
    assert links[0].visibility == EvidenceVisibility.INTERNAL.value
    assert links[0].pack_source_fingerprint == fingerprint
    assert links[0].claim_keys == ["snapshot_date", "units_completed"]
    assert links[0].observed_at == observed

    with pytest.raises(ApiError) as exc:
        await create_draft(
            session,
            project,
            "Subject",
            "Body",
            "weekly_summary",
            [
                EvidenceInput(
                    source_table="throughput_snapshots",
                    source_row_id=row_id,
                    description="Latest throughput",
                    visibility=EvidenceVisibility.INTERNAL.value,
                    observed_at=observed,
                    claim_keys=("snapshot_date",),
                    pack_source_fingerprint=fingerprint,
                )
            ],
            evidence_source_fingerprint="NOT-A-FINGERPRINT",
        )
    assert exc.value.status_code == 422


@pytest.mark.asyncio
async def test_create_draft_rejects_incomplete_provenance() -> None:
    session = RecordingSession()
    project = SimpleNamespace(id=PROJECT_ID, org_id=ORG_ID)
    with pytest.raises(ApiError) as exc:
        await create_draft(
            session,
            project,
            "Subject",
            "Body",
            "ad_hoc",
            [EvidenceInput("throughput_snapshots", uuid4(), "missing provenance")],
            evidence_source_fingerprint="b" * 64,
        )
    assert exc.value.code == ERROR_EVIDENCE_PROVENANCE_INCOMPLETE
    assert not any(
        item.__class__.__name__ == "ClientCommunication" for item in session.added
    )


@pytest.mark.asyncio
async def test_approve_and_send_block_when_evidence_fingerprint_changed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.db.models import CommunicationStatus

    stored = "b" * 64
    current = "c" * 64
    communication = _communication(
        status=CommunicationStatus.IN_REVIEW,
        body_approved="Reviewed body",
        evidence_source_fingerprint=stored,
    )
    user = _user()

    async def _current(*_a: Any, **_k: Any) -> str:
        return current

    monkeypatch.setattr(
        "app.services.communications._current_evidence_fingerprint",
        _current,
    )
    with pytest.raises(ApiError) as approve_exc:
        await approve(
            FakeSession(),
            communication,
            CommunicationApprove(body_approved="Reviewed body"),
            user,
        )
    assert approve_exc.value.code == ERROR_COMMUNICATION_EVIDENCE_CHANGED

    communication.status = CommunicationStatus.APPROVED
    communication.approved_by = user.id
    communication.approved_at = datetime(2026, 7, 16, tzinfo=UTC)
    with pytest.raises(ApiError) as send_exc:
        await send(FakeSession(), communication, user)
    assert send_exc.value.code == ERROR_COMMUNICATION_EVIDENCE_CHANGED


@pytest.mark.asyncio
async def test_unchanged_fingerprint_allows_approve_and_legacy_null_is_disclosed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.db.models import CommunicationStatus

    fingerprint = "d" * 64
    communication = _communication(
        status=CommunicationStatus.IN_REVIEW,
        body_approved="Reviewed body",
        evidence_source_fingerprint=fingerprint,
    )
    user = _user()

    async def _same(*_a: Any, **_k: Any) -> str:
        return fingerprint

    monkeypatch.setattr(
        "app.services.communications._current_evidence_fingerprint",
        _same,
    )
    approved = await approve(
        RecordingSession(),
        communication,
        CommunicationApprove(body_approved="Reviewed body"),
        user,
    )
    assert approved.status == CommunicationStatus.APPROVED

    legacy = _communication(
        status=CommunicationStatus.IN_REVIEW,
        body_approved="Reviewed body",
        evidence_source_fingerprint=None,
    )
    from app.services.communications import _assert_evidence_fingerprint_for_lifecycle

    disclosed = await _assert_evidence_fingerprint_for_lifecycle(
        FakeSession(),
        legacy,
        user,
        action="approve",
    )
    assert disclosed == LIMITATION_LEGACY_EVIDENCE_FINGERPRINT_MISSING
