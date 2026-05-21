from src.service.crud_client import ClientService
from fastapi import APIRouter,status, Depends, Query
from src.db.config.connection import get_db
from sqlalchemy.ext.asyncio import AsyncSession


from src.service.admin_service import AdminService
from src.service.crud_client import ClientService
from src.service.crud_device import DeviceService
from src.service.crud_user import UserService
from src.schemas.user import UserDashboardResponse
from src.schemas.admin import DashboardStatsResponse
from src.schemas.device import DeviceAdminResponse
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