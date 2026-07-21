"""Internal API contracts for team throughput and bottleneck operations."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.db.models import AlertStatus, RiskTier, TeamThroughputSourceType


class _ORMModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class TeamThroughputSnapshotCreate(BaseModel):
    team_id: UUID
    snapshot_date: date
    units_completed: int = Field(ge=0)
    active_headcount: int | None = Field(default=None, ge=0)
    source_type: TeamThroughputSourceType = TeamThroughputSourceType.MANUAL
    source_reference: str | None = Field(default=None, max_length=500)
    notes: str | None = Field(default=None, max_length=2000)


class TeamThroughputSnapshotUpdate(BaseModel):
    units_completed: int | None = Field(default=None, ge=0)
    active_headcount: int | None = Field(default=None, ge=0)
    source_reference: str | None = Field(default=None, max_length=500)
    notes: str | None = Field(default=None, max_length=2000)

    @model_validator(mode="after")
    def reject_null_units(self) -> TeamThroughputSnapshotUpdate:
        if "units_completed" in self.model_fields_set and self.units_completed is None:
            raise ValueError("units_completed cannot be null")
        return self


class TeamThroughputSnapshotResponse(_ORMModel):
    id: UUID
    project_id: UUID
    team_id: UUID
    snapshot_date: date
    units_completed: int
    active_headcount: int | None
    source_type: TeamThroughputSourceType
    source_reference: str | None
    notes: str | None
    created_at: datetime
    updated_at: datetime
    corrected: bool = False
    detection_changed: bool = False
    scoring_status: str | None = None
    scoring_error: str | None = None


class BottleneckEvidencePointResponse(BaseModel):
    snapshot_date: date
    current_share: Decimal
    historical_share: Decimal
    decline_pct: Decimal
    headcount_change_pct: Decimal | None


class BottleneckResponse(_ORMModel):
    id: UUID
    project_id: UUID
    team_id: UUID | None
    title: str
    detail: str
    status: AlertStatus
    severity: RiskTier
    source_type: str | None
    source_key: str | None
    detector_version: str | None
    evidence_json: dict[str, object] | None
    first_detected_at: datetime | None
    last_detected_at: datetime | None
    acknowledged_at: datetime | None
    acknowledged_by: UUID | None
    acknowledgement_note: str | None
    resolved_at: datetime | None
    resolved_by: UUID | None
    resolution_reason: str | None
    occurrence_count: int
    created_at: datetime
    updated_at: datetime


class BottleneckAcknowledgeRequest(BaseModel):
    note: str | None = Field(default=None, max_length=1000)


class BottleneckResolveRequest(BaseModel):
    reason: str = Field(min_length=3, max_length=1000)


class BottleneckDetectionRunResponse(BaseModel):
    project_id: UUID
    evaluated_teams: int
    valid_observation_days: int
    signals_detected: int
    created: int
    updated: int
    resolved: int
    reopened: int
    skipped_reasons: list[str]
    scoring_status: str | None = None
    scoring_error: str | None = None
