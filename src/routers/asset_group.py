from fastapi import APIRouter, Body, Depends, HTTPException, Query, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from src.db.config.connection import get_db
from src.schemas.asset_group import (
    AssetGroupActivationUpdate,
    AssetGroupCreate,
    AssetGroupDetailRead,
    AssetGroupMemberRemove,
    AssetGroupMembersUpdate,
    AssetGroupRead,
    AssetGroupUpdate,
)
from src.schemas.user import TokenData
from src.service.asset_group_service import (
    AssetGroupNotFoundError,
    AssetGroupService,
    AssetGroupValidationError,
)
from src.service.crud_user import get_current_user
from src.utils.validations import validate_user_service_access


router = APIRouter(prefix="/asset-groups", tags=["Asset Groups"])


@router.post(
    "",
    status_code=status.HTTP_201_CREATED,
    response_model=AssetGroupDetailRead,
)
async def create_asset_group(
    payload: AssetGroupCreate,
    client_id: int | None = Query(default=None),
    db: AsyncSession = Depends(get_db),
    current_user: TokenData = Depends(get_current_user),
):
    await validate_user_service_access(current_user, "asset-group:create", db)
    resolved_client_id = _resolve_client_id(current_user, client_id)

    service = AssetGroupService(db)
    try:
        return await service.create_asset_group(resolved_client_id, payload)
    except AssetGroupValidationError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "message": exc.detail,
                "asset_ids": exc.asset_ids,
            },
        )
    except IntegrityError:
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Asset group name already exists for this client.",
        )


@router.get(
    "/my-asset-groups",
    status_code=status.HTTP_200_OK,
    response_model=list[AssetGroupRead],
)
async def get_my_asset_groups(
    active: bool | None = Query(default=None),
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=500),
    search: str | None = Query(default=None),
    db: AsyncSession = Depends(get_db),
    current_user: TokenData = Depends(get_current_user),
):
    await validate_user_service_access(current_user, "asset-group:get my asset groups", db)
    client_id = _resolve_client_id(current_user, None)

    service = AssetGroupService(db)
    return await service.get_asset_groups_by_client_id(
        client_id=client_id,
        active=active,
        skip=skip,
        limit=limit,
        search=search,
    )


@router.get(
    "/{id_asset_group}",
    status_code=status.HTTP_200_OK,
    response_model=AssetGroupDetailRead,
)
async def get_asset_group(
    id_asset_group: int,
    db: AsyncSession = Depends(get_db),
    current_user: TokenData = Depends(get_current_user),
):
    await validate_user_service_access(current_user, "asset-group:get", db)
    client_id = _resolve_client_id(current_user, None)

    service = AssetGroupService(db)
    asset_group = await service.get_asset_group_detail_for_client(id_asset_group, client_id)
    if asset_group is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Asset group not found.",
        )

    return asset_group


@router.patch(
    "/{id_asset_group}",
    status_code=status.HTTP_200_OK,
    response_model=AssetGroupDetailRead,
)
async def update_asset_group(
    id_asset_group: int,
    payload: AssetGroupUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: TokenData = Depends(get_current_user),
):
    await validate_user_service_access(current_user, "asset-group:update", db)
    client_id = _resolve_client_id(current_user, None)

    service = AssetGroupService(db)
    try:
        asset_group = await service.update_asset_group(id_asset_group, client_id, payload)
    except AssetGroupValidationError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "message": exc.detail,
                "asset_ids": exc.asset_ids,
            },
        )
    except IntegrityError:
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Asset group name already exists for this client.",
        )

    if asset_group is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Asset group not found.",
        )

    return asset_group


@router.patch(
    "/{id_asset_group}/activation",
    status_code=status.HTTP_200_OK,
    response_model=AssetGroupDetailRead,
)
async def set_asset_group_activation(
    id_asset_group: int,
    payload: AssetGroupActivationUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: TokenData = Depends(get_current_user),
):
    await validate_user_service_access(current_user, "asset-group:update activation", db)
    client_id = _resolve_client_id(current_user, None)

    service = AssetGroupService(db)
    asset_group = await service.set_asset_group_active(id_asset_group, client_id, payload)
    if asset_group is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Asset group not found.",
        )

    return asset_group


@router.post(
    "/{id_asset_group}/members",
    status_code=status.HTTP_200_OK,
    response_model=AssetGroupDetailRead,
)
async def add_asset_group_members(
    id_asset_group: int,
    payload: AssetGroupMembersUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: TokenData = Depends(get_current_user),
):
    await validate_user_service_access(current_user, "asset-group:add members", db)
    client_id = _resolve_client_id(current_user, None)

    service = AssetGroupService(db)
    try:
        return await service.add_members(id_asset_group, client_id, payload)
    except AssetGroupNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=exc.detail,
        )
    except AssetGroupValidationError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "message": exc.detail,
                "asset_ids": exc.asset_ids,
            },
        )


@router.delete(
    "/{id_asset_group}/members",
    status_code=status.HTTP_200_OK,
    response_model=AssetGroupDetailRead,
)
async def remove_asset_group_members(
    id_asset_group: int,
    payload: AssetGroupMemberRemove = Body(...),
    db: AsyncSession = Depends(get_db),
    current_user: TokenData = Depends(get_current_user),
):
    await validate_user_service_access(current_user, "asset-group:remove members", db)
    client_id = _resolve_client_id(current_user, None)

    service = AssetGroupService(db)
    try:
        return await service.remove_members(id_asset_group, client_id, payload.asset_ids)
    except AssetGroupNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=exc.detail,
        )


def _resolve_client_id(
    current_user: TokenData,
    requested_client_id: int | None,
) -> int:
    if current_user.is_admin and requested_client_id is not None:
        return requested_client_id

    if current_user.client_id is not None:
        return current_user.client_id

    raise HTTPException(
        status_code=status.HTTP_400_BAD_REQUEST,
        detail="client_id is required for this asset group operation.",
    )
