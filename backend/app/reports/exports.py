"""Report export orchestration and idempotency."""

from __future__ import annotations

import hashlib
import logging

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.db.models import ReportExport, ReportInstance
from app.reports.exporters import SUPPORTED_FORMATS, render_report
from app.reports.storage import store_report_bytes

logger = logging.getLogger(__name__)


async def create_report_export(
    session: AsyncSession,
    report: ReportInstance,
    format_: str,
) -> ReportExport:
    """Render, store, and record an export without committing."""
    normalized = format_.lower()
    if normalized not in SUPPORTED_FORMATS:
        raise ValueError(f"Unsupported report export format '{format_}'.")
    content, content_type, filename = render_report(report, normalized)
    content_hash = hashlib.sha256(content).hexdigest()
    existing = (
        await session.execute(
            select(ReportExport).where(
                ReportExport.report_instance_id == report.id,
                ReportExport.format == normalized,
                ReportExport.content_hash == content_hash,
            )
        )
    ).scalar_one_or_none()
    if existing is not None:
        return existing
    if not get_settings().report_publish_enabled:
        raise RuntimeError("Report export publishing is disabled.")
    backend, storage_path = await store_report_bytes(
        org_id=report.org_id,
        report_id=report.id,
        format_=normalized,
        filename=filename,
        content=content,
        content_type=content_type,
    )
    row = ReportExport(
        org_id=report.org_id,
        report_instance_id=report.id,
        format=normalized,
        storage_backend=backend,
        storage_path=storage_path,
        file_name=filename,
        content_type=content_type,
        size_bytes=len(content),
        checksum_sha256=content_hash,
        content_hash=content_hash,
    )
    session.add(row)
    await session.flush()
    logger.info(
        "event=report_export_created report_id=%s export_id=%s format=%s size_bytes=%s",
        report.id,
        row.id,
        normalized,
        len(content),
    )
    return row
