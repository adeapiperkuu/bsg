"""Shared data lineage metadata for AI-generated recommendations.

Every recommendation can be traced:

    Recommendation → Evidence → Database Records → Calculations → Source Data

This schema is intentionally domain-agnostic so Workforce, Delivery, Governance,
and future agents can attach the same lineage contract without further
architectural changes.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, Field


class RecommendationSourceEntity(BaseModel):
    """A database row that contributed to the recommendation."""

    source_table: str
    source_row_id: UUID | None = None
    label: str | None = None
    attributes: dict[str, Any] = Field(default_factory=dict)


class RecommendationCalculation(BaseModel):
    """A named calculation step used to produce scores or findings."""

    name: str
    description: str
    inputs: dict[str, Any] = Field(default_factory=dict)
    result: Any = None
    formula: str | None = None


class RecommendationEvidenceItem(BaseModel):
    """One piece of supporting evidence for a recommendation."""

    evidence_id: str
    summary: str
    source_entities: list[RecommendationSourceEntity] = Field(default_factory=list)
    metric_keys: list[str] = Field(default_factory=list)
    document_ids: list[UUID] = Field(default_factory=list)
    observed_at: datetime | None = None
    visibility: Literal["internal", "client_safe"] = "internal"
    attributes: dict[str, Any] = Field(default_factory=dict)


class RecommendationLineage(BaseModel):
    """Full lineage metadata attached to a recommendation."""

    recommendation_id: str
    recommendation_type: str
    generated_at: datetime
    confidence_score: float = Field(ge=0.0, le=1.0)
    evidence: list[RecommendationEvidenceItem] = Field(default_factory=list)
    source_entities: list[RecommendationSourceEntity] = Field(default_factory=list)
    calculations: list[RecommendationCalculation] = Field(default_factory=list)
    metrics_involved: list[str] = Field(default_factory=list)
    documents_referenced: list[UUID] = Field(default_factory=list)
    related_entity_ids: dict[str, list[UUID]] = Field(default_factory=dict)
    model_version: str = "workforce_optimization_v1"
    notes: str | None = None


def build_lineage(
    *,
    recommendation_id: str,
    recommendation_type: str,
    generated_at: datetime,
    confidence_score: float,
    evidence: list[RecommendationEvidenceItem] | None = None,
    source_entities: list[RecommendationSourceEntity] | None = None,
    calculations: list[RecommendationCalculation] | None = None,
    metrics_involved: list[str] | None = None,
    documents_referenced: list[UUID] | None = None,
    related_entity_ids: dict[str, list[UUID]] | None = None,
    model_version: str = "workforce_optimization_v1",
    notes: str | None = None,
) -> RecommendationLineage:
    """Construct a lineage object with de-duplicated metric/document lists."""
    evidence = evidence or []
    source_entities = source_entities or []
    calculations = calculations or []

    metric_keys = list(metrics_involved or [])
    for item in evidence:
        for key in item.metric_keys:
            if key not in metric_keys:
                metric_keys.append(key)

    doc_ids = list(documents_referenced or [])
    for item in evidence:
        for doc_id in item.document_ids:
            if doc_id not in doc_ids:
                doc_ids.append(doc_id)

    # Prefer explicit source entities; fall back to evidence-linked ones.
    entities = list(source_entities)
    if not entities:
        seen: set[tuple[str, str | None]] = set()
        for item in evidence:
            for entity in item.source_entities:
                key = (entity.source_table, str(entity.source_row_id) if entity.source_row_id else None)
                if key in seen:
                    continue
                seen.add(key)
                entities.append(entity)

    return RecommendationLineage(
        recommendation_id=recommendation_id,
        recommendation_type=recommendation_type,
        generated_at=generated_at,
        confidence_score=max(0.0, min(1.0, confidence_score)),
        evidence=evidence,
        source_entities=entities,
        calculations=calculations,
        metrics_involved=metric_keys,
        documents_referenced=doc_ids,
        related_entity_ids=related_entity_ids or {},
        model_version=model_version,
        notes=notes,
    )
