"""CSV report exporter."""

from __future__ import annotations

import csv
import io
import json

from app.db.models import ReportInstance
from app.reports.exporters.base import ExportArtifact, safe_stem


def render(report: ReportInstance) -> ExportArtifact:
    output = io.StringIO(newline="")
    writer = csv.DictWriter(
        output,
        fieldnames=[
            "report_id",
            "template_key",
            "section_key",
            "section_title",
            "payload_json",
            "limitations",
        ],
    )
    writer.writeheader()
    for section in (report.content_payload or {}).get("sections", []):
        writer.writerow(
            {
                "report_id": str(report.id),
                "template_key": report.template_key,
                "section_key": section.get("key", ""),
                "section_title": section.get("title", ""),
                "payload_json": json.dumps(
                    section.get("payload", {}), ensure_ascii=False, default=str
                ),
                "limitations": " | ".join(section.get("limitations", [])),
            }
        )
    return (
        output.getvalue().encode("utf-8-sig"),
        "text/csv; charset=utf-8",
        f"{safe_stem(report)}.csv",
    )
