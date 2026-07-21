"""Internal API contracts for Phase 15.2 operational data sources."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.db.models import OperationalDataSourceType


class _ORMModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class TimesheetEntryCreate(BaseModel):
    team_id: UUID
    snapshot_date: date
    hours_logged: Decimal = Field(ge=0, le=Decimal("10000"))
    expected_hours: Decimal | None = Field(default=None, ge=0, le=Decimal("10000"))
    source_type: OperationalDataSourceType = OperationalDataSourceType.MANUAL
    source_reference: str | None = Field(default=None, max_length=500)
    notes: str | None = Field(default=None, max_length=2000)


class TimesheetEntryResponse(_ORMModel):
    id: UUID
    project_id: UUID
    team_id: UUID
    snapshot_date: date
    hours_logged: Decimal
    expected_hours: Decimal | None
    source_type: OperationalDataSourceType
    source_reference: str | None
    notes: str | None
    created_at: datetime
    updated_at: datetime
    created: bool = False
    corrected: bool = False


class AbsenteeismSnapshotCreate(BaseModel):
    snapshot_date: date
    absent_fte: Decimal = Field(ge=0, le=Decimal("10000"))
    planned_fte: Decimal = Field(gt=0, le=Decimal("10000"))
    source_type: OperationalDataSourceType = OperationalDataSourceType.MANUAL
    source_reference: str | None = Field(default=None, max_length=500)
    notes: str | None = Field(default=None, max_length=2000)

    @model_validator(mode="after")
    def validate_absent_vs_planned(self) -> AbsenteeismSnapshotCreate:
        if self.absent_fte > self.planned_fte:
            raise ValueError("absent_fte cannot exceed planned_fte")
        return self


class AbsenteeismSnapshotResponse(_ORMModel):
    id: UUID
    project_id: UUID
    snapshot_date: date
    absent_fte: Decimal
    planned_fte: Decimal
    absence_rate_pct: Decimal
    source_type: OperationalDataSourceType
    source_reference: str | None
    notes: str | None
    created_at: datetime
    updated_at: datetime
    created: bool = False
    corrected: bool = False


class ReviewQueueSnapshotCreate(BaseModel):
    snapshot_date: date
    pending_count: int = Field(ge=0, le=1_000_000)
    avg_turnaround_hours: Decimal = Field(ge=0, le=Decimal("10000"))
    sla_breach_count: int = Field(default=0, ge=0, le=1_000_000)
    source_type: OperationalDataSourceType = OperationalDataSourceType.MANUAL
    source_reference: str | None = Field(default=None, max_length=500)
    notes: str | None = Field(default=None, max_length=2000)

    @model_validator(mode="after")
    def validate_sla_vs_pending(self) -> ReviewQueueSnapshotCreate:
        if self.sla_breach_count > self.pending_count:
            raise ValueError("sla_breach_count cannot exceed pending_count")
        return self


class ReviewQueueSnapshotResponse(_ORMModel):
    id: UUID
    project_id: UUID
    snapshot_date: date
    pending_count: int
    avg_turnaround_hours: Decimal
    sla_breach_count: int
    source_type: OperationalDataSourceType
    source_reference: str | None
    notes: str | None
    created_at: datetime
    updated_at: datetime
    created: bool = False
    corrected: bool = False


class BacklogQueueSnapshotCreate(BaseModel):
    snapshot_date: date
    item_count: int = Field(ge=0, le=1_000_000)
    aging_item_count: int = Field(default=0, ge=0, le=1_000_000)
    oldest_item_age_days: int = Field(default=0, ge=0, le=10_000)
    source_type: OperationalDataSourceType = OperationalDataSourceType.MANUAL
    source_reference: str | None = Field(default=None, max_length=500)
    notes: str | None = Field(default=None, max_length=2000)

    @model_validator(mode="after")
    def validate_aging(self) -> BacklogQueueSnapshotCreate:
        if self.aging_item_count > self.item_count:
            raise ValueError("aging_item_count cannot exceed item_count")
        return self


class BacklogQueueSnapshotResponse(_ORMModel):
    id: UUID
    project_id: UUID
    snapshot_date: date
    item_count: int
    aging_item_count: int
    oldest_item_age_days: int
    source_type: OperationalDataSourceType
    source_reference: str | None
    notes: str | None
    created_at: datetime
    updated_at: datetime
    created: bool = False
    corrected: bool = False


class CapacitySnapshotCreate(BaseModel):
    snapshot_date: date
    planned_capacity_hours: Decimal = Field(gt=0, le=Decimal("1000000"))
    available_capacity_hours: Decimal = Field(ge=0, le=Decimal("1000000"))
    source_type: OperationalDataSourceType = OperationalDataSourceType.MANUAL
    source_reference: str | None = Field(default=None, max_length=500)
    notes: str | None = Field(default=None, max_length=2000)


class CapacitySnapshotResponse(_ORMModel):
    id: UUID
    project_id: UUID
    snapshot_date: date
    planned_capacity_hours: Decimal
    available_capacity_hours: Decimal
    source_type: OperationalDataSourceType
    source_reference: str | None
    notes: str | None
    created_at: datetime
    updated_at: datetime
    created: bool = False
    corrected: bool = False


class TeamAvailabilitySnapshotCreate(BaseModel):
    team_id: UUID
    snapshot_date: date
    available_headcount: int = Field(ge=0, le=1_000_000)
    planned_headcount: int = Field(gt=0, le=1_000_000)
    available_fte: Decimal | None = Field(default=None, ge=0, le=Decimal("10000"))
    source_type: OperationalDataSourceType = OperationalDataSourceType.MANUAL
    source_reference: str | None = Field(default=None, max_length=500)
    notes: str | None = Field(default=None, max_length=2000)

    @model_validator(mode="after")
    def validate_available_vs_planned(self) -> TeamAvailabilitySnapshotCreate:
        if self.available_headcount > self.planned_headcount:
            raise ValueError("available_headcount cannot exceed planned_headcount")
        return self


class TeamAvailabilitySnapshotResponse(_ORMModel):
    id: UUID
    project_id: UUID
    team_id: UUID
    snapshot_date: date
    available_headcount: int
    planned_headcount: int
    available_fte: Decimal | None
    source_type: OperationalDataSourceType
    source_reference: str | None
    notes: str | None
    created_at: datetime
    updated_at: datetime
    created: bool = False
    corrected: bool = False
