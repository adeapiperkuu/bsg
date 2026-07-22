"""Append-only KPI and agent-score observation writers."""

from __future__ import annotations

import hashlib
import json
import logging
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import AgentScoreObservation, KpiDefinition, KpiDefinitionVersion, KpiObservation
from app.schemas.kpi import KpiEvaluationRead

logger = logging.getLogger(__name__)


def _json_default(value: Any) -> Any:
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, UUID):
        return str(value)
    if isinstance(value, datetime):
        return value.isoformat()
    raise TypeError(f"Object of type {type(value)!r} is not JSON serializable")


def canonicalize_for_fingerprint(payload: dict[str, Any]) -> str:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), default=_json_default)


def fingerprint_payload(payload: dict[str, Any]) -> str:
    canonical = canonicalize_for_fingerprint(payload)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def extract_calculator_version(calculator_key: str | None) -> str | None:
    if not calculator_key:
        return None
    parts = calculator_key.rsplit(".", 1)
    if len(parts) == 2 and parts[1].startswith("v"):
        return parts[1]
    return "v1"


@dataclass(frozen=True, slots=True)
class PersistResult:
    observation: KpiObservation | AgentScoreObservation
    created: bool
    duplicate_skipped: bool = False


async def _resolve_definition_ids(
    session: AsyncSession,
    *,
    kpi_key: str,
    definition_version: str,
) -> tuple[UUID | None, UUID | None]:
    definition = (
        await session.execute(
            select(KpiDefinition).where(
                KpiDefinition.kpi_key == kpi_key,
                KpiDefinition.deleted_at.is_(None),
            )
        )
    ).scalar_one_or_none()
    if definition is None:
        return None, None
    version_row = (
        await session.execute(
            select(KpiDefinitionVersion).where(
                KpiDefinitionVersion.kpi_definition_id == definition.id,
                KpiDefinitionVersion.version == definition_version,
            )
        )
    ).scalar_one_or_none()
    return definition.id, None if version_row is None else version_row.id


async def persist_kpi_observation(
    session: AsyncSession,
    evaluation: KpiEvaluationRead,
    *,
    source_type: str = "evaluation",
    department_key: str | None = None,
    agent_key: str | None = None,
    client_user_id: UUID | None = None,
    bucket_start: datetime | None = None,
    bucket_end: datetime | None = None,
    bucket_interval: str | None = None,
    evidence_refs: list[Any] | None = None,
    lineage_refs: dict[str, Any] | None = None,
    reproducibility_metadata: dict[str, Any] | None = None,
    confidence: Decimal | None = None,
    value_type: str = "numeric",
    supersedes_observation_id: UUID | None = None,
    job_id: UUID | None = None,
    legal_hold: bool = False,
    audit_hold: bool = False,
    report_hold: bool = False,
) -> PersistResult:
    """Insert an immutable KPI observation. Duplicates are skipped by fingerprint."""
    if evaluation.org_id is None:
        raise ValueError("org_id is required to persist a KPI observation")

    definition_version = evaluation.version
    calculator_version = extract_calculator_version(evaluation.calculator_key)
    fingerprint = fingerprint_payload(
        {
            "kpi_key": evaluation.kpi_key,
            "definition_version": definition_version,
            "calculator_key": evaluation.calculator_key,
            "calculator_version": calculator_version,
            "org_id": evaluation.org_id,
            "project_id": evaluation.project_id,
            "department_key": department_key,
            "agent_key": agent_key,
            "client_user_id": client_user_id,
            "bucket_interval": bucket_interval,
            "bucket_start": bucket_start,
            "numeric_value": evaluation.numeric_value,
            "text_value": evaluation.text_value,
            "status": evaluation.status,
            "source_type": source_type,
            "supersedes_observation_id": supersedes_observation_id,
        }
    )

    existing = (
        await session.execute(
            select(KpiObservation).where(KpiObservation.idempotency_fingerprint == fingerprint)
        )
    ).scalar_one_or_none()
    if existing is not None:
        logger.info(
            "event=kpi_observation_duplicate_skipped kpi_key=%s fingerprint=%s",
            evaluation.kpi_key,
            fingerprint[:12],
        )
        return PersistResult(observation=existing, created=False, duplicate_skipped=True)

    definition_id, version_id = await _resolve_definition_ids(
        session,
        kpi_key=evaluation.kpi_key,
        definition_version=definition_version,
    )
    observed_at = evaluation.as_of or evaluation.evaluated_at
    row = KpiObservation(
        org_id=evaluation.org_id,
        project_id=evaluation.project_id,
        kpi_key=evaluation.kpi_key,
        version=definition_version,
        kpi_definition_id=definition_id,
        definition_version_id=version_id,
        definition_version=definition_version,
        calculator_key=evaluation.calculator_key,
        calculator_version=calculator_version,
        observed_at=observed_at,
        evaluated_at=evaluation.evaluated_at,
        numeric_value=evaluation.numeric_value,
        text_value=evaluation.text_value,
        normalized_value=evaluation.numeric_value,
        confidence=confidence,
        value_type=value_type if evaluation.numeric_value is not None else "categorical",
        status=evaluation.status,
        client_user_id=client_user_id,
        department_key=department_key,
        agent_key=agent_key or evaluation.kpi_key.split(".", 1)[0],
        bucket_start=bucket_start,
        bucket_end=bucket_end,
        bucket_interval=bucket_interval,
        source_type=source_type,
        evidence_refs=evidence_refs or [],
        lineage_refs=lineage_refs or {},
        reproducibility_metadata=reproducibility_metadata
        or {
            "thresholds": evaluation.thresholds,
            "dependencies": [dep.model_dump() for dep in evaluation.dependencies],
        },
        provenance=dict(evaluation.provenance),
        explainability=dict(evaluation.explainability or {}),
        idempotency_fingerprint=fingerprint,
        supersedes_observation_id=supersedes_observation_id,
        job_id=job_id,
        legal_hold=legal_hold,
        audit_hold=audit_hold,
        report_hold=report_hold,
    )
    session.add(row)
    await session.flush()
    logger.info(
        "event=kpi_observation_persisted kpi_key=%s org_id=%s source_type=%s status=%s",
        evaluation.kpi_key,
        evaluation.org_id,
        source_type,
        evaluation.status,
    )
    return PersistResult(observation=row, created=True)


async def publish_agent_score(
    session: AsyncSession,
    *,
    org_id: UUID,
    score_key: str,
    agent_key: str,
    score_version: str = "1.0.0",
    project_id: UUID | None = None,
    department_key: str | None = None,
    client_user_id: UUID | None = None,
    numeric_value: Decimal | None = None,
    text_value: str | None = None,
    confidence: Decimal | None = None,
    status: str = "ok",
    source_type: str = "agent_event",
    evidence_refs: list[Any] | None = None,
    lineage_refs: dict[str, Any] | None = None,
    provenance: dict[str, Any] | None = None,
    explainability: dict[str, Any] | None = None,
    reproducibility_metadata: dict[str, Any] | None = None,
    supersedes_observation_id: UUID | None = None,
    observed_at: datetime | None = None,
) -> PersistResult:
    """Persist a versioned non-KPI agent score observation."""
    now = datetime.now(UTC)
    observed = observed_at or now
    fingerprint = fingerprint_payload(
        {
            "score_key": score_key,
            "score_version": score_version,
            "agent_key": agent_key,
            "org_id": org_id,
            "project_id": project_id,
            "department_key": department_key,
            "numeric_value": numeric_value,
            "text_value": text_value,
            "status": status,
            "source_type": source_type,
            "observed_at_bucket": observed.replace(microsecond=0).isoformat(),
            "supersedes_observation_id": supersedes_observation_id,
        }
    )
    existing = (
        await session.execute(
            select(AgentScoreObservation).where(
                AgentScoreObservation.idempotency_fingerprint == fingerprint
            )
        )
    ).scalar_one_or_none()
    if existing is not None:
        return PersistResult(observation=existing, created=False, duplicate_skipped=True)

    row = AgentScoreObservation(
        org_id=org_id,
        project_id=project_id,
        score_key=score_key,
        score_version=score_version,
        agent_key=agent_key,
        department_key=department_key,
        client_user_id=client_user_id,
        observed_at=observed,
        evaluated_at=now,
        numeric_value=numeric_value,
        text_value=text_value,
        normalized_value=numeric_value,
        confidence=confidence,
        status=status,
        source_type=source_type,
        evidence_refs=evidence_refs or [],
        lineage_refs=lineage_refs or {},
        reproducibility_metadata=reproducibility_metadata or {},
        provenance=provenance or {},
        explainability=explainability or {},
        idempotency_fingerprint=fingerprint,
        supersedes_observation_id=supersedes_observation_id,
    )
    session.add(row)
    await session.flush()
    logger.info(
        "event=agent_score_observation_persisted score_key=%s agent_key=%s org_id=%s",
        score_key,
        agent_key,
        org_id,
    )
    return PersistResult(observation=row, created=True)


async def append_correction_observation(
    session: AsyncSession,
    *,
    original: KpiObservation,
    evaluation: KpiEvaluationRead,
    reason: str,
) -> PersistResult:
    """Append a superseding correction observation without mutating the original row."""
    return await persist_kpi_observation(
        session,
        evaluation,
        source_type="correction",
        department_key=original.department_key,
        agent_key=original.agent_key,
        client_user_id=original.client_user_id,
        bucket_start=original.bucket_start,
        bucket_end=original.bucket_end,
        bucket_interval=original.bucket_interval,
        evidence_refs=list(original.evidence_refs or []),
        lineage_refs={
            **dict(original.lineage_refs or {}),
            "correction_of": str(original.id),
            "correction_reason": reason,
        },
        reproducibility_metadata={
            "correction_of": str(original.id),
            "reason": reason,
        },
        supersedes_observation_id=original.id,
        legal_hold=original.legal_hold,
        audit_hold=True,
        report_hold=original.report_hold,
    )
