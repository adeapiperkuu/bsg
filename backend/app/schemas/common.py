from datetime import date, datetime
from decimal import Decimal
from typing import Generic, TypeVar
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

T = TypeVar("T")


class Pagination(BaseModel):
    limit: int = 50
    next_cursor: str | None = None


class DataResponse(BaseModel, Generic[T]):
    data: T


class ListResponse(BaseModel, Generic[T]):
    data: list[T]
    pagination: Pagination


class ORMModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class EvidenceLinkRead(ORMModel):
    id: UUID | None = None
    source_table: str
    source_row_id: UUID
    description: str
    created_at: datetime | None = None


class DateRangeParams(BaseModel):
    date_from: date | None = None
    date_to: date | None = None


class DecimalBounds:
    percent = Field(ge=0, le=100)
    ratio = Field(ge=0, le=1)


def ensure_month_start(value: date) -> date:
    if value.day != 1:
        raise ValueError("Date must be the first day of the month.")
    return value
