"""Cross-Agent Reporting Framework public API."""

from app.reports.contracts import (
    SECTION_KEYS,
    EvidenceReference,
    ReportBuildContext,
    ReportSectionResult,
)
from app.reports.engine import build_report
from app.reports.exports import create_report_export
from app.reports.jobs import enqueue_report_job, process_report_queue
from app.reports.registry import get_report_registry, load_templates, resolve_template
from app.reports.workflows import (
    approve_report,
    distribute_report,
    reject_report,
    submit_for_review,
)

__all__ = [
    "SECTION_KEYS",
    "EvidenceReference",
    "ReportBuildContext",
    "ReportSectionResult",
    "approve_report",
    "build_report",
    "create_report_export",
    "distribute_report",
    "enqueue_report_job",
    "get_report_registry",
    "load_templates",
    "process_report_queue",
    "reject_report",
    "resolve_template",
    "submit_for_review",
]
