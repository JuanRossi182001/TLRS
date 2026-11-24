from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from src.db.config.connection import get_db
from src.schemas.map_reference_point import (
    MapReferencePointCreate,
    MapReferencePointRead,
    MapReferencePointUpdate,
)
from src.schemas.user import TokenData
from src.service.crud_user import get_current_user
from src.service.map_reference_point_service import MapReferencePointService


router = APIRouter(prefix="/map-reference-points", tags=["Map reference points"])


@router.post(
    "",
    status_code=status.HTTP_201_CREATED,
    response_model=MapReferencePointRead,
)
async def create_map_reference_point(
    payload: MapReferencePointCreate,
    client_id: int | None = Query(default=None, ge=1),
    db: AsyncSession = Depends(get_db),
    current_user: TokenData = Depends(get_current_user),
):
    scoped_client_id = _resolve_client_id(current_user, client_id)
    service = MapReferencePointService(db)
    point = await service.create(
        client_id=scoped_client_id,
        category=payload.category,
        other_type=payload.other_type,
        name=payload.name,
        latitude=payload.latitude,
        longitude=payload.longitude,
        note=payload.note,
    )
    return await service.get_read_model_for_client(
        point.id_map_reference_point,
        scoped_client_id,
    )


@router.get(
    "",
    status_code=status.HTTP_200_OK,
    response_model=list[MapReferencePointRead],
)
async def list_map_reference_points(
    skip: int = Query(default=0, ge=0),
    limit: int = Query(default=500, ge=1, le=500),
    client_id: int | None = Query(default=None, ge=1),
    db: AsyncSession = Depends(get_db),
    current_user: TokenData = Depends(get_current_user),
):
    scoped_client_id = _resolve_client_id(current_user, client_id)
    return await MapReferencePointService(db).list_read_models_for_client(
        scoped_client_id,
        skip=skip,
        limit=limit,
    )


@router.get(
    "/{point_id}",
    status_code=status.HTTP_200_OK,
    response_model=MapReferencePointRead,
)
async def get_map_reference_point(
    point_id: int,
    client_id: int | None = Query(default=None, ge=1),
    db: AsyncSession = Depends(get_db),
    current_user: TokenData = Depends(get_current_user),
):
    scoped_client_id = _resolve_client_id(current_user, client_id)
    point = await MapReferencePointService(db).get_read_model_for_client(
        point_id,
        scoped_client_id,
    )
    if point is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Map reference point not found.",
        )
    return point


@router.put(
    "/{point_id}",
    status_code=status.HTTP_200_OK,
    response_model=MapReferencePointRead,
)
async def update_map_reference_point(
    point_id: int,
    payload: MapReferencePointUpdate,
    client_id: int | None = Query(default=None, ge=1),
    db: AsyncSession = Depends(get_db),
    current_user: TokenData = Depends(get_current_user),
):
    scoped_client_id = _resolve_client_id(current_user, client_id)
    service = MapReferencePointService(db)
    point = await service.update(
        point_id,
        client_id=scoped_client_id,
        category=payload.category,
        other_type=payload.other_type,
        name=payload.name,
        latitude=payload.latitude,
        longitude=payload.longitude,
        note=payload.note,
    )
    if point is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Map reference point not found.",
        )
    return await service.get_read_model_for_client(
        point_id,
        scoped_client_id,
    )


@router.delete(
    "/{point_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def delete_map_reference_point(
    point_id: int,
    client_id: int | None = Query(default=None, ge=1),
    db: AsyncSession = Depends(get_db),
    current_user: TokenData = Depends(get_current_user),
) -> Response:
    scoped_client_id = _resolve_client_id(current_user, client_id)
    deleted = await MapReferencePointService(db).delete(point_id, scoped_client_id)
    if not deleted:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Map reference point not found.",
        )
    return Response(status_code=status.HTTP_204_NO_CONTENT)


def _resolve_client_id(
    current_user: TokenData,
    requested_client_id: int | None,
) -> int:
    if current_user.is_admin:
        if requested_client_id is not None:
            return requested_client_id
        if current_user.client_id is not None:
            return current_user.client_id
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="client_id is required for this map reference point operation.",
        )

    if current_user.client_id is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="A client scope is required.",
        )
    if requested_client_id is not None and requested_client_id != current_user.client_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Map reference point not found.",
        )
    return current_user.client_id
