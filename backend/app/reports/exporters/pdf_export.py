"""PDF exporter with an optional ReportLab implementation."""

from __future__ import annotations

import io

from app.db.models import ReportInstance
from app.reports.exporters.base import ExportArtifact, safe_stem


def render(report: ReportInstance) -> ExportArtifact:
    try:
        from reportlab.lib.pagesizes import letter
        from reportlab.lib.styles import getSampleStyleSheet
        from reportlab.lib.utils import simpleSplit
        from reportlab.pdfgen.canvas import Canvas

        buffer = io.BytesIO()
        canvas = Canvas(buffer, pagesize=letter)
        styles = getSampleStyleSheet()
        width, height = letter
        y = height - 54
        for line in [report.title, "", *((report.body_markdown or "").splitlines())]:
            style = styles["Heading1"] if line.startswith("# ") else styles["BodyText"]
            text = line.lstrip("# ").strip()
            wrapped = simpleSplit(text, style.fontName, style.fontSize, width - 108) or [""]
            for value in wrapped:
                if y < 54:
                    canvas.showPage()
                    y = height - 54
                canvas.setFont(style.fontName, style.fontSize)
                canvas.drawString(54, y, value)
                y -= max(style.leading, 14)
        canvas.save()
        content = buffer.getvalue()
    except ImportError:
        from app.services.pdf_export import generate_simple_pdf

        content = generate_simple_pdf(report.title, report.body_markdown or "")
    return content, "application/pdf", f"{safe_stem(report)}.pdf"
