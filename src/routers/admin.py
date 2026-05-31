from fastapi import APIRouter, HTTPException, status, Depends, Query
from src.db.config.connection import get_db
from sqlalchemy.ext.asyncio import AsyncSession


from src.service.admin_service import AdminService
from src.service.crud_client import ClientService
from src.service.crud_device import DeviceService
from src.service.crud_user import UserService
from src.schemas.user import UserDashboardResponse, UserResponse
from src.schemas.admin import DashboardStatsResponse
from src.schemas.device import DeviceAdminResponse, DeviceRead, DeviceUpdate
from src.schemas.client import ClientDashboardResponse
from src.schemas.user import TokenData
from src.utils.validations import validate_user_service_access
from src.service.crud_user import get_current_user

router = APIRouter(prefix="/admin", tags=["Admin"])

@router.get(
    "/stats",
    status_code=status.HTTP_200_OK,
    response_model=DashboardStatsResponse,
)
async def get_admin_dashboard_stats(
    db: AsyncSession = Depends(get_db),
    current_user: TokenData = Depends(get_current_user)
):
    await validate_user_service_access(current_user, "admin:get dashboard stats", db)

    service = AdminService(db)
    return await service.get_admin_dashboard_stats()

@router.get(
    "/clients",
    status_code=status.HTTP_200_OK,
    response_model=list[ClientDashboardResponse]
)
async def get_clients(
    db: AsyncSession = Depends(get_db),
    current_user: TokenData = Depends(get_current_user)
):
    await validate_user_service_access(current_user, "admin:get clients", db)

    service = ClientService(db)
    return await service.get_clients_dashboard()

@router.get(
    "/devices",
    status_code=status.HTTP_200_OK,
    response_model=list[DeviceAdminResponse]
)
async def get_all_devices(
    skip: int = Query(0, ge=0),
    limit: int = Query(25, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
    current_user: TokenData = Depends(get_current_user),
):
    await validate_user_service_access(current_user, "admin:get all devices", db)
    device_service = DeviceService(db)

    devices = await device_service.get_devices(skip=skip, limit=limit)

    return devices


@router.get(
    "/users",
    status_code=status.HTTP_200_OK,
    response_model=list[UserDashboardResponse],
)
async def get_all_users(
    db: AsyncSession = Depends(get_db),
    current_user: TokenData = Depends(get_current_user),
):
    await validate_user_service_access(current_user, "admin:get all users", db)
    user_service = UserService(db)

    users = await user_service.get_users_dashboard()

    return users


@router.get(
    "/clients/{client_id}/users",
    status_code=status.HTTP_200_OK,
    response_model=list[UserResponse],
)
async def get_client_users(
    client_id: int,
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
    current_user: TokenData = Depends(get_current_user),
):
    await validate_user_service_access(current_user, "admin:get client users", db)
    user_service = UserService(db)

    return await user_service.get_users_by_client_id(
        client_id=client_id,
        skip=skip,
        limit=limit,
    )


@router.patch(
    "/devices/{device_id}",
    status_code=status.HTTP_200_OK,
    response_model=DeviceRead,
)
async def update_device(
    device_id: int,
    payload: DeviceUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: TokenData = Depends(get_current_user),
):
    await validate_user_service_access(current_user, "admin:update device", db)
    device_service = DeviceService(db)

    device = await device_service.update_device(device_id, payload)
    if device is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Device not found.",
        )

    return device


@router.patch(
    "/users/{user_id}/deactivate",
    status_code=status.HTTP_200_OK,
    response_model=UserResponse,
)
async def deactivate_user(
    user_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: TokenData = Depends(get_current_user),
):
    await validate_user_service_access(current_user, "admin:deactivate user", db)
    user_service = UserService(db)

    user = await user_service.deactivate_user(user_id)
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found.",
        )

    return user


@router.patch(
    "/users/{user_id}/reactivate",
    status_code=status.HTTP_200_OK,
    response_model=UserResponse,
)
async def reactivate_user(
    user_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: TokenData = Depends(get_current_user),
):
    await validate_user_service_access(current_user, "admin:reactivate user", db)
    user_service = UserService(db)

    user = await user_service.reactivate_user(user_id)
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found.",
        )

    return user


@router.patch(
    "/devices/{device_id}/deactivate",
    status_code=status.HTTP_200_OK,
    response_model=DeviceRead,
)
async def deactivate_device(
    device_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: TokenData = Depends(get_current_user),
):
    await validate_user_service_access(current_user, "admin:deactivate device", db)
    device_service = DeviceService(db)

    device = await device_service.deactivate_device(device_id)
    if device is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Device not found.",
        )

    return device


@router.patch(
    "/devices/{device_id}/reactivate",
    status_code=status.HTTP_200_OK,
    response_model=DeviceRead,
)
async def reactivate_device(
    device_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: TokenData = Depends(get_current_user),
):
    await validate_user_service_access(current_user, "admin:reactivate device", db)
    device_service = DeviceService(db)

    device = await device_service.reactivate_device(device_id)
    if device is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Device not found.",
        )

    return device
