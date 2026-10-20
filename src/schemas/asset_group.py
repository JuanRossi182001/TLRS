from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator

from src.models.device import DeviceState


class AssetGroupCreate(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    description: str | None = None
    asset_ids: list[int] | None = None

    @field_validator("asset_ids")
    @classmethod
    def validate_asset_ids(cls, asset_ids: list[int] | None) -> list[int] | None:
        if asset_ids is None:
            return None

        if len(asset_ids) != len(set(asset_ids)):
            raise ValueError("asset_ids cannot contain duplicates.")

        return asset_ids


class AssetGroupUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=255)
    description: str | None = None
    asset_ids: list[int] | None = None

    @field_validator("asset_ids")
    @classmethod
    def validate_asset_ids(cls, asset_ids: list[int] | None) -> list[int] | None:
        if asset_ids is None:
            return None

        if len(asset_ids) != len(set(asset_ids)):
            raise ValueError("asset_ids cannot contain duplicates.")

        return asset_ids


class AssetGroupActivationUpdate(BaseModel):
    active: bool


class AssetGroupMembersUpdate(BaseModel):
    asset_ids: list[int] = Field(min_length=1)

    @field_validator("asset_ids")
    @classmethod
    def validate_asset_ids(cls, asset_ids: list[int]) -> list[int]:
        if len(asset_ids) != len(set(asset_ids)):
            raise ValueError("asset_ids cannot contain duplicates.")

        return asset_ids


class AssetGroupMemberRemove(BaseModel):
    asset_ids: list[int] = Field(min_length=1)

    @field_validator("asset_ids")
    @classmethod
    def validate_asset_ids(cls, asset_ids: list[int]) -> list[int]:
        if len(asset_ids) != len(set(asset_ids)):
            raise ValueError("asset_ids cannot contain duplicates.")

        return asset_ids


class GeofenceAssetGroupsAssign(BaseModel):
    asset_group_ids: list[int] = Field(min_length=1)

    @field_validator("asset_group_ids")
    @classmethod
    def validate_asset_group_ids(cls, asset_group_ids: list[int]) -> list[int]:
        if len(asset_group_ids) != len(set(asset_group_ids)):
            raise ValueError("asset_group_ids cannot contain duplicates.")

        return asset_group_ids


class GeofenceAssetGroupsRemove(BaseModel):
    asset_group_ids: list[int] = Field(min_length=1)

    @field_validator("asset_group_ids")
    @classmethod
    def validate_asset_group_ids(cls, asset_group_ids: list[int]) -> list[int]:
        if len(asset_group_ids) != len(set(asset_group_ids)):
            raise ValueError("asset_group_ids cannot contain duplicates.")

        return asset_group_ids


class AssetGroupRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id_asset_group: int
    client_id: int
    name: str
    description: str | None = None
    active: bool
    total_assets: int
    geofences_assigned: list["AssetGroupAssignedGeofenceRead"]
    created_at: datetime
    updated_at: datetime


class AssetGroupAssignedGeofenceRead(BaseModel):
    id_geofence_asset_group: int
    geofence_id: int
    geofence_name: str
    geofence_description: str | None = None
    geofence_active: bool
    assignment_active: bool
    assigned_at: datetime
    unassigned_at: datetime | None = None


class AssetGroupMemberRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    asset_id: int
    asset_name: str
    asset_type: str
    asset_serial: str
    device_id: int | None = None
    device_serial: str | None = None
    device_name: str | None = None
    device_active: bool | None = None
    device_state: DeviceState | None = None


class AssetGroupDetailRead(AssetGroupRead):
    members: list[AssetGroupMemberRead]


class GeoFenceAssetGroupRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id_geofence_asset_group: int
    geofence_id: int
    asset_group_id: int
    active: bool
    assigned_at: datetime
    unassigned_at: datetime | None = None
