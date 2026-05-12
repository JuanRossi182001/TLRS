from src.models.asset import Asset
from src.schemas.asset import(
AssetUpdate,
AssetCreate
)
from src.service.crud_base import CrudBase

class AssetService(CrudBase[Asset, AssetCreate, AssetUpdate]):
    model=Asset
