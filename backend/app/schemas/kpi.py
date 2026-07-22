"""API schemas for the Phase 18.1 KPI Semantic Layer."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class KpiDependencyRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    depends_on_kpi_key: str
    depends_on_version: str | None = None
    dependency_type: str


class KpiVersionRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    version: str
    name: str
    description: str | None = None
    unit: str
    trend_direction: str
    refresh_frequency: str
    calculator_key: str
    formula_description: str | None = None
    source_fields: list[Any] = Field(default_factory=list)
    default_thresholds: dict[str, Any] = Field(default_factory=dict)
    explainability: dict[str, Any] = Field(default_factory=dict)
    allowed_roles: list[str] = Field(default_factory=list)
    is_client_visible: bool = False
    compatibility_status: str
    effective_from: datetime
    effective_to: datetime | None = None
    dependencies: list[KpiDependencyRead] = Field(default_factory=list)


class KpiDefinitionRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    kpi_key: str
    owner_agent: str
    scope: str
    is_active: bool
    current_version: KpiVersionRead | None = None
    versions: list[KpiVersionRead] = Field(default_factory=list)


class KpiCalculationMetadataRead(BaseModel):
    kpi_key: str
    version: str
    name: str
    calculator_key: str
    formula_description: str | None = None
    source_fields: list[Any] = Field(default_factory=list)
    thresholds: dict[str, Any] = Field(default_factory=dict)
    threshold_source: str = "default"
    explainability: dict[str, Any] = Field(default_factory=dict)
    dependencies: list[KpiDependencyRead] = Field(default_factory=list)
    compatibility_status: str
    unit: str
    trend_direction: str
    refresh_frequency: str


class KpiEvaluateRequest(BaseModel):
    project_id: UUID | None = None
    org_id: UUID | None = None
    as_of: datetime | None = None
    version: str | None = None
    inputs: dict[str, Any] | None = None
    include_explainability: bool = True
    persist_observation: bool = False


class KpiBatchEvaluateRequest(BaseModel):
    kpi_ids: list[str] = Field(min_length=1)
    project_id: UUID | None = None
    org_id: UUID | None = None
    as_of: datetime | None = None
    version: str | None = None
    inputs: dict[str, Any] | None = None
    include_explainability: bool = True
    persist_observation: bool = False


class KpiEvaluationRead(BaseModel):
    kpi_key: str
    version: str
    calculator_key: str
    org_id: UUID | None = None
    project_id: UUID | None = None
    evaluated_at: datetime
    as_of: datetime | None = None
    status: str
    numeric_value: Decimal | None = None
    text_value: str | None = None
    unit: str
    thresholds: dict[str, Any] = Field(default_factory=dict)
    provenance: dict[str, Any] = Field(default_factory=dict)
    explainability: dict[str, Any] | None = None
    dependencies: list[KpiDependencyRead] = Field(default_factory=list)
