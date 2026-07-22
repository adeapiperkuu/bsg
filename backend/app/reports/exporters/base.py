"""Exporter protocol and shared helpers."""

from __future__ import annotations

import re
from typing import Protocol

from app.db.models import ReportInstance

ExportArtifact = tuple[bytes, str, str]


class ReportExporter(Protocol):
    def __call__(self, report: ReportInstance) -> ExportArtifact: ...


def safe_stem(report: ReportInstance) -> str:
    value = re.sub(r"[^A-Za-z0-9._-]+", "_", report.title).strip("._")
    return (value or "report")[:120]
