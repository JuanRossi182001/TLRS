from pydantic import BaseModel
from typing import Optional
from src.models.asset import AssetStatus

class AssetBase(BaseModel):
    asset_type: str
    serial: str
    client_id: int
    status: AssetStatus

class AssetCreate(AssetBase):
    pass

class AssetUpdate(BaseModel):
    asset_type: Optional[str] = None
    serial: Optional[str] = None
    client_id: Optional[int] = None
    status: Optional[AssetStatus] = None

class AssetResponse(BaseModel):
    id_asset: int
    asset_type: str
    serial: str
    client_id: int
    status: AssetStatus