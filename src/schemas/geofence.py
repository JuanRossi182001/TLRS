from datetime import datetime
from enum import Enum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from src.models.geofence import FenceEventType


Position = tuple[float, float]
LinearRing = list[Position]
PolygonCoordinates = list[LinearRing]
MultiPolygonCoordinates = list[PolygonCoordinates]


class GeoJSONMultiPolygon(BaseModel):
    type: Literal["MultiPolygon"] = "MultiPolygon"
    coordinates: MultiPolygonCoordinates

    @field_validator("coordinates")
    @classmethod
    def validate_coordinates(
        cls,
        coordinates: MultiPolygonCoordinates,
    ) -> MultiPolygonCoordinates:
        if not coordinates:
            raise ValueError("A geofence requires at least one polygon.")

        for polygon in coordinates:
            if not polygon:
                raise ValueError("Each polygon requires at least one linear ring.")

            for ring in polygon:
                if len(ring) < 4:
                    raise ValueError("Each linear ring requires at least four positions.")

                if ring[0] != ring[-1]:
                    raise ValueError("Each linear ring must be closed.")

        return coordinates


class GeoFenceCreate(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    description: str | None = None
    shape: GeoJSONMultiPolygon
    active: bool = True


class GeoFenceUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=255)
    description: str | None = None
    shape: GeoJSONMultiPolygon | None = None
    active: bool | None = None


class GeoFenceActivationUpdate(BaseModel):
    active: bool


class GeoFenceRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id_geofence: int
    client_id: int
    name: str
    description: str | None = None
    shape: GeoJSONMultiPolygon | None = None
    active: bool
    created_at: datetime
    updated_at: datetime


class GeoFenceAssignmentCreate(BaseModel):
    asset_ids: list[int] = Field(min_length=1)

    @field_validator("asset_ids")
    @classmethod
    def validate_asset_ids(cls, asset_ids: list[int]) -> list[int]:
        if len(asset_ids) != len(set(asset_ids)):
            raise ValueError("asset_ids cannot contain duplicates.")

        return asset_ids


class GeoFenceAssignmentRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id_assignment: int
    asset_id: int
    fence_id: int
    active: bool
    assigned_at: datetime
    unassigned_at: datetime | None = None


class GeoFenceEventCreate(BaseModel):
    fence_id: int
    device_id: int
    asset_id: int | None = None
    location_id: int
    event_type: FenceEventType
    distance_to_boundary_meters: float | None = None
    accuracy: float | None = None


class GeoFenceEventRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id_event: int
    fence_id: int
    geofence_name: str
    device_id: int
    device_name: str
    device_serial: str
    asset_type: str | None = None
    asset_id: int | None = None
    location_id: int
    event_type: FenceEventType
    distance_to_boundary_meters: float | None = None
    accuracy: float | None = None
    created_at: datetime


class GeoFenceEventTimeFilter(str, Enum):
    TODAY = "today"
    LAST_7_DAYS = "7_days"
    ALL = "all"


class GeoFenceEventRelevanceFilter(str, Enum):
    ALL = "all"
    IMPORTANT_ONLY = "important_only"


class GeoFenceEventTypeFilter(str, Enum):
    EXITED = "EXITED"
    NEAR_LIMIT = "NEAR_LIMIT"
    RETURNED = "RETURNED"
    GPS_UNCERTAIN = "GPS_UNCERTAIN"


class GeoFenceEventStatsResponse(BaseModel):
    total_events: int
    near_limit_events: int
    exited_events: int
    returned_events: int
    gps_unknown_events: int


class GeoFenceEventPaginatedResponse(BaseModel):
    total: int
    skip: int
    limit: int
    stats: GeoFenceEventStatsResponse
    items: list[GeoFenceEventRead]


class AssetState(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id_asset: int
    asset_type: str
    asset_serial: str
    id_device: int
    device_serial: str
    device_name: str
    fence_id: int
    geofence_name: str
    current_status: str
    last_location_id: int
    latitude: float
    longitude: float
    last_distance_to_boundary_meters: float | None
    last_accuracy: float | None
    last_evaluated_at: datetime
