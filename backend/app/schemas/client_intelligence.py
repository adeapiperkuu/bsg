"""Read models for the internal Client Intelligence overview and summary APIs."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from enum import StrEnum
from uuid import UUID

from pydantic import Field, field_validator, model_validator

from app.agents.client_intelligence.contracts import (
    ClientIntelligenceModel,
    DataQualityIssue,
    DataQualityState,
    EvidenceVisibility,
    ProjectIdentityFacts,
    ReportingPeriod,
    VisibilityLimitation,
)
from app.agents.client_intelligence.delivery_confidence_contracts import (
    DeliveryConfidenceAssessment,
)
from app.agents.client_intelligence.delivery_trend_contracts import DeliveryTrendAssessment
from app.agents.client_intelligence.health_contracts import (
    ProjectHealthAssessment,
    ProjectHealthStatus,
)
from app.agents.client_intelligence.risk_transparency_contracts import (
    RiskTransparencyAssessment,
)
from app.schemas.common import EvidenceLinkRead


class ClientIntelligenceOverviewRead(ClientIntelligenceModel):
    """Stable internal overview assembled from one canonical evidence pack."""

    project: ProjectIdentityFacts
    reporting_period: ReportingPeriod
    as_of: date
    generated_at: datetime
    visibility_mode: EvidenceVisibility
    source_fingerprint: str
    overall_data_quality: DataQualityState
    data_quality: list[DataQualityIssue]
    source_limitations: list[str]
    visibility_limitations: list[VisibilityLimitation]
    project_health: ProjectHealthAssessment
    delivery_confidence: DeliveryConfidenceAssessment
    risk_transparency: RiskTransparencyAssessment
    delivery_trend: DeliveryTrendAssessment


class SummaryMetricAvailability(StrEnum):
    """Per-KPI availability for authorized-scope Client Intelligence summary cards."""

    AVAILABLE = "available"
    NO_DATA = "no_data"
    PARTIAL = "partial"
    UNAVAILABLE = "unavailable"


def _canonicalize_limitations(values: list[str]) -> list[str]:
    return sorted({item.strip() for item in values if item and item.strip()})


class DeliveryConfidenceSummaryMetric(ClientIntelligenceModel):
    availability: SummaryMetricAvailability
    average_score_pct: Decimal | None = None
    covered_project_count: int = Field(ge=0)
    eligible_project_count: int = Field(ge=0)
    limitations: list[str] = Field(default_factory=list)

    @field_validator("limitations")
    @classmethod
    def _validate_limitations(cls, value: list[str]) -> list[str]:
        return _canonicalize_limitations(value)

    @model_validator(mode="after")
    def _confidence_invariants(self) -> DeliveryConfidenceSummaryMetric:
        if self.covered_project_count > self.eligible_project_count:
            raise ValueError(
                "covered_project_count cannot exceed eligible_project_count"
            )
        if self.average_score_pct is not None and (
            self.average_score_pct < Decimal("0")
            or self.average_score_pct > Decimal("100")
        ):
            raise ValueError("average_score_pct must be between 0 and 100")
        if self.average_score_pct is not None and self.covered_project_count <= 0:
            raise ValueError(
                "calculated confidence requires a positive covered_project_count"
            )
        if self.covered_project_count > 0 and self.average_score_pct is None:
            raise ValueError(
                "positive confidence coverage requires average_score_pct"
            )
        if self.availability in {
            SummaryMetricAvailability.NO_DATA,
            SummaryMetricAvailability.UNAVAILABLE,
        } and (
            self.average_score_pct is not None or self.covered_project_count != 0
        ):
            raise ValueError(
                "no_data/unavailable confidence must not carry calculated values"
            )
        if self.availability == SummaryMetricAvailability.AVAILABLE and (
            self.average_score_pct is None
            or self.covered_project_count <= 0
            or self.covered_project_count != self.eligible_project_count
        ):
            raise ValueError(
                "available confidence requires complete authorized-project coverage"
            )
        if (
            self.availability == SummaryMetricAvailability.PARTIAL
            and not self.limitations
        ):
            raise ValueError("partial confidence requires limitations")
        if (
            self.availability == SummaryMetricAvailability.UNAVAILABLE
            and not self.limitations
        ):
            raise ValueError("unavailable confidence requires limitations")
        return self


class ReportsSummaryMetric(ClientIntelligenceModel):
    availability: SummaryMetricAvailability
    drafted_count: int = Field(ge=0)
    approved_count: int = Field(ge=0)
    eligible_record_count: int = Field(ge=0)
    limitations: list[str] = Field(default_factory=list)

    @field_validator("limitations")
    @classmethod
    def _validate_limitations(cls, value: list[str]) -> list[str]:
        return _canonicalize_limitations(value)

    @model_validator(mode="after")
    def _report_invariants(self) -> ReportsSummaryMetric:
        if self.drafted_count + self.approved_count > self.eligible_record_count:
            raise ValueError(
                "drafted_count + approved_count cannot exceed eligible_record_count"
            )
        if (
            self.availability == SummaryMetricAvailability.AVAILABLE
            and self.eligible_record_count <= 0
        ):
            raise ValueError("available report metrics require an eligible population")
        if self.availability in {
            SummaryMetricAvailability.NO_DATA,
            SummaryMetricAvailability.UNAVAILABLE,
        } and (
            self.drafted_count != 0
            or self.approved_count != 0
            or self.eligible_record_count != 0
        ):
            raise ValueError(
                "no_data/unavailable report metrics must not carry calculated counts"
            )
        if (
            self.availability == SummaryMetricAvailability.PARTIAL
            and self.eligible_record_count == 0
            and not self.limitations
        ):
            raise ValueError(
                "partial report metrics without a calculated population require limitations"
            )
        if (
            self.availability == SummaryMetricAvailability.UNAVAILABLE
            and not self.limitations
        ):
            raise ValueError("unavailable report metrics require limitations")
        return self


class QueryResponseSummaryMetric(ClientIntelligenceModel):
    availability: SummaryMetricAvailability
    average_latency_ms: int | None = None
    sample_size: int = Field(ge=0)
    limitations: list[str] = Field(default_factory=list)

    @field_validator("limitations")
    @classmethod
    def _validate_limitations(cls, value: list[str]) -> list[str]:
        return _canonicalize_limitations(value)

    @model_validator(mode="after")
    def _query_invariants(self) -> QueryResponseSummaryMetric:
        if self.average_latency_ms is not None and self.average_latency_ms < 0:
            raise ValueError("average_latency_ms cannot be negative")
        if self.average_latency_ms is not None and self.sample_size <= 0:
            raise ValueError("calculated latency requires a positive sample_size")
        if self.sample_size > 0 and self.average_latency_ms is None:
            raise ValueError("positive query sample_size requires average_latency_ms")
        if self.availability in {
            SummaryMetricAvailability.NO_DATA,
            SummaryMetricAvailability.UNAVAILABLE,
        } and (self.average_latency_ms is not None or self.sample_size != 0):
            raise ValueError(
                "no_data/unavailable query metrics must not carry calculated values"
            )
        if (
            self.availability == SummaryMetricAvailability.AVAILABLE
            and (self.average_latency_ms is None or self.sample_size <= 0)
        ):
            raise ValueError(
                "available query metrics require calculated latency and positive sample_size"
            )
        if (
            self.availability == SummaryMetricAvailability.PARTIAL
            and self.average_latency_ms is None
            and not self.limitations
        ):
            raise ValueError(
                "partial query metrics without a calculated value require limitations"
            )
        if (
            self.availability == SummaryMetricAvailability.UNAVAILABLE
            and not self.limitations
        ):
            raise ValueError("unavailable query metrics require limitations")
        return self


class CsatSummaryMetric(ClientIntelligenceModel):
    availability: SummaryMetricAvailability
    average_score: Decimal | None = None
    sample_size: int = Field(ge=0)
    scale_max: int = Field(default=5, ge=5, le=5)
    limitations: list[str] = Field(default_factory=list)

    @field_validator("limitations")
    @classmethod
    def _validate_limitations(cls, value: list[str]) -> list[str]:
        return _canonicalize_limitations(value)

    @model_validator(mode="after")
    def _csat_invariants(self) -> CsatSummaryMetric:
        if self.average_score is not None and (
            self.average_score < Decimal("1") or self.average_score > Decimal("5")
        ):
            raise ValueError("average_score must be between 1 and 5")
        if self.average_score is not None and self.sample_size <= 0:
            raise ValueError("calculated CSAT requires a positive sample_size")
        if self.sample_size > 0 and self.average_score is None:
            raise ValueError("positive CSAT sample_size requires average_score")
        if self.availability in {
            SummaryMetricAvailability.NO_DATA,
            SummaryMetricAvailability.UNAVAILABLE,
        } and (self.average_score is not None or self.sample_size != 0):
            raise ValueError(
                "no_data/unavailable CSAT metrics must not carry calculated values"
            )
        if (
            self.availability == SummaryMetricAvailability.AVAILABLE
            and (self.average_score is None or self.sample_size <= 0)
        ):
            raise ValueError(
                "available CSAT metrics require calculated score and positive sample_size"
            )
        if (
            self.availability == SummaryMetricAvailability.PARTIAL
            and self.average_score is None
            and not self.limitations
        ):
            raise ValueError(
                "partial CSAT metrics without a calculated value require limitations"
            )
        if (
            self.availability == SummaryMetricAvailability.UNAVAILABLE
            and not self.limitations
        ):
            raise ValueError("unavailable CSAT metrics require limitations")
        return self


class ClientIntelligenceSummaryRead(ClientIntelligenceModel):
    """Authorized-scope read aggregates for the Client Intelligence summary cards."""

    delivery_confidence: DeliveryConfidenceSummaryMetric
    reports: ReportsSummaryMetric
    query_response: QueryResponseSummaryMetric
    csat: CsatSummaryMetric
    authorized_project_count: int = Field(ge=0)

    @model_validator(mode="after")
    def _summary_invariants(self) -> ClientIntelligenceSummaryRead:
        if (
            self.delivery_confidence.eligible_project_count
            != self.authorized_project_count
        ):
            raise ValueError(
                "confidence eligible project count must equal authorized_project_count"
            )
        return self


class ClientMasterHealthAvailability(StrEnum):
    """Bulk Client Master health availability (not Delivery Confidence status)."""

    NOT_ASSESSED = "not_assessed"


class ClientMasterRowRead(ClientIntelligenceModel):
    """Live project navigator row for the internal Client Master table."""

    project_id: UUID
    project_name: str
    project_count: int = Field(default=1, ge=1, le=1)
    health_status: ProjectHealthStatus | None = None
    health_availability: ClientMasterHealthAvailability = (
        ClientMasterHealthAvailability.NOT_ASSESSED
    )
    confidence_score_pct: Decimal | None = None
    last_report_at: datetime | None = None
    next_milestone_date: date | None = None
    csat_average: Decimal | None = None
    csat_sample_size: int = Field(default=0, ge=0)
    draft_count: int = Field(default=0, ge=0)

    @model_validator(mode="after")
    def _master_row_invariants(self) -> ClientMasterRowRead:
        if (
            self.health_availability
            == ClientMasterHealthAvailability.NOT_ASSESSED
            and self.health_status is not None
        ):
            raise ValueError(
                "not_assessed Client Master health must not carry health_status"
            )
        if self.confidence_score_pct is not None and not (
            Decimal("0") <= self.confidence_score_pct <= Decimal("100")
        ):
            raise ValueError("confidence_score_pct must be between 0 and 100")
        if self.csat_average is not None and not (
            Decimal("1") <= self.csat_average <= Decimal("5")
        ):
            raise ValueError("csat_average must be between 1 and 5")
        if self.csat_average is None and self.csat_sample_size != 0:
            raise ValueError("CSAT sample size requires a calculated average")
        if self.csat_average is not None and self.csat_sample_size <= 0:
            raise ValueError("calculated CSAT requires a positive sample size")
        return self


class DeliveryConfidenceHistoryAvailability(StrEnum):
    """Availability for project-scoped Delivery Confidence history reads."""

    AVAILABLE = "available"
    PARTIAL = "partial"
    NO_DATA = "no_data"
    UNAVAILABLE = "unavailable"


class DeliveryConfidenceCurrentScoreAvailability(StrEnum):
    """Canonical current Delivery Confidence row vs history-point validity."""

    AVAILABLE = "available"
    INVALID = "invalid"
    MISSING = "missing"


class DeliveryConfidenceHistoryPoint(ClientIntelligenceModel):
    """One persisted Delivery Confidence score in chronological history."""

    source_row_id: UUID
    project_id: UUID
    milestone_id: UUID
    score_pct: Decimal
    confidence_status: str
    observed_at: datetime

    @field_validator("observed_at")
    @classmethod
    def _require_aware_observed_at(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.tzinfo.utcoffset(value) is None:
            raise ValueError("observed_at must be timezone-aware")
        return value

    @model_validator(mode="after")
    def _point_invariants(self) -> DeliveryConfidenceHistoryPoint:
        if not (Decimal("0") <= self.score_pct <= Decimal("100")):
            raise ValueError("score_pct must be between 0 and 100")
        if not self.confidence_status.strip():
            raise ValueError("confidence_status must be non-empty")
        return self


class DeliveryConfidenceHistoryRead(ClientIntelligenceModel):
    """Bounded project-scoped Delivery Confidence history for sparkline reads."""

    project_id: UUID
    availability: DeliveryConfidenceHistoryAvailability
    points: list[DeliveryConfidenceHistoryPoint] = Field(default_factory=list)
    returned_point_count: int = Field(ge=0)
    total_valid_point_count: int = Field(ge=0)
    limitations: list[str] = Field(default_factory=list)
    current_score_availability: DeliveryConfidenceCurrentScoreAvailability
    current_source_row_id: UUID | None = None
    latest_history_point_is_current: bool = False

    @field_validator("limitations")
    @classmethod
    def _validate_limitations(cls, value: list[str]) -> list[str]:
        return _canonicalize_limitations(value)

    @model_validator(mode="after")
    def _history_invariants(self) -> DeliveryConfidenceHistoryRead:
        if self.returned_point_count != len(self.points):
            raise ValueError("returned_point_count must equal len(points)")
        if self.returned_point_count > self.total_valid_point_count:
            raise ValueError(
                "returned_point_count cannot exceed total_valid_point_count"
            )
        source_ids = [point.source_row_id for point in self.points]
        if len(source_ids) != len(set(source_ids)):
            raise ValueError("history points must have unique source_row_id values")
        for point in self.points:
            if point.project_id != self.project_id:
                raise ValueError("history point project_id must match parent project_id")
        ordered = sorted(
            self.points,
            key=lambda point: (point.observed_at, point.source_row_id),
        )
        if list(self.points) != ordered:
            raise ValueError(
                "history points must be ordered by observed_at ASC, source_row_id ASC"
            )

        if (
            self.current_score_availability
            == DeliveryConfidenceCurrentScoreAvailability.MISSING
        ):
            if self.current_source_row_id is not None:
                raise ValueError("missing current score requires null current_source_row_id")
            if self.latest_history_point_is_current:
                raise ValueError("missing current score cannot be current history point")
            if self.availability != DeliveryConfidenceHistoryAvailability.NO_DATA:
                raise ValueError("missing current score requires no_data availability")
        elif (
            self.current_score_availability
            == DeliveryConfidenceCurrentScoreAvailability.INVALID
        ):
            if self.current_source_row_id is None:
                raise ValueError("invalid current score requires current_source_row_id")
            if self.latest_history_point_is_current:
                raise ValueError(
                    "invalid current score cannot mark latest history point as current"
                )
            if self.availability != DeliveryConfidenceHistoryAvailability.PARTIAL:
                raise ValueError("invalid current score requires partial availability")
            if "LATEST_DELIVERY_CONFIDENCE_SCORE_OUT_OF_RANGE" not in self.limitations:
                raise ValueError(
                    "invalid current score requires LATEST_DELIVERY_CONFIDENCE_SCORE_OUT_OF_RANGE"
                )
        elif (
            self.current_score_availability
            == DeliveryConfidenceCurrentScoreAvailability.AVAILABLE
        ):
            if self.current_source_row_id is None:
                raise ValueError("available current score requires current_source_row_id")
            if self.points:
                newest = self.points[-1]
                matches = newest.source_row_id == self.current_source_row_id
                if self.latest_history_point_is_current != matches:
                    raise ValueError(
                        "latest_history_point_is_current must match newest point identity"
                    )
                if not matches:
                    raise ValueError(
                        "available current score must equal newest history point source_row_id"
                    )
            elif self.latest_history_point_is_current:
                raise ValueError(
                    "latest_history_point_is_current requires a newest history point"
                )

        if self.availability == DeliveryConfidenceHistoryAvailability.AVAILABLE:
            if not self.points:
                raise ValueError("available history requires at least one point")
            if self.limitations:
                raise ValueError("available history must not carry limitations")
            if self.returned_point_count != self.total_valid_point_count:
                raise ValueError(
                    "available history requires complete untruncated valid coverage"
                )
            if (
                self.current_score_availability
                != DeliveryConfidenceCurrentScoreAvailability.AVAILABLE
            ):
                raise ValueError("available history requires available current score")
            if not self.latest_history_point_is_current:
                raise ValueError(
                    "available history requires latest_history_point_is_current"
                )
        elif self.availability == DeliveryConfidenceHistoryAvailability.PARTIAL:
            if not self.limitations:
                raise ValueError("partial history requires limitations")
            if not self.points and self.total_valid_point_count != 0:
                raise ValueError(
                    "partial history without points requires total_valid_point_count=0"
                )
        elif self.availability == DeliveryConfidenceHistoryAvailability.NO_DATA:
            if self.points or self.returned_point_count != 0:
                raise ValueError("no_data history must not carry points")
            if self.total_valid_point_count != 0:
                raise ValueError("no_data history requires total_valid_point_count=0")
        elif self.availability == DeliveryConfidenceHistoryAvailability.UNAVAILABLE:
            if self.points or self.returned_point_count != 0:
                raise ValueError("unavailable history must not carry points")
            if not self.limitations:
                raise ValueError("unavailable history requires limitations")
        return self


class ClientIntelligenceReportStatus(StrEnum):
    """Statuses eligible for Approved & Sent report history."""

    APPROVED = "approved"
    SENT = "sent"


class ReportProvenanceAvailability(StrEnum):
    COMPLETE = "complete"
    PARTIAL = "partial"
    UNAVAILABLE = "unavailable"


class ClientIntelligenceReportHistoryItem(ClientIntelligenceModel):
    communication_id: UUID
    project_id: UUID
    report_type: str
    subject: str
    approved_body: str | None
    status: ClientIntelligenceReportStatus
    reviewed_by: UUID | None = None
    reviewed_at: datetime | None = None
    approved_by: UUID | None = None
    approved_at: datetime | None = None
    sent_at: datetime | None = None
    history_at: datetime | None = None
    provenance_availability: ReportProvenanceAvailability
    limitations: list[str] = Field(default_factory=list)
    evidence_links: list[EvidenceLinkRead] = Field(default_factory=list)
    created_at: datetime
    updated_at: datetime

    @field_validator("limitations")
    @classmethod
    def _validate_limitations(cls, value: list[str]) -> list[str]:
        return _canonicalize_limitations(value)

    @model_validator(mode="after")
    def _item_invariants(self) -> ClientIntelligenceReportHistoryItem:
        if self.provenance_availability == ReportProvenanceAvailability.COMPLETE:
            if not (self.approved_body or "").strip():
                raise ValueError("complete report requires approved_body")
            if self.approved_by is None or self.approved_at is None:
                raise ValueError("complete report requires approval provenance")
            if self.limitations:
                raise ValueError("complete report must not carry limitations")
            if self.status == ClientIntelligenceReportStatus.SENT and self.sent_at is None:
                raise ValueError("complete sent report requires sent_at")
        elif self.provenance_availability == ReportProvenanceAvailability.PARTIAL:
            if not self.limitations:
                raise ValueError("partial report requires limitations")
            if not (self.approved_body or "").strip():
                raise ValueError("partial report requires readable approved_body")
        elif self.provenance_availability == ReportProvenanceAvailability.UNAVAILABLE:
            if not self.limitations:
                raise ValueError("unavailable report requires limitations")
            if (self.approved_body or "").strip():
                raise ValueError("unavailable report must not expose approved_body")
        return self


class ClientIntelligenceReportHistoryRead(ClientIntelligenceModel):
    project_id: UUID
    items: list[ClientIntelligenceReportHistoryItem]
    limit: int = Field(ge=1, le=50)
    offset: int = Field(ge=0)
    total: int = Field(ge=0)
    has_more: bool
    status_filter: ClientIntelligenceReportStatus | None = None

    @model_validator(mode="after")
    def _page_invariants(self) -> ClientIntelligenceReportHistoryRead:
        if len(self.items) > self.limit:
            raise ValueError("items cannot exceed limit")
        if (
            self.offset + len(self.items) > self.total
            and self.total >= 0
            and self.items
            and self.offset >= self.total
        ):
            raise ValueError("offset beyond total cannot return items")
        expected_more = self.offset + len(self.items) < self.total
        if self.has_more != expected_more:
            raise ValueError("has_more must match offset+len(items) < total")
        return self


# Re-export Q&A contracts for API/schema consumers.
from app.agents.client_intelligence.query_contracts import (  # noqa: E402, F401
    ClientIntelligenceAnswerAvailability,
    ClientIntelligenceConfidenceLevel,
    ClientIntelligenceQueryEvidenceLink,
    ClientIntelligenceQueryHistoryRead,
    ClientIntelligenceQueryRead,
    ClientIntelligenceQueryRetrievalParams,
    ClientIntelligenceQuestionCategory,
    ClientIntelligenceQuestionCreate,
)
