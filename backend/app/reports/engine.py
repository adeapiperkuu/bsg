"""Report composition engine."""

from __future__ import annotations

import logging
from dataclasses import replace
from typing import Any, Mapping

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import CurrentUser
from app.db.models import (
    KpiObservation,
    ReportEvidenceRef,
    ReportInstance,
    ReportTemplate,
)
from app.reports.contracts import EvidenceReference, ReportBuildContext, ReportSectionResult
from app.reports.registry import get_report_registry
from app.time_series.observations import fingerprint_payload

logger = logging.getLogger(__name__)


def _evidence_identity(ref: EvidenceReference) -> tuple[str, str | None, str | None, str | None]:
    return (
        ref.source_table,
        str(ref.source_id) if ref.source_id else None,
        str(ref.observation_id) if ref.observation_id else None,
        ref.kpi_key,
    )


def _serialize_section(section: ReportSectionResult) -> dict[str, Any]:
    return {
        "key": section.key,
        "title": section.title,
        "payload": dict(section.payload),
        "markdown": section.markdown,
        "limitations": list(section.limitations),
        "has_ai": section.has_ai,
        "requires_approval": section.requires_approval,
        "provenance": dict(section.provenance),
    }


async def build_report(
    session: AsyncSession,
    current_user: CurrentUser,
    template: ReportTemplate,
    context: ReportBuildContext,
    *,
    section_options: Mapping[str, Mapping[str, Any]] | None = None,
) -> ReportInstance:
    """Compose and persist a draft report without committing the session."""
    registry = get_report_registry()
    registry.validate_section_config(list(template.section_config or []))
    build_context = replace(
        context,
        org_id=context.org_id,
        template_key=template.template_key,
        template_version=template.version,
        audience=template.audience,
    )
    overrides = section_options or {}
    for config in template.section_config or []:
        key = str(config["key"])
        builder = registry.get_section(key)
        if builder is None:
            raise ValueError(f"Report section plugin '{key}' is not registered.")
        options = {**dict(config.get("options") or {}), **dict(overrides.get(key) or {})}
        result = await builder(session, current_user, build_context, options)
        build_context.section_results.append(result)

    all_evidence: dict[
        tuple[str, str | None, str | None, str | None], EvidenceReference
    ] = {}
    limitations: list[str] = []
    for section in build_context.section_results:
        limitations.extend(section.limitations)
        for ref in section.evidence:
            all_evidence.setdefault(_evidence_identity(ref), ref)
    evidence_payload = [
        {
            "source_table": ref.source_table,
            "source_id": ref.source_id,
            "observation_id": ref.observation_id,
            "kpi_key": ref.kpi_key,
            "label": ref.label,
            "metadata": dict(ref.metadata),
        }
        for ref in all_evidence.values()
    ]
    evidence_fingerprint = fingerprint_payload({"evidence": evidence_payload})
    title = build_context.title or template.name
    body = "\n\n".join(
        [f"# {title}", *(section.markdown for section in build_context.section_results)]
    )
    sections_payload = [_serialize_section(section) for section in build_context.section_results]
    has_ai = any(section.has_ai for section in build_context.section_results)

    if build_context.idempotency_key:
        existing = (
            await session.execute(
                select(ReportInstance).where(
                    ReportInstance.idempotency_key == build_context.idempotency_key,
                    ReportInstance.status.in_(("queued", "generating", "draft", "in_review")),
                )
            )
        ).scalar_one_or_none()
        if existing is not None:
            return existing

    instance = ReportInstance(
        org_id=build_context.org_id,
        project_id=build_context.project_id,
        template_id=template.id,
        template_key=template.template_key,
        template_version=template.version,
        audience=template.audience,
        domain=template.domain,
        status="draft",
        title=title,
        body_markdown=body,
        content_payload={"sections": sections_payload},
        provenance={
            "template_id": str(template.id),
            "template_version": template.version,
            "evidence_count": len(all_evidence),
            "requires_approval": template.requires_approval
            or any(section.requires_approval for section in build_context.section_results),
        },
        limitations=limitations,
        evidence_fingerprint=evidence_fingerprint,
        period_start=build_context.period_start,
        period_end=build_context.period_end,
        has_ai_sections=has_ai,
        generation_mode=build_context.generation_mode,
        generated_by_user_id=(
            None if build_context.inputs.get("system_generated") else current_user.id
        ),
        generated_by_job_id=build_context.generated_by_job_id,
        source_table=build_context.source_table,
        source_id=build_context.source_id,
        idempotency_key=build_context.idempotency_key,
    )
    session.add(instance)
    await session.flush()

    observation_ids = []
    for ref in all_evidence.values():
        session.add(
            ReportEvidenceRef(
                org_id=instance.org_id,
                report_instance_id=instance.id,
                source_table=ref.source_table,
                source_id=ref.source_id,
                kpi_key=ref.kpi_key,
                observation_id=ref.observation_id,
                label=ref.label,
                metadata_=dict(ref.metadata),
            )
        )
        if ref.observation_id is not None:
            observation_ids.append(ref.observation_id)
    if observation_ids:
        await session.execute(
            update(KpiObservation)
            .where(KpiObservation.id.in_(set(observation_ids)))
            .values(report_hold=True)
        )
    await session.flush()
    logger.info(
        "event=report_generated report_id=%s template_key=%s sections=%s evidence=%s has_ai=%s",
        instance.id,
        template.template_key,
        len(build_context.section_results),
        len(all_evidence),
        has_ai,
    )
    return instance
