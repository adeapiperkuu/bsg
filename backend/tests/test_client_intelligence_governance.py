"""Client Intelligence Project Governance evidence adapter tests."""

from __future__ import annotations

import re
from datetime import UTC, date, datetime, time
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest

from app.agents.client_intelligence import (
    DataQualityState,
    EvidenceVisibility,
    build_client_evidence_pack,
    load_governance_evidence,
    resolve_reporting_period,
)
from app.agents.client_intelligence import governance_adapter as gov_mod
from app.agents.client_intelligence.evidence_pack import (
    _fingerprint,
)
from app.core.exceptions import ApiError
from app.core.security import CurrentUser
from app.db.models import (
    AppRole,
    GovernanceActionStatus,
    GovernanceCharterStatus,
    GovernanceDependencyStatus,
    GovernanceDependencyType,
    GovernanceEscalationSeverity,
    GovernanceEscalationStatus,
    GovernanceScopeStatus,
    KnowledgeVisibility,
    ProjectStatus,
)

_PAST = datetime(2026, 1, 1, tzinfo=UTC)
_FUTURE = datetime(2026, 6, 25, tzinfo=UTC)
_AS_OF = date(2026, 6, 18)


class FakeScalars:
    def __init__(self, items: list[object] | None = None) -> None:
        self._items = items or []

    def all(self) -> list[object]:
        return list(self._items)

    def __iter__(self):
        return iter(self._items)


class FakeResult:
    def __init__(self, value: object = None, items: list[object] | None = None) -> None:
        self._value = value
        self._items = items or []

    def scalar_one_or_none(self) -> object:
        return self._value if self._value is not None else (self._items[0] if self._items else None)

    def scalars(self) -> FakeScalars:
        return FakeScalars(self._items)

    def all(self) -> list[object]:
        return list(self._items)

    def first(self) -> object | None:
        if self._items:
            return self._items[0]
        return self._value


class FakeSession:
    def __init__(
        self,
        *,
        as_of: date | None = None,
        scopes: list[object] | None = None,
        charters: list[object] | None = None,
        dependencies: list[object] | None = None,
        actions: list[object] | None = None,
        escalations: list[object] | None = None,
        milestones: list[object] | None = None,
    ) -> None:
        self.as_of = as_of or _AS_OF
        self.as_of_end = datetime.combine(self.as_of, time.max, tzinfo=UTC)
        self.scopes = scopes or []
        self.charters = charters or []
        self.dependencies = dependencies or []
        self.actions = actions or []
        self.escalations = escalations or []
        self.milestones = milestones or []
        self.statements: list[str] = []

    def _created_ok(self, row: object) -> bool:
        created = getattr(row, "created_at", None)
        return created is None or created <= self.as_of_end

    async def execute(self, stmt) -> FakeResult:
        compiled = str(stmt.compile(compile_kwargs={"literal_binds": True}))
        self.statements.append(compiled)
        assert "LIMIT" in compiled.upper() or "limit" in compiled
        lower = compiled.lower()

        if "FROM project_scope_states" in compiled:
            assert "notes" not in lower
            assert "created_by" not in lower
            assert "updated_by" not in lower
            assert "linked_charter_document_id" not in lower
            rows = [r for r in self.scopes if self._created_ok(r)]
            return FakeResult(None, rows)
        if "FROM project_charters" in compiled:
            assert "generated_text" not in lower
            assert "approved_by" not in lower
            assert "knowledge_document_id" not in lower
            rows = [r for r in self.charters if self._created_ok(r)]
            if "client_safe" in lower:
                rows = [
                    r
                    for r in rows
                    if getattr(r, "status", None) == GovernanceCharterStatus.APPROVED
                    and getattr(r, "visibility", None) == KnowledgeVisibility.CLIENT_SAFE
                ]
                rows.sort(
                    key=lambda r: (
                        r.approved_at is None,
                        -(r.approved_at.timestamp() if r.approved_at else 0),
                        -(r.created_at.timestamp() if r.created_at else 0),
                        str(r.id),
                    )
                )
            elif "'approved'" in lower:
                rows = [
                    r
                    for r in rows
                    if getattr(r, "status", None) == GovernanceCharterStatus.APPROVED
                ]
                rows.sort(
                    key=lambda r: (
                        r.approved_at is None,
                        -(r.approved_at.timestamp() if r.approved_at else 0),
                        -(r.created_at.timestamp() if r.created_at else 0),
                        str(r.id),
                    )
                )
            else:
                rows.sort(
                    key=lambda r: (
                        -(r.created_at.timestamp() if r.created_at else 0),
                        str(r.id),
                    )
                )
            limit_match = re.search(r"LIMIT\s+(\d+)", compiled, re.IGNORECASE)
            if limit_match:
                rows = rows[: int(limit_match.group(1))]
            return FakeResult(None, rows)
        if "FROM project_dependencies" in compiled:
            assert "title" not in lower
            assert "description" not in lower
            assert "owner_id" not in lower
            assert "created_by" not in lower
            rows = [r for r in self.dependencies if self._created_ok(r)]
            return FakeResult(None, rows)
        if "FROM governance_actions" in compiled:
            assert "title" not in lower
            assert "description" not in lower
            assert "owner_id" not in lower
            assert "linked_knowledge_document_id" not in lower
            rows = [r for r in self.actions if self._created_ok(r)]
            return FakeResult(None, rows)
        if "FROM governance_escalations" in compiled:
            assert "title" not in lower
            assert "description" not in lower
            assert "raised_by" not in lower
            assert "assigned_to" not in lower
            assert "source_id" not in lower
            rows = [
                r
                for r in self.escalations
                if self._created_ok(r) and getattr(r, "raised_at", self.as_of_end) <= self.as_of_end
            ]
            return FakeResult(None, rows)
        if "FROM governance_weekly_summaries" in compiled:
            raise AssertionError("summary_text source must not be queried")
        if "FROM knowledge_documents" in compiled:
            assert "extracted_text" not in lower
            return FakeResult(None, [])
        if (
            re.search(r"\bselect\s+1\b", compiled, re.IGNORECASE)
            or (
                "knowledge_document_chunks" in lower
                and "chunk_text" not in lower
            )
        ):
            return FakeResult(None, [])
        if "FROM knowledge_document_versions" in compiled:
            assert "file_name" not in lower
            assert "file_url" not in lower
            assert "storage_path" not in lower
            assert "uploaded_by" not in lower
            assert "approved_by" not in lower
            return FakeResult(None, [])
        if "FROM knowledge_document_chunks" in compiled or "knowledge_document_chunks" in compiled:
            assert "embedding" not in lower
            return FakeResult(None, [])
        if "FROM knowledge_document_embeddings" in compiled:
            raise AssertionError("Knowledge embeddings must not be queried")
        if "FROM client_communications" in compiled:
            raise AssertionError("ClientCommunication must not be queried by Knowledge adapter")
        if "FROM milestones" in compiled:
            return FakeResult(None, self.milestones)
        if "FROM teams" in compiled:
            return FakeResult(None, [])
        if "FROM annotators" in compiled:
            return FakeResult(None, [])
        if "FROM utilization_snapshots" in compiled:
            return FakeResult(None, [])
        if "FROM project_skill_requirements" in compiled:
            return FakeResult(None, [])
        if "FROM skills" in compiled:
            return FakeResult(None, [])
        if "FROM annotator_skills" in compiled:
            return FakeResult(None, [])
        if "FROM training_programs" in compiled:
            return FakeResult(None, [])
        if "FROM training_records" in compiled:
            return FakeResult(None, [])
        if "FROM capability_gaps" in compiled:
            return FakeResult(None, [])
        if "FROM quality_snapshots" in compiled:
            return FakeResult(None, [])
        if "FROM metric_configurations" in compiled:
            return FakeResult(None, [])
        if "FROM throughput_snapshots" in compiled:
            upper = compiled.upper()
            if "SNAPSHOT_DATE ASC" in upper and "LIMIT" not in upper:
                rows = getattr(self, "throughput_series", None)
                if rows is None and getattr(self, "throughput", None) is not None:
                    rows = [self.throughput]
                return FakeResult(None, rows or [])
            return FakeResult(None)
        if "FROM delivery_confidence_scores" in compiled:
            return FakeResult(None)
        if "FROM risk_alerts" in compiled:
            return FakeResult(None, [])
        if "FROM bottlenecks" in compiled:
            return FakeResult(None, [])
        return FakeResult(None, [])


def _user(role: AppRole, org_id=None) -> CurrentUser:
    return CurrentUser(
        id=uuid4(),
        org_id=org_id or uuid4(),
        email="ci-gov@example.com",
        role=role,
        is_active=True,
    )


def _project(org_id=None) -> SimpleNamespace:
    return SimpleNamespace(
        id=uuid4(),
        org_id=org_id or uuid4(),
        name="Aurora Labeling",
        status=ProjectStatus.ACTIVE,
    )


def _scope(**kwargs) -> SimpleNamespace:
    data = {
        "id": uuid4(),
        "scope_status": GovernanceScopeStatus.APPROVED,
        "version_label": "v1",
        "updated_at": _PAST,
        "created_at": _PAST,
        "notes": "SECRET_NOTES",
        "created_by": uuid4(),
    }
    data.update(kwargs)
    return SimpleNamespace(**data)


def _charter(**kwargs) -> SimpleNamespace:
    data = {
        "id": uuid4(),
        "version": "1.0",
        "status": GovernanceCharterStatus.APPROVED,
        "visibility": KnowledgeVisibility.CLIENT_SAFE,
        "approved_at": datetime(2026, 6, 1, tzinfo=UTC),
        "created_at": _PAST,
        "generated_text": "SECRET_CHARTER_NARRATIVE",
        "approved_by": uuid4(),
        "knowledge_document_id": uuid4(),
    }
    data.update(kwargs)
    return SimpleNamespace(**data)


def _dependency(**kwargs) -> SimpleNamespace:
    data = {
        "id": uuid4(),
        "dependency_type": GovernanceDependencyType.CLIENT_ACTION,
        "status": GovernanceDependencyStatus.OPEN,
        "due_date": date(2026, 6, 10),
        "resolved_at": None,
        "created_at": _PAST,
        "title": "SECRET_DEP_TITLE",
        "description": "SECRET_DEP_DESC",
        "owner_id": uuid4(),
    }
    data.update(kwargs)
    return SimpleNamespace(**data)


def _action(**kwargs) -> SimpleNamespace:
    data = {
        "id": uuid4(),
        "status": GovernanceActionStatus.OPEN,
        "due_date": date(2026, 6, 10),
        "completed_at": None,
        "created_at": _PAST,
        "title": "SECRET_ACTION_TITLE",
        "description": "SECRET_ACTION_DESC",
        "owner_id": uuid4(),
    }
    data.update(kwargs)
    return SimpleNamespace(**data)


def _escalation(**kwargs) -> SimpleNamespace:
    data = {
        "id": uuid4(),
        "severity": GovernanceEscalationSeverity.CRITICAL,
        "status": GovernanceEscalationStatus.OPEN,
        "raised_at": datetime(2026, 6, 5, tzinfo=UTC),
        "resolved_at": None,
        "source_type": None,
        "created_at": _PAST,
        "title": "SECRET_ESC_TITLE",
        "description": "SECRET_ESC_DESC",
        "raised_by": uuid4(),
        "assigned_to": uuid4(),
        "source_id": uuid4(),
    }
    data.update(kwargs)
    return SimpleNamespace(**data)


@pytest.mark.asyncio
async def test_auth_before_governance_queries() -> None:
    project = _project()
    user = _user(AppRole.DELIVERY_MANAGER, project.org_id)
    session = FakeSession(scopes=[_scope()])
    with (
        patch(
            "app.agents.client_intelligence.evidence_pack.get_visible_project",
            new=AsyncMock(side_effect=ApiError(404, "NOT_FOUND", "missing")),
        ),
        pytest.raises(ApiError),
    ):
        await build_client_evidence_pack(session, user, project.id, as_of=_AS_OF)
    assert session.statements == []


@pytest.mark.asyncio
async def test_internal_aggregates_and_structured_rows() -> None:
    org_id = uuid4()
    period = resolve_reporting_period(_AS_OF)
    dep = _dependency(status=GovernanceDependencyStatus.BLOCKING)
    action = _action(status=GovernanceActionStatus.OVERDUE)
    esc = _escalation()
    session = FakeSession(
        scopes=[_scope()],
        charters=[_charter(visibility=KnowledgeVisibility.INTERNAL_ONLY)],
        dependencies=[dep, _dependency(status=GovernanceDependencyStatus.RESOLVED, due_date=None)],
        actions=[action, _action(status=GovernanceActionStatus.COMPLETED)],
        escalations=[esc],
    )
    facts, evidence, issues, _, limitations = await load_governance_evidence(
        session,
        uuid4(),
        org_id,
        period,
        visibility_mode=EvidenceVisibility.INTERNAL,
    )
    assert facts.scope is not None
    assert facts.scope.scope_state_id is not None
    assert facts.charter is not None
    assert facts.charter.visibility == KnowledgeVisibility.INTERNAL_ONLY.value
    assert facts.summary.dependency_count == 2
    assert facts.summary.open_dependency_count == 1
    assert facts.summary.blocking_dependency_count == 1
    assert facts.summary.overdue_dependency_count == 1
    assert facts.summary.client_action_dependency_count == 2
    assert facts.summary.action_count == 2
    assert facts.summary.overdue_action_count == 1
    assert facts.summary.critical_escalation_count == 1
    assert len(facts.dependencies) == 2
    assert len(facts.actions) == 2
    assert len(facts.escalations) == 1
    blob = str(facts.model_dump(mode="json")).lower()
    assert "secret" not in blob
    assert "generated_text" not in blob
    assert all(item.source_agent.value == "project_governance" for item in evidence)
    assert any("current-state" in item for item in limitations)


@pytest.mark.asyncio
async def test_client_safe_hides_rows_and_internal_charter() -> None:
    org_id = uuid4()
    period = resolve_reporting_period(_AS_OF)
    hidden = _charter(visibility=KnowledgeVisibility.INTERNAL_ONLY)
    session = FakeSession(
        scopes=[_scope()],
        charters=[hidden],
        dependencies=[_dependency()],
        actions=[_action()],
        escalations=[_escalation()],
    )
    facts, evidence, _, vis, _ = await load_governance_evidence(
        session,
        uuid4(),
        org_id,
        period,
        visibility_mode=EvidenceVisibility.CLIENT_SAFE,
    )
    assert facts.charter is None
    assert facts.dependencies == []
    assert facts.actions == []
    assert facts.escalations == []
    assert facts.scope is not None
    assert facts.scope.scope_state_id is None
    assert facts.summary.dependency_count == 1
    assert facts.summary.client_action_dependency_count == 1
    assert all(
        not (item.category == "dependency_type" and item.status in {"internal", "external"})
        for item in facts.summary.grouped_counts
    )
    assert any(item.reason == "not_client_safe" for item in vis)
    blob = str(facts.model_dump(mode="json")).lower()
    assert "secret" not in blob
    assert str(hidden.id).lower() not in blob
    for item in evidence:
        assert "title" not in item.claim_keys
        assert "description" not in item.claim_keys
        assert "owner_id" not in item.claim_keys
        assert "generated_text" not in item.claim_keys


@pytest.mark.asyncio
async def test_client_safe_approved_charter_only() -> None:
    org_id = uuid4()
    period = resolve_reporting_period(_AS_OF)
    approved = _charter()
    draft = _charter(status=GovernanceCharterStatus.DRAFT, approved_at=None)
    archived = _charter(status=GovernanceCharterStatus.ARCHIVED)
    future_approved = _charter(approved_at=_FUTURE)
    session = FakeSession(
        charters=[approved, draft, archived, future_approved],
    )
    facts, _, _, _, _ = await load_governance_evidence(
        session,
        uuid4(),
        org_id,
        period,
        visibility_mode=EvidenceVisibility.CLIENT_SAFE,
    )
    assert facts.charter is not None
    assert facts.charter.charter_id == approved.id
    assert facts.summary.client_safe_charter_present is True


@pytest.mark.asyncio
async def test_no_scope_unavailable_and_empty_lists_complete() -> None:
    org_id = uuid4()
    period = resolve_reporting_period(_AS_OF)
    session = FakeSession()
    facts, _, issues, _, _ = await load_governance_evidence(
        session,
        uuid4(),
        org_id,
        period,
        visibility_mode=EvidenceVisibility.INTERNAL,
    )
    by_source = {i.source: i.state for i in issues}
    assert facts.scope is None
    assert by_source["governance_scope"] == DataQualityState.UNAVAILABLE
    assert by_source["governance_dependencies"] == DataQualityState.COMPLETE
    assert by_source["governance_actions"] == DataQualityState.COMPLETE
    assert by_source["governance_escalations"] == DataQualityState.COMPLETE
    assert facts.summary.dependency_count == 0


@pytest.mark.asyncio
async def test_multiple_scope_rows_conflicting() -> None:
    org_id = uuid4()
    period = resolve_reporting_period(_AS_OF)
    newer = _scope(version_label="v2", updated_at=datetime(2026, 6, 1, tzinfo=UTC))
    older = _scope(version_label="v1", updated_at=datetime(2026, 5, 1, tzinfo=UTC))
    session = FakeSession(scopes=[newer, older])
    facts, _, issues, _, _ = await load_governance_evidence(
        session,
        uuid4(),
        org_id,
        period,
        visibility_mode=EvidenceVisibility.INTERNAL,
    )
    assert facts.scope is not None
    assert facts.scope.version_label == "v2"
    assert {i.source: i.state for i in issues}["governance_scope"] == DataQualityState.CONFLICTING


@pytest.mark.asyncio
async def test_historical_excludes_future_rows() -> None:
    org_id = uuid4()
    period = resolve_reporting_period(_AS_OF)
    session = FakeSession(
        scopes=[_scope(created_at=_FUTURE), _scope()],
        charters=[_charter(created_at=_FUTURE), _charter()],
        dependencies=[_dependency(created_at=_FUTURE), _dependency()],
        actions=[_action(created_at=_FUTURE)],
        escalations=[_escalation(raised_at=_FUTURE, created_at=_FUTURE)],
    )
    facts, evidence, _, _, limitations = await load_governance_evidence(
        session,
        uuid4(),
        org_id,
        period,
        visibility_mode=EvidenceVisibility.INTERNAL,
    )
    assert facts.scope is not None
    assert facts.summary.dependency_count == 1
    assert facts.summary.action_count == 0
    assert facts.summary.escalation_count == 0
    assert any("current-state" in item for item in limitations)
    assert all(item.source_table != "governance_escalations" for item in evidence)


@pytest.mark.asyncio
async def test_limit_plus_one_dependencies() -> None:
    org_id = uuid4()
    period = resolve_reporting_period(_AS_OF)
    deps = [_dependency() for _ in range(3)]
    with patch.object(gov_mod, "_MAX_DEPENDENCIES", 2):
        session = FakeSession(dependencies=deps)
        facts, _, issues, _, _ = await load_governance_evidence(
            session,
            uuid4(),
            org_id,
            period,
            visibility_mode=EvidenceVisibility.INTERNAL,
        )
    assert facts.summary.dependency_count == 2
    assert len(facts.dependencies) == 2
    states = {i.source: i.state for i in issues}
    assert states["governance_dependencies"] == DataQualityState.PARTIAL


@pytest.mark.asyncio
async def test_exact_max_not_truncation() -> None:
    org_id = uuid4()
    period = resolve_reporting_period(_AS_OF)
    deps = [_dependency() for _ in range(2)]
    with patch.object(gov_mod, "_MAX_DEPENDENCIES", 2):
        session = FakeSession(dependencies=deps)
        facts, _, issues, _, _ = await load_governance_evidence(
            session,
            uuid4(),
            org_id,
            period,
            visibility_mode=EvidenceVisibility.INTERNAL,
        )
    assert facts.summary.dependency_count == 2
    states = {i.source: i.state for i in issues}
    assert states["governance_dependencies"] == DataQualityState.COMPLETE


@pytest.mark.asyncio
async def test_fingerprint_aggregate_and_hidden_text() -> None:
    org_id = uuid4()
    period = resolve_reporting_period(_AS_OF)
    dep = _dependency()
    left_session = FakeSession(dependencies=[dep])
    right_session = FakeSession(
        dependencies=[
            _dependency(
                id=dep.id,
                dependency_type=dep.dependency_type,
                status=dep.status,
                due_date=dep.due_date,
                created_at=dep.created_at,
                title="DIFFERENT_SECRET",
            )
        ]
    )
    changed_session = FakeSession(
        dependencies=[_dependency(status=GovernanceDependencyStatus.BLOCKING)]
    )
    left, left_ev, _, _, _ = await load_governance_evidence(
        left_session,
        uuid4(),
        org_id,
        period,
        visibility_mode=EvidenceVisibility.CLIENT_SAFE,
    )
    right, right_ev, _, _, _ = await load_governance_evidence(
        right_session,
        uuid4(),
        org_id,
        period,
        visibility_mode=EvidenceVisibility.CLIENT_SAFE,
    )
    changed, changed_ev, _, _, _ = await load_governance_evidence(
        changed_session,
        uuid4(),
        org_id,
        period,
        visibility_mode=EvidenceVisibility.CLIENT_SAFE,
    )
    project_id = uuid4()
    fp_left = _fingerprint(
        project_id=project_id,
        reporting_period_start=period.start_date,
        reporting_period_end=period.end_date,
        visibility_mode=EvidenceVisibility.CLIENT_SAFE,
        evidence=left_ev,
        governance=left,
    )
    fp_right = _fingerprint(
        project_id=project_id,
        reporting_period_start=period.start_date,
        reporting_period_end=period.end_date,
        visibility_mode=EvidenceVisibility.CLIENT_SAFE,
        evidence=right_ev,
        governance=right,
    )
    fp_changed = _fingerprint(
        project_id=project_id,
        reporting_period_start=period.start_date,
        reporting_period_end=period.end_date,
        visibility_mode=EvidenceVisibility.CLIENT_SAFE,
        evidence=changed_ev,
        governance=changed,
    )
    assert fp_left == fp_right
    assert fp_left != fp_changed


@pytest.mark.asyncio
async def test_hidden_charter_does_not_affect_client_safe_fingerprint() -> None:
    org_id = uuid4()
    period = resolve_reporting_period(_AS_OF)
    scope = _scope()
    without = FakeSession(scopes=[scope])
    with_hidden = FakeSession(
        scopes=[scope],
        charters=[_charter(visibility=KnowledgeVisibility.INTERNAL_ONLY)],
    )
    left, left_ev, _, _, _ = await load_governance_evidence(
        without,
        uuid4(),
        org_id,
        period,
        visibility_mode=EvidenceVisibility.CLIENT_SAFE,
    )
    right, right_ev, _, _, _ = await load_governance_evidence(
        with_hidden,
        uuid4(),
        org_id,
        period,
        visibility_mode=EvidenceVisibility.CLIENT_SAFE,
    )
    assert left.charter is None and right.charter is None
    assert left.summary.client_safe_charter_present is False
    assert right.summary.client_safe_charter_present is False
    project_id = uuid4()
    assert _fingerprint(
        project_id=project_id,
        reporting_period_start=period.start_date,
        reporting_period_end=period.end_date,
        visibility_mode=EvidenceVisibility.CLIENT_SAFE,
        evidence=left_ev,
        governance=left,
    ) == _fingerprint(
        project_id=project_id,
        reporting_period_start=period.start_date,
        reporting_period_end=period.end_date,
        visibility_mode=EvidenceVisibility.CLIENT_SAFE,
        evidence=right_ev,
        governance=right,
    )


@pytest.mark.asyncio
async def test_pack_integration_client_role() -> None:
    project = _project()
    user = _user(AppRole.CLIENT, project.org_id)
    session = FakeSession(
        scopes=[_scope()],
        charters=[_charter()],
        dependencies=[_dependency()],
    )
    with patch(
        "app.agents.client_intelligence.evidence_pack.get_visible_project",
        new=AsyncMock(return_value=project),
    ):
        pack = await build_client_evidence_pack(session, user, project.id, as_of=_AS_OF)
    assert pack.visibility_mode == EvidenceVisibility.CLIENT_SAFE
    assert pack.governance.charter is not None
    assert pack.governance.dependencies == []
    blob = str(pack.model_dump(mode="json")).lower()
    assert "secret" not in blob
    assert "generated_text" not in blob
    assert "summary_text" not in blob
    assert any("FROM metric_configurations" in s for s in session.statements)


@pytest.mark.asyncio
async def test_approved_client_safe_missing_approved_at_is_partial() -> None:
    org_id = uuid4()
    period = resolve_reporting_period(_AS_OF)
    malformed = _charter(approved_at=None)
    session = FakeSession(charters=[malformed])
    facts, evidence, issues, vis, limitations = await load_governance_evidence(
        session,
        uuid4(),
        org_id,
        period,
        visibility_mode=EvidenceVisibility.CLIENT_SAFE,
    )
    assert facts.charter is None
    charter_issues = [i for i in issues if i.source == "governance_charter"]
    assert len(charter_issues) == 1
    assert charter_issues[0].state == DataQualityState.PARTIAL
    assert any(item.reason == "missing_approved_at" for item in vis)
    assert not any(item.reason == "not_client_safe" for item in vis)
    assert any("approved_at is missing" in item for item in limitations)
    assert all(item.source_table != "project_charters" for item in evidence)
    assert facts.summary.client_safe_charter_present is False
    assert str(malformed.id).lower() not in str(facts.model_dump(mode="json")).lower()


@pytest.mark.asyncio
async def test_approved_after_as_of_distinct_from_missing_approved_at() -> None:
    org_id = uuid4()
    period = resolve_reporting_period(_AS_OF)
    future = _charter(approved_at=_FUTURE)
    session = FakeSession(charters=[future])
    facts, evidence, issues, vis, _ = await load_governance_evidence(
        session,
        uuid4(),
        org_id,
        period,
        visibility_mode=EvidenceVisibility.CLIENT_SAFE,
    )
    assert facts.charter is None
    assert {i.source: i.state for i in issues}["governance_charter"] == DataQualityState.COMPLETE
    assert any(item.reason == "approved_after_as_of" for item in vis)
    assert not any(item.reason == "missing_approved_at" for item in vis)
    assert all(item.source_table != "project_charters" for item in evidence)


@pytest.mark.asyncio
async def test_normal_charter_version_history_is_complete() -> None:
    org_id = uuid4()
    period = resolve_reporting_period(_AS_OF)
    archived = _charter(
        version="1.0",
        status=GovernanceCharterStatus.ARCHIVED,
        created_at=datetime(2026, 1, 1, tzinfo=UTC),
    )
    approved = _charter(
        version="2.0",
        status=GovernanceCharterStatus.APPROVED,
        visibility=KnowledgeVisibility.INTERNAL_ONLY,
        created_at=datetime(2026, 5, 1, tzinfo=UTC),
    )
    session = FakeSession(charters=[archived, approved])
    facts, _, issues, _, _ = await load_governance_evidence(
        session,
        uuid4(),
        org_id,
        period,
        visibility_mode=EvidenceVisibility.INTERNAL,
    )
    assert facts.charter is not None
    assert facts.charter.version == "2.0"
    assert {i.source: i.state for i in issues}["governance_charter"] == DataQualityState.COMPLETE

    draft_latest = _charter(
        version="3.0",
        status=GovernanceCharterStatus.DRAFT,
        approved_at=None,
        created_at=datetime(2026, 6, 1, tzinfo=UTC),
    )
    session2 = FakeSession(charters=[approved, draft_latest])
    facts2, _, issues2, _, _ = await load_governance_evidence(
        session2,
        uuid4(),
        org_id,
        period,
        visibility_mode=EvidenceVisibility.INTERNAL,
    )
    assert facts2.charter is not None
    assert facts2.charter.version == "3.0"
    assert {i.source: i.state for i in issues2}["governance_charter"] == DataQualityState.COMPLETE


@pytest.mark.asyncio
async def test_competing_approved_charters_conflict() -> None:
    org_id = uuid4()
    period = resolve_reporting_period(_AS_OF)
    first = _charter(version="1.0", created_at=datetime(2026, 4, 1, tzinfo=UTC))
    second = _charter(version="2.0", created_at=datetime(2026, 5, 1, tzinfo=UTC))
    session = FakeSession(charters=[first, second])
    facts, _, issues, _, _ = await load_governance_evidence(
        session,
        uuid4(),
        org_id,
        period,
        visibility_mode=EvidenceVisibility.INTERNAL,
    )
    assert facts.charter is not None
    charter_issues = [i for i in issues if i.source == "governance_charter"]
    assert len(charter_issues) == 1
    assert charter_issues[0].state == DataQualityState.CONFLICTING


@pytest.mark.asyncio
async def test_client_safe_omits_internal_external_dependency_types() -> None:
    org_id = uuid4()
    period = resolve_reporting_period(_AS_OF)
    session = FakeSession(
        dependencies=[
            _dependency(dependency_type=GovernanceDependencyType.INTERNAL),
            _dependency(dependency_type=GovernanceDependencyType.EXTERNAL),
            _dependency(dependency_type=GovernanceDependencyType.CLIENT_ACTION),
        ]
    )
    safe, _, _, _, _ = await load_governance_evidence(
        session,
        uuid4(),
        org_id,
        period,
        visibility_mode=EvidenceVisibility.CLIENT_SAFE,
    )
    internal, _, _, _, _ = await load_governance_evidence(
        session,
        uuid4(),
        org_id,
        period,
        visibility_mode=EvidenceVisibility.INTERNAL,
    )
    assert safe.summary.client_action_dependency_count == 1
    assert safe.summary.dependency_count == 3
    pairs = [[c.category, c.status] for c in safe.summary.grouped_counts]
    assert ["dependency_type", "internal"] not in pairs
    assert ["dependency_type", "external"] not in pairs
    assert any(
        c.category == "dependency_type" and c.status == "internal"
        for c in internal.summary.grouped_counts
    )


@pytest.mark.asyncio
async def test_hidden_dependency_type_change_does_not_affect_client_safe_fingerprint() -> None:
    org_id = uuid4()
    period = resolve_reporting_period(_AS_OF)
    dep_a = uuid4()
    dep_b = uuid4()
    left_session = FakeSession(
        dependencies=[
            _dependency(
                id=dep_a,
                dependency_type=GovernanceDependencyType.INTERNAL,
                status=GovernanceDependencyStatus.OPEN,
                due_date=None,
            ),
            _dependency(
                id=dep_b,
                dependency_type=GovernanceDependencyType.CLIENT_ACTION,
                status=GovernanceDependencyStatus.OPEN,
                due_date=None,
            ),
        ]
    )
    right_session = FakeSession(
        dependencies=[
            _dependency(
                id=dep_a,
                dependency_type=GovernanceDependencyType.EXTERNAL,
                status=GovernanceDependencyStatus.OPEN,
                due_date=None,
            ),
            _dependency(
                id=dep_b,
                dependency_type=GovernanceDependencyType.CLIENT_ACTION,
                status=GovernanceDependencyStatus.OPEN,
                due_date=None,
            ),
        ]
    )
    left, left_ev, _, _, _ = await load_governance_evidence(
        left_session,
        uuid4(),
        org_id,
        period,
        visibility_mode=EvidenceVisibility.CLIENT_SAFE,
    )
    right, right_ev, _, _, _ = await load_governance_evidence(
        right_session,
        uuid4(),
        org_id,
        period,
        visibility_mode=EvidenceVisibility.CLIENT_SAFE,
    )
    assert left.summary.model_dump(mode="json") == right.summary.model_dump(mode="json")
    project_id = uuid4()
    assert _fingerprint(
        project_id=project_id,
        reporting_period_start=period.start_date,
        reporting_period_end=period.end_date,
        visibility_mode=EvidenceVisibility.CLIENT_SAFE,
        evidence=left_ev,
        governance=left,
    ) == _fingerprint(
        project_id=project_id,
        reporting_period_start=period.start_date,
        reporting_period_end=period.end_date,
        visibility_mode=EvidenceVisibility.CLIENT_SAFE,
        evidence=right_ev,
        governance=right,
    )

    left_int, left_int_ev, _, _, _ = await load_governance_evidence(
        left_session,
        uuid4(),
        org_id,
        period,
        visibility_mode=EvidenceVisibility.INTERNAL,
    )
    right_int, right_int_ev, _, _, _ = await load_governance_evidence(
        right_session,
        uuid4(),
        org_id,
        period,
        visibility_mode=EvidenceVisibility.INTERNAL,
    )
    assert _fingerprint(
        project_id=project_id,
        reporting_period_start=period.start_date,
        reporting_period_end=period.end_date,
        visibility_mode=EvidenceVisibility.INTERNAL,
        evidence=left_int_ev,
        governance=left_int,
    ) != _fingerprint(
        project_id=project_id,
        reporting_period_start=period.start_date,
        reporting_period_end=period.end_date,
        visibility_mode=EvidenceVisibility.INTERNAL,
        evidence=right_int_ev,
        governance=right_int,
    )


@pytest.mark.asyncio
async def test_client_safe_scope_excludes_scope_state_id_from_projection() -> None:
    org_id = uuid4()
    period = resolve_reporting_period(_AS_OF)
    scope = _scope()
    session = FakeSession(scopes=[scope])
    safe, evidence, _, _, _ = await load_governance_evidence(
        session,
        uuid4(),
        org_id,
        period,
        visibility_mode=EvidenceVisibility.CLIENT_SAFE,
    )
    internal, _, _, _, _ = await load_governance_evidence(
        session,
        uuid4(),
        org_id,
        period,
        visibility_mode=EvidenceVisibility.INTERNAL,
    )
    assert safe.scope is not None
    assert safe.scope.scope_state_id is None
    assert internal.scope is not None
    assert internal.scope.scope_state_id == scope.id
    assert str(scope.id) not in str(safe.model_dump(mode="json"))
    for item in evidence:
        if item.source_table == "project_scope_states":
            assert "scope_state_id" not in item.claim_keys


@pytest.mark.asyncio
async def test_valid_plus_malformed_charter_is_partial() -> None:
    org_id = uuid4()
    period = resolve_reporting_period(_AS_OF)
    valid = _charter(version="2.0", approved_at=datetime(2026, 6, 1, tzinfo=UTC))
    malformed = _charter(version="1.0", approved_at=None)
    session = FakeSession(charters=[valid, malformed])
    facts, evidence, issues, vis, limitations = await load_governance_evidence(
        session,
        uuid4(),
        org_id,
        period,
        visibility_mode=EvidenceVisibility.CLIENT_SAFE,
    )
    assert facts.charter is not None
    assert facts.charter.charter_id == valid.id
    charter_issues = [i for i in issues if i.source == "governance_charter"]
    assert len(charter_issues) == 1
    assert charter_issues[0].state == DataQualityState.PARTIAL
    assert any("lacks approval metadata" in item for item in limitations)
    assert not any(item.reason == "missing_approved_at" for item in vis)
    assert [item.source_row_id for item in evidence if item.source_table == "project_charters"] == [
        valid.id
    ]
    blob = str(facts.model_dump(mode="json")).lower()
    assert str(malformed.id).lower() not in blob
    assert "1.0" not in blob


@pytest.mark.asyncio
async def test_two_valid_plus_malformed_remains_conflicting() -> None:
    org_id = uuid4()
    period = resolve_reporting_period(_AS_OF)
    valid_a = _charter(version="2.0", approved_at=datetime(2026, 5, 1, tzinfo=UTC))
    valid_b = _charter(version="3.0", approved_at=datetime(2026, 6, 1, tzinfo=UTC))
    malformed = _charter(version="1.0", approved_at=None)
    session = FakeSession(charters=[valid_a, valid_b, malformed])
    facts, evidence, issues, _, _ = await load_governance_evidence(
        session,
        uuid4(),
        org_id,
        period,
        visibility_mode=EvidenceVisibility.CLIENT_SAFE,
    )
    assert facts.charter is not None
    assert facts.charter.charter_id == valid_b.id
    assert {i.source: i.state for i in issues}["governance_charter"] == DataQualityState.CONFLICTING
    assert all(item.source_row_id != malformed.id for item in evidence)


@pytest.mark.asyncio
async def test_charter_candidate_bound_truncation_is_partial() -> None:
    org_id = uuid4()
    period = resolve_reporting_period(_AS_OF)
    drafts = [
        _charter(
            version=f"draft-{i}",
            status=GovernanceCharterStatus.DRAFT,
            visibility=KnowledgeVisibility.INTERNAL_ONLY,
            approved_at=None,
            created_at=datetime(2026, 6, 10, tzinfo=UTC),
        )
        for i in range(5)
    ]
    valid = _charter(
        version="keep-me",
        created_at=datetime(2026, 1, 1, tzinfo=UTC),
        approved_at=datetime(2026, 1, 2, tzinfo=UTC),
    )
    with patch.object(gov_mod, "_MAX_CHARTER_METADATA", 2):
        # Exact MAX candidates is not truncation (1 valid + 1 future-approved).
        exact = FakeSession(
            charters=[
                _charter(version="a", approved_at=datetime(2026, 5, 1, tzinfo=UTC)),
                _charter(version="b", approved_at=datetime(2026, 7, 1, tzinfo=UTC)),
            ]
        )
        facts_exact, _, issues_exact, _, limitations_exact = await load_governance_evidence(
            exact,
            uuid4(),
            org_id,
            period,
            visibility_mode=EvidenceVisibility.CLIENT_SAFE,
        )
        assert facts_exact.charter is not None
        assert facts_exact.charter.version == "a"
        assert {i.source: i.state for i in issues_exact}[
            "governance_charter"
        ] == DataQualityState.COMPLETE
        assert not any("truncated" in item.lower() for item in limitations_exact)

        # MAX + 1 candidates: truncate, PARTIAL, project the in-bound valid charter.
        truncated = FakeSession(
            charters=[
                _charter(version="keep", approved_at=datetime(2026, 6, 1, tzinfo=UTC)),
                _charter(version="mal-a", approved_at=None),
                _charter(version="mal-b", approved_at=None),
            ]
        )
        (
            facts_trunc,
            evidence_trunc,
            issues_trunc,
            vis_trunc,
            limitations,
        ) = await load_governance_evidence(
            truncated,
            uuid4(),
            org_id,
            period,
            visibility_mode=EvidenceVisibility.CLIENT_SAFE,
        )
        assert facts_trunc.charter is not None
        assert facts_trunc.charter.version == "keep"
        assert {i.source: i.state for i in issues_trunc}[
            "governance_charter"
        ] == DataQualityState.PARTIAL
        assert any("truncated" in item.lower() for item in limitations)
        assert not any(item.reason == "not_client_safe" for item in vis_trunc)
        assert "mal-a" not in str(facts_trunc.model_dump(mode="json"))
        assert "mal-b" not in str(facts_trunc.model_dump(mode="json"))
        assert all(
            item.source_row_id == facts_trunc.charter.charter_id
            for item in evidence_trunc
            if item.source_table == "project_charters"
        )

        # Truncation must not invent a false not_client_safe COMPLETE state.
        futures_only = FakeSession(
            charters=[
                _charter(version="f1", approved_at=datetime(2026, 7, 1, tzinfo=UTC)),
                _charter(version="f2", approved_at=datetime(2026, 7, 2, tzinfo=UTC)),
                _charter(version="f3", approved_at=datetime(2026, 7, 3, tzinfo=UTC)),
            ]
        )
        facts_future, _, issues_future, vis_future, lim_future = await load_governance_evidence(
            futures_only,
            uuid4(),
            org_id,
            period,
            visibility_mode=EvidenceVisibility.CLIENT_SAFE,
        )
        assert facts_future.charter is None
        assert {i.source: i.state for i in issues_future}[
            "governance_charter"
        ] == DataQualityState.PARTIAL
        assert any("truncated" in item.lower() for item in lim_future)
        assert not any(item.reason == "not_client_safe" for item in vis_future)

        # Newer drafts/internal rows do not hide a valid approved client-safe candidate.
        mixed = FakeSession(charters=[*drafts, valid])
        facts_mixed, evidence, issues_mixed, _, _ = await load_governance_evidence(
            mixed,
            uuid4(),
            org_id,
            period,
            visibility_mode=EvidenceVisibility.CLIENT_SAFE,
        )
        assert facts_mixed.charter is not None
        assert facts_mixed.charter.version == "keep-me"
        assert facts_mixed.charter.charter_id == valid.id
        assert "draft-" not in (facts_mixed.charter.version or "")
        assert {i.source: i.state for i in issues_mixed}[
            "governance_charter"
        ] == DataQualityState.COMPLETE
        assert all(
            item.source_row_id == valid.id
            for item in evidence
            if item.source_table == "project_charters"
        )
        blob = str(facts_mixed.model_dump(mode="json")).lower()
        assert "draft-" not in blob
        assert "generated_text" not in blob
