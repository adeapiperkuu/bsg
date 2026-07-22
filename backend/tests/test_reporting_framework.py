"""Phase 18.3 Cross-Agent Reporting Framework unit tests."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

import pytest

from app.core.security import CurrentUser
from app.db.models import AppRole, ReportInstance
from app.main import app
from app.reports.contracts import SECTION_KEYS, ReportBuildContext
from app.reports.exporters import render_report
from app.reports.permissions import can_approve_report, can_view_report
from app.reports.sections import SECTION_BUILDERS
from app.reports.workflows import approve_report, distribute_report


def _user(role: AppRole = AppRole.DELIVERY_MANAGER) -> CurrentUser:
    return CurrentUser(
        id=uuid4(),
        org_id=uuid4(),
        email="reports@test.local",
        role=role,
        is_active=True,
    )


def test_section_plugins_cover_contract_keys() -> None:
    assert SECTION_KEYS == frozenset(SECTION_BUILDERS)
    assert "ai_executive_summary" in SECTION_BUILDERS
    assert "kpi_summary" in SECTION_BUILDERS


def test_openapi_registers_report_routes() -> None:
    paths = app.openapi()["paths"]
    assert "/api/v1/reports/templates" in paths
    assert "/api/v1/reports/generate" in paths
    assert "/api/v1/reports/{report_id}/approve" in paths
    assert "/api/v1/reports/{report_id}/distribute" in paths
    assert "/api/v1/reports/{report_id}/exports/{format}" in paths
    assert "/api/v1/reports/schedules" in paths


def test_exporters_render_all_formats() -> None:
    report = ReportInstance(
        id=uuid4(),
        org_id=uuid4(),
        template_id=uuid4(),
        template_key="delivery.health_summary",
        template_version="1.0.0",
        audience="delivery_manager",
        domain="delivery",
        status="draft",
        title="Delivery Health",
        body_markdown="# Delivery Health\n\nAll good.",
        content_payload={
            "sections": [
                {
                    "key": "kpi_summary",
                    "title": "KPIs",
                    "payload": {"items": [{"kpi_key": "delivery.confidence", "numeric_value": "88"}]},
                    "markdown": "## KPIs\n\n88",
                    "limitations": [],
                    "has_ai": False,
                    "requires_approval": False,
                }
            ]
        },
        provenance={},
        limitations=[],
        has_ai_sections=False,
        generation_mode="structured",
    )
    for fmt in ("json", "csv", "pdf", "docx"):
        content, content_type, filename = render_report(report, fmt)
        assert isinstance(content, (bytes, bytearray))
        assert len(content) > 10
        assert content_type
        assert filename.endswith(f".{fmt}" if fmt != "docx" else ".docx")


def test_client_only_sees_distributed_client_reports() -> None:
    org = uuid4()
    client = CurrentUser(
        id=uuid4(), org_id=org, email="c@test.local", role=AppRole.CLIENT, is_active=True
    )
    report = ReportInstance(
        id=uuid4(),
        org_id=org,
        template_id=uuid4(),
        template_key="client.weekly_status",
        template_version="1.0.0",
        audience="client",
        domain="client",
        status="approved",
        title="Client",
        body_markdown="x",
        content_payload={},
        provenance={},
        limitations=[],
        has_ai_sections=True,
        generation_mode="hybrid",
    )
    assert can_view_report(report, client) is False
    report.status = "distributed"
    assert can_view_report(report, client) is True


@pytest.mark.asyncio
async def test_approve_does_not_distribute() -> None:
    org = uuid4()
    user = CurrentUser(
        id=uuid4(), org_id=org, email="dm@test.local", role=AppRole.DELIVERY_MANAGER, is_active=True
    )
    report = ReportInstance(
        id=uuid4(),
        org_id=org,
        template_id=uuid4(),
        template_key="client.weekly_status",
        template_version="1.0.0",
        audience="client",
        domain="client",
        status="in_review",
        title="Client",
        body_markdown="x",
        content_payload={},
        provenance={},
        limitations=[],
        has_ai_sections=True,
        generation_mode="hybrid",
    )

    class _Session:
        def add(self, _obj):
            return None

        async def flush(self):
            return None

    session = _Session()
    approved = await approve_report(session, report, user)  # type: ignore[arg-type]
    assert approved.status == "approved"
    assert approved.distributed_at is None
    assert can_approve_report(approved, user) is False
    distributed = await distribute_report(session, approved, user)  # type: ignore[arg-type]
    assert distributed.status == "distributed"
    assert distributed.distributed_at is not None


def test_build_context_defaults() -> None:
    ctx = ReportBuildContext(org_id=uuid4())
    assert ctx.generation_mode == "structured"
    assert ctx.section_results == []
    assert datetime.now(UTC)


def test_adapter_link_helpers() -> None:
    from types import SimpleNamespace

    from app.reports.adapters import (
        link_charter,
        link_communication_to_report,
        link_evaluation_report,
        link_weekly_summary,
    )

    report = ReportInstance(
        id=uuid4(),
        org_id=uuid4(),
        template_id=uuid4(),
        template_key="client.weekly_status",
        template_version="1.0.0",
        audience="client",
        domain="client",
        status="draft",
        title="t",
        body_markdown="b",
        content_payload={},
        provenance={},
        limitations=[],
        has_ai_sections=False,
        generation_mode="legacy_adapter",
    )
    communication = SimpleNamespace(id=uuid4())
    link_communication_to_report(report, communication)  # type: ignore[arg-type]
    assert report.source_communication_id == communication.id
    assert report.source_table == "client_communications"

    summary = SimpleNamespace(id=uuid4())
    link_weekly_summary(report, summary)  # type: ignore[arg-type]
    assert report.source_weekly_summary_id == summary.id

    charter = SimpleNamespace(id=uuid4())
    link_charter(report, charter)  # type: ignore[arg-type]
    assert report.source_charter_id == charter.id

    evaluation = SimpleNamespace(id=uuid4())
    link_evaluation_report(report, evaluation)  # type: ignore[arg-type]
    assert report.source_evaluation_report_id == evaluation.id


def test_scheduler_module_is_draft_oriented() -> None:
    from pathlib import Path

    from app.reports import jobs as report_jobs
    from app.reports import scheduler as report_scheduler

    assert hasattr(report_scheduler, "run_report_planner")
    jobs_source = Path(report_jobs.__file__).read_text(encoding="utf-8")
    assert "scheduled_generate" in jobs_source
    assert "Scheduled report generation must remain draft" in jobs_source
