from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import uuid4

import pytest

from app.agents.governance.services.charter_service import (
    CharterEvidenceItem,
    build_project_charter_read_with_metrics,
    build_template_charter,
    get_project_charters_panel_data,
    build_project_charters_read,
    has_sufficient_charter_evidence,
    invalidate_project_charter_list_cache,
    list_project_charters_page,
    sanitize_charter_text,
)
from app.core.security import CurrentUser
from app.db.models import (
    AppRole,
    GovernanceCharterPublicationStatus,
    GovernanceCharterStatus,
    GovernanceDependencyStatus,
    GovernanceEvidenceSourceType,
    KnowledgeVisibility,
)


class FakeScalars:
    def __init__(self, items):
        self._items = items

    def all(self):
        return self._items


class FakeResult:
    def __init__(self, items):
        self._items = items

    def scalars(self):
        return FakeScalars(self._items)

    def all(self):
        return self._items

    def scalar_one_or_none(self):
        return self._items[0] if self._items else None


class QueueSession:
    def __init__(self, results):
        self.results = list(results)
        self.execute_count = 0

    async def execute(self, *_args, **_kwargs):
        self.execute_count += 1
        return FakeResult(self.results.pop(0) if self.results else [])


def _user(role=AppRole.DELIVERY_MANAGER, org_id=None, user_id=None) -> CurrentUser:
    return CurrentUser(
        id=user_id or uuid4(),
        org_id=org_id or uuid4(),
        email=f"{role.value}@example.com",
        role=role,
        is_active=True,
    )


def _charter(**overrides):
    org_id = overrides.pop("org_id", uuid4())
    project_id = overrides.pop("project_id", uuid4())
    base = {
        "id": uuid4(),
        "org_id": org_id,
        "project_id": project_id,
        "version": "v1",
        "status": GovernanceCharterStatus.APPROVED,
        "generated_text": "## Executive Summary\nTest charter\n\n## Evidence Appendix\nsecret",
        "generated_by_ai": True,
        "previous_version_id": None,
        "knowledge_document_id": None,
        "knowledge_version_id": None,
        "visibility": KnowledgeVisibility.INTERNAL_ONLY,
        "approved_by": None,
        "approved_at": None,
        "publication_status": GovernanceCharterPublicationStatus.NOT_PUBLISHED,
        "published_at": None,
        "published_by": None,
        "publication_error": None,
        "publication_attempt_count": 0,
        "last_publication_attempt_at": None,
        "created_at": datetime(2026, 7, 15, tzinfo=UTC),
        "updated_at": datetime(2026, 7, 15, tzinfo=UTC),
    }
    base.update(overrides)
    return SimpleNamespace(**base)


def _evidence_link(charter_id, source_id, org_id):
    return SimpleNamespace(
        id=uuid4(),
        org_id=org_id,
        summary_id=None,
        charter_id=charter_id,
        source_type=GovernanceEvidenceSourceType.DEPENDENCY,
        source_id=source_id,
        created_at=datetime(2026, 7, 15, tzinfo=UTC),
    )


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
    assert "## Evidence Appendix" not in text
    assert ref in text
    assert "- Version: v2" in text


def test_sanitize_charter_text_removes_evidence_appendix_data() -> None:
    text = "\n".join(
        [
            "## Executive Summary",
            "Grounded summary [scope_state:11111111-1111-1111-1111-111111111111].",
            "",
            "## Approval Section",
            "- Version: v1",
            "",
            "## Evidence Appendix",
            "- [weekly_summary:22222222-2222-2222-2222-222222222222] noisy detail",
        ]
    )

    sanitized = sanitize_charter_text(text)

    assert "## Approval Section" in sanitized
    assert "Evidence Appendix" not in sanitized
    assert "weekly_summary:" not in sanitized


async def _fake_load_user_names(_session, user_ids):
    return {user_id: f"User {index}" for index, user_id in enumerate(user_ids)}


async def _fake_load_project_names(_session, project_ids):
    return {project_id: "Phoenix" for project_id in project_ids}


async def _fake_visible_project(_session, project_id, _current_user):
    return SimpleNamespace(id=project_id, name="Phoenix")


@pytest.mark.asyncio
async def test_batch_project_charter_read_preserves_order_and_evidence(monkeypatch) -> None:
    from app.agents.governance.services import charter_service as svc

    org_id = uuid4()
    project_id = uuid4()
    dependency_id = uuid4()
    first = _charter(org_id=org_id, project_id=project_id, version="v2")
    second = _charter(org_id=org_id, project_id=project_id, version="v1")
    link = _evidence_link(first.id, dependency_id, org_id)
    dependency = SimpleNamespace(
        id=dependency_id,
        title="Data dependency",
        status=GovernanceDependencyStatus.BLOCKING,
        due_date=None,
        project_id=project_id,
    )
    session = QueueSession([[link], [dependency]])
    monkeypatch.setattr(svc, "load_user_names", _fake_load_user_names)
    monkeypatch.setattr(svc, "load_project_names", _fake_load_project_names)

    reads = await build_project_charters_read(session, [first, second])

    assert [read.id for read in reads] == [first.id, second.id]
    assert reads[0].generated_text.endswith("Test charter")
    assert reads[0].evidence_links[0].label == "Data dependency"
    assert reads[1].evidence_links == []
    assert session.execute_count == 2


@pytest.mark.asyncio
async def test_lightweight_project_charter_list_skips_evidence_enrichment(monkeypatch) -> None:
    from app.agents.governance.services import charter_service as svc

    invalidate_project_charter_list_cache()
    org_id = uuid4()
    project_id = uuid4()
    user = _user(org_id=org_id)
    charter = _charter(org_id=org_id, project_id=project_id)
    session = QueueSession([[charter]])
    monkeypatch.setattr(svc, "load_user_names", _fake_load_user_names)
    monkeypatch.setattr(svc, "load_project_names", _fake_load_project_names)

    page = await list_project_charters_page(session, user, limit=5, include_detail=False)

    assert page.cache_hit is False
    assert page.db_executes == 2
    assert page.items[0].generated_text == ""
    assert page.items[0].evidence_links == []
    assert session.execute_count == 1


@pytest.mark.asyncio
async def test_lightweight_project_charter_list_records_timing_fields(monkeypatch) -> None:
    from app.agents.governance.services import charter_service as svc
    from app.agents.governance.timing import (
        GovernanceEndpointTimer,
        _reset_governance_timer,
        _set_governance_timer,
    )

    invalidate_project_charter_list_cache()
    org_id = uuid4()
    project_id = uuid4()
    user = _user(org_id=org_id)
    charter = _charter(org_id=org_id, project_id=project_id)
    monkeypatch.setattr(svc, "load_user_names", _fake_load_user_names)
    monkeypatch.setattr(svc, "load_project_names", _fake_load_project_names)

    timer = GovernanceEndpointTimer("GET /governance/project-charters", user)
    token = _set_governance_timer(timer)
    try:
        page = await list_project_charters_page(
            QueueSession([[charter]]),
            user,
            limit=5,
            include_detail=False,
        )
    finally:
        _reset_governance_timer(token)

    assert page.db_executes == 2
    assert timer.execute_count == 2
    assert timer.cache_hit is False
    assert timer.returned_row_count == 1
    assert timer.list_row_fetch_ms is not None
    assert timer.enrichment_ms is not None


@pytest.mark.asyncio
async def test_lightweight_project_charter_list_preserves_project_authorization(monkeypatch) -> None:
    from app.agents.governance.services import charter_service as svc

    invalidate_project_charter_list_cache()
    org_id = uuid4()
    project_id = uuid4()
    user = _user(org_id=org_id)
    charter = _charter(org_id=org_id, project_id=project_id)
    visible_calls = []

    async def _visible(_session, requested_project_id, _current_user):
        visible_calls.append(requested_project_id)
        return SimpleNamespace(id=requested_project_id, name="Phoenix")

    monkeypatch.setattr(svc, "get_visible_project", _visible)
    monkeypatch.setattr(svc, "load_user_names", _fake_load_user_names)
    monkeypatch.setattr(svc, "load_project_names", _fake_load_project_names)

    page = await list_project_charters_page(
        QueueSession([[charter]]),
        user,
        project_id=project_id,
        limit=5,
        include_detail=False,
    )

    assert visible_calls == [project_id]
    assert page.db_executes == 2
    assert page.items[0].project_name == "Phoenix"


@pytest.mark.asyncio
async def test_selected_project_charter_detail_enriches_evidence_once(monkeypatch) -> None:
    from app.agents.governance.services import charter_service as svc

    org_id = uuid4()
    project_id = uuid4()
    dependency_id = uuid4()
    charter = _charter(org_id=org_id, project_id=project_id)
    link = _evidence_link(charter.id, dependency_id, org_id)
    dependency = SimpleNamespace(
        id=dependency_id,
        title="Data dependency",
        status=GovernanceDependencyStatus.BLOCKING,
        due_date=None,
        project_id=project_id,
    )
    session = QueueSession([[link], [dependency]])
    monkeypatch.setattr(svc, "load_user_names", _fake_load_user_names)
    monkeypatch.setattr(svc, "load_project_names", _fake_load_project_names)

    read, executes = await build_project_charter_read_with_metrics(session, charter)

    assert read.generated_text.endswith("Test charter")
    assert read.evidence_links[0].label == "Data dependency"
    assert executes == 4
    assert session.execute_count == 2


@pytest.mark.asyncio
async def test_project_charters_panel_returns_list_metadata_and_selected_text(monkeypatch) -> None:
    from app.agents.governance.services import charter_service as svc

    invalidate_project_charter_list_cache()
    org_id = uuid4()
    project_id = uuid4()
    dependency_id = uuid4()
    user = _user(org_id=org_id)
    charter = _charter(org_id=org_id, project_id=project_id)
    link = _evidence_link(charter.id, dependency_id, org_id)
    dependency = SimpleNamespace(
        id=dependency_id,
        title="Data dependency",
        status=GovernanceDependencyStatus.BLOCKING,
        due_date=None,
        project_id=project_id,
    )
    session = QueueSession([[charter], [charter], [link], [dependency]])
    monkeypatch.setattr(svc, "load_user_names", _fake_load_user_names)
    monkeypatch.setattr(svc, "load_project_names", _fake_load_project_names)

    panel = await get_project_charters_panel_data(session, user, limit=5)

    assert panel.cache_hit is False
    assert panel.charters[0].generated_text == ""
    assert panel.selected_charter.generated_text.endswith("Test charter")
    assert panel.selected_charter.evidence_links[0].label == "Data dependency"
    assert panel.db_executes <= 8
    assert session.execute_count == 4


@pytest.mark.asyncio
async def test_project_charter_first_page_cache_hit_and_invalidation(monkeypatch) -> None:
    from app.agents.governance.services import charter_service as svc

    invalidate_project_charter_list_cache()
    org_id = uuid4()
    project_id = uuid4()
    user = _user(org_id=org_id)
    charter = _charter(org_id=org_id, project_id=project_id)
    session = QueueSession([[charter], []])
    monkeypatch.setattr(svc, "load_user_names", _fake_load_user_names)
    monkeypatch.setattr(svc, "load_project_names", _fake_load_project_names)

    first = await list_project_charters_page(session, user, limit=5)
    second = await list_project_charters_page(QueueSession([]), user, limit=5)

    assert first.cache_hit is False
    assert first.db_executes == 3
    assert second.cache_hit is True
    assert second.db_executes == 0
    assert second.items[0].id == charter.id

    removed = invalidate_project_charter_list_cache(org_id=org_id, project_id=project_id)
    assert removed == 1
    miss_after_invalidation = await list_project_charters_page(
        QueueSession([[charter], []]), user, limit=5
    )
    assert miss_after_invalidation.cache_hit is False


@pytest.mark.asyncio
async def test_project_charter_cache_scopes_by_org_user_and_project(monkeypatch) -> None:
    from app.agents.governance.services import charter_service as svc

    invalidate_project_charter_list_cache()
    org_a = uuid4()
    org_b = uuid4()
    project_a = uuid4()
    user_a = _user(org_id=org_a)
    user_b = _user(org_id=org_b)
    charter_a = _charter(org_id=org_a, project_id=project_a)
    charter_b = _charter(org_id=org_b)
    monkeypatch.setattr(svc, "load_user_names", _fake_load_user_names)
    monkeypatch.setattr(svc, "load_project_names", _fake_load_project_names)
    monkeypatch.setattr(svc, "get_visible_project", _fake_visible_project)

    await list_project_charters_page(
        QueueSession([[charter_a], []]), user_a, project_id=project_a, limit=5
    )
    await list_project_charters_page(QueueSession([[charter_b], []]), user_b, limit=5)

    removed = invalidate_project_charter_list_cache(org_id=org_a, project_id=project_a)
    assert removed == 1
    assert (await list_project_charters_page(QueueSession([]), user_b, limit=5)).cache_hit is True
