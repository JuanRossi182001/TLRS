from pydantic import BaseModel, ConfigDict, Field
from typing import Optional
from src.models.asset import AssetStatus

class AssetBase(BaseModel):
    asset_type: str = Field(min_length=1, max_length=255)
    serial: str = Field(min_length=1, max_length=255)
    client_id: int = Field(gt=0)
    status: AssetStatus = AssetStatus.ACTIVE

class AssetCreate(AssetBase):
    pass

class AssetUpdate(BaseModel):
    asset_type: Optional[str] = None
    serial: Optional[str] = None
    client_id: Optional[int] = None
    status: Optional[AssetStatus] = None

class AssetResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id_asset: int
    asset_type: str
    serial: str
    client_id: int
    status: AssetStatus


class AssetListItem(AssetResponse):
    assigned_device_id: int | None = None
