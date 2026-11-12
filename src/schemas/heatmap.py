from datetime import datetime
from enum import Enum
from typing import Literal

from pydantic import BaseModel, ConfigDict, field_validator


class HeatmapSubjectType(str, Enum):
    ASSET = "asset"
    ASSET_GROUP = "asset_group"


class HeatmapRequest(BaseModel):
    subject_type: HeatmapSubjectType
    subject_id: int
    window_start: datetime
    window_end: datetime

    @field_validator("subject_id")
    @classmethod
    def validate_subject_id(cls, value: int) -> int:
        if value <= 0:
            raise ValueError("subject_id must be positive")
        return value

    @field_validator("window_start", "window_end")
    @classmethod
    def validate_utc_naive_datetime(cls, value: datetime) -> datetime:
        if value.tzinfo is not None:
            raise ValueError("timestamps must use UTC without a timezone offset")
        return value


class HeatmapPolygon(BaseModel):
    type: Literal["Polygon"] = "Polygon"
    coordinates: list[list[list[float]]]


class HeatmapCell(BaseModel):
    spatial_cell_id: str
    geometry: HeatmapPolygon
    dwell_seconds: float


class HeatmapCoverage(BaseModel):
    temporal_coverage_ratio: float | None
    observed_seconds: float
    eligible_assignment_seconds: float
    requested_seconds: float


class HeatmapResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    subject_type: HeatmapSubjectType
    subject_id: int
    window_start: datetime
    window_end: datetime
    availability: Literal["available", "no_data", "insufficient_evidence"]
    total_dwell_seconds: float
    coverage: HeatmapCoverage
    crs: str
    cell_size_meters: float
    cells: list[HeatmapCell]
