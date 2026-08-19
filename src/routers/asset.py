from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from src.db.config.connection import get_db
from src.schemas.asset import AssetCreate, AssetListItem, AssetResponse
from src.schemas.user import TokenData
from src.service.crud_asset import AssetNotFoundError, AssetService
from src.service.crud_user import get_current_user


router = APIRouter(prefix="/assets", tags=["Assets"])


def _require_admin_user(current_user: TokenData) -> None:
    if not current_user.is_admin:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only admin users can manage assets.",
        )


@router.post("", status_code=status.HTTP_201_CREATED, response_model=AssetResponse)
async def create_asset(
    payload: AssetCreate,
    db: AsyncSession = Depends(get_db),
    current_user: TokenData = Depends(get_current_user),
):
    _require_admin_user(current_user)
    service = AssetService(db)

    try:
        return await service.create_asset(payload)
    except AssetNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))
    except IntegrityError:
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Asset serial already exists.",
        )


@router.get("", status_code=status.HTTP_200_OK, response_model=list[AssetListItem])
async def get_assets(
    client_id: int = Query(gt=0),
    unassigned: bool | None = Query(default=None),
    db: AsyncSession = Depends(get_db),
    current_user: TokenData = Depends(get_current_user),
):
    _require_admin_user(current_user)
    service = AssetService(db)

    try:
        return await service.get_assets(client_id=client_id, unassigned=unassigned)
    except AssetNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))
