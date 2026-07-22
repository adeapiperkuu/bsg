"""Report export adapter selection."""

from __future__ import annotations

from app.db.models import ReportInstance
from app.reports.exporters.base import ExportArtifact

SUPPORTED_FORMATS = frozenset({"json", "csv", "pdf", "docx"})


def render_report(report: ReportInstance, format_: str) -> ExportArtifact:
    normalized = format_.lower()
    if normalized == "json":
        from app.reports.exporters.json_export import render
    elif normalized == "csv":
        from app.reports.exporters.csv_export import render
    elif normalized == "pdf":
        from app.reports.exporters.pdf_export import render
    elif normalized == "docx":
        from app.reports.exporters.docx_export import render
    else:
        raise ValueError(f"Unsupported report export format '{format_}'.")
    return render(report)


__all__ = ["SUPPORTED_FORMATS", "render_report"]
