from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from src.db.config.connection import get_db
from src.schemas.rbac import (
    RoleCreate,
    RoleResponse,
    ServiceCreate,
    ServiceResponse,
    ServiceRoleResponse,
    UserRoleResponse,
)
from src.service.rbac_service import RbacConflictError, RbacNotFoundError, RbacService


router = APIRouter(prefix="/rbac", tags=["RBAC"])


@router.post(
    "/services",
    status_code=status.HTTP_201_CREATED,
    response_model=ServiceResponse,
)
async def create_service(
    payload: ServiceCreate,
    db: AsyncSession = Depends(get_db),
):
    try:
        return await RbacService(db).create_service(payload)
    except RbacConflictError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=exc.detail,
        )


@router.post(
    "/roles",
    status_code=status.HTTP_201_CREATED,
    response_model=RoleResponse,
)
async def create_role(
    payload: RoleCreate,
    db: AsyncSession = Depends(get_db),
):
    try:
        return await RbacService(db).create_role(payload)
    except RbacConflictError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=exc.detail,
        )


@router.post(
    "/roles/{role_id}/services/{service_id}",
    status_code=status.HTTP_201_CREATED,
    response_model=ServiceRoleResponse,
)
async def assign_service_to_role(
    role_id: int,
    service_id: int,
    db: AsyncSession = Depends(get_db),
):
    try:
        return await RbacService(db).assign_service_to_role(
            role_id=role_id,
            service_id=service_id,
        )
    except RbacNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=exc.detail,
        )
    except RbacConflictError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=exc.detail,
        )


@router.post(
    "/users/{user_id}/roles/{role_id}",
    status_code=status.HTTP_201_CREATED,
    response_model=UserRoleResponse,
)
async def assign_role_to_user(
    user_id: int,
    role_id: int,
    db: AsyncSession = Depends(get_db),
):
    try:
        return await RbacService(db).assign_role_to_user(
            user_id=user_id,
            role_id=role_id,
        )
    except RbacNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=exc.detail,
        )
    except RbacConflictError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=exc.detail,
        )
