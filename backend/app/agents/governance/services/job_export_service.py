"""Background generation and protected storage for large Governance exports."""

from __future__ import annotations

import csv
import io
from pathlib import Path
from typing import Any
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.governance.services.analytics_service import get_governance_analytics
from app.core.config import get_settings
from app.core.exceptions import ApiError
from app.core.security import CurrentUser
from app.services.pdf_export import generate_simple_pdf


def _analytics_csv(data: Any) -> str:
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["section", "project", "metric", "value", "evidence"])
    if data.insights_kpis is not None:
        for metric in (
            "portfolio_governance_score",
            "recommendation_acceptance_rate_pct",
            "recommendation_dismissal_rate_pct",
            "escalations_created",
            "recommendations_created",
            "projects_at_risk",
        ):
            writer.writerow(["insights_kpis", "", metric, getattr(data.insights_kpis, metric), ""])
    for project in data.portfolio_risk_ranking:
        writer.writerow(
            [
                "portfolio_risk_ranking",
                project.project_name,
                "governance_health_score",
                project.score,
                "; ".join(item.label for item in project.evidence),
            ]
        )
    for section, values in (
        ("top_governance_risks", data.top_governance_risks),
        ("top_recurring_blockers", data.top_recurring_blockers),
        ("top_recurring_mitigation_failures", data.top_recurring_mitigation_failures),
        ("most_affected_departments", data.most_affected_departments),
    ):
        for item in values:
            writer.writerow(
                [
                    section,
                    item.project_name or "" if hasattr(item, "project_name") else "",
                    item.label,
                    item.count,
                    item.detail or "",
                ]
            )
    for cell in data.risk_heatmap:
        writer.writerow(
            [
                "risk_heatmap",
                cell.vertical,
                cell.risk_level,
                cell.project_count,
                f"avg_score={cell.avg_score}",
            ]
        )
    for recommendation in data.recommendations:
        writer.writerow(
            [
                "recommendation",
                recommendation.project_name or "",
                recommendation.title,
                recommendation.detail,
                "; ".join(item.label for item in recommendation.evidence),
            ]
        )
    return output.getvalue()


async def generate_governance_analytics_export(
    session: AsyncSession,
    current_user: CurrentUser,
    job_id: UUID,
    payload: dict[str, Any],
):
    from app.agents.governance.services.job_service import JobProduct

    export_format = str(payload.get("format", "csv")).lower()
    if export_format not in {"csv", "pdf"}:
        raise ApiError(
            422, "UNSUPPORTED_FORMAT", "Background analytics export supports CSV or PDF."
        )
    project_id = UUID(payload["project_id"]) if payload.get("project_id") else None
    data = await get_governance_analytics(
        session,
        current_user,
        days=int(payload.get("days", 30)),
        project_id=project_id,
        vertical=payload.get("vertical") or None,
    )
    # Release the analytics read transaction before CSV serialization and filesystem I/O.
    await session.commit()
    if export_format == "csv":
        content = _analytics_csv(data).encode("utf-8")
        content_type = "text/csv"
    else:
        ranking = "\n".join(
            f"- {project.project_name}: score={project.score}, risk={project.risk_level}"
            for project in data.portfolio_risk_ranking[:25]
        )
        risks = "\n".join(
            f"- {item.label}: count={item.count}" for item in data.top_governance_risks[:25]
        )
        body = (
            f"Generated: {data.generated_at.isoformat()}\n"
            f"Range: {data.date_range_days} days\n\n"
            f"Portfolio Risk Ranking\n{ranking}\n\nTop Governance Risks\n{risks}"
        )
        content = generate_simple_pdf("Governance Analytics", body)
        content_type = "application/pdf"
    storage_dir = Path(get_settings().governance_job_export_dir).resolve()
    storage_dir.mkdir(parents=True, exist_ok=True)
    path = storage_dir / f"{job_id}.{export_format}"
    path.write_bytes(content)
    return JobProduct(
        "governance_analytics_export",
        None,
        {
            "storage_path": str(path),
            "file_name": f"governance-analytics-{data.date_range_days}d.{export_format}",
            "content_type": content_type,
            "size_bytes": len(content),
            "download_url": f"/governance/jobs/{job_id}/download",
        },
    )


def resolve_export_path(result_data: dict[str, Any] | None) -> tuple[Path, str, str]:
    data = result_data or {}
    raw_path = data.get("storage_path")
    if not raw_path:
        raise ApiError(404, "EXPORT_NOT_FOUND", "The export file is not available.")
    root = Path(get_settings().governance_job_export_dir).resolve()
    path = Path(str(raw_path)).resolve()
    if root not in path.parents or not path.is_file():
        raise ApiError(404, "EXPORT_NOT_FOUND", "The export file is not available.")
    return (
        path,
        str(data.get("file_name") or path.name),
        str(data.get("content_type") or "application/octet-stream"),
    )
