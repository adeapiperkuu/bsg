"""JSON report exporter."""

from __future__ import annotations

import json

from app.db.models import ReportInstance
from app.reports.exporters.base import ExportArtifact, safe_stem


def render(report: ReportInstance) -> ExportArtifact:
    payload = {
        "id": str(report.id),
        "template_key": report.template_key,
        "template_version": report.template_version,
        "title": report.title,
        "audience": report.audience,
        "domain": report.domain,
        "status": report.status,
        "period_start": report.period_start.isoformat() if report.period_start else None,
        "period_end": report.period_end.isoformat() if report.period_end else None,
        "content": report.content_payload,
        "provenance": report.provenance,
        "limitations": report.limitations,
        "evidence_fingerprint": report.evidence_fingerprint,
    }
    content = json.dumps(payload, indent=2, ensure_ascii=False, default=str).encode("utf-8")
    return content, "application/json", f"{safe_stem(report)}.json"
