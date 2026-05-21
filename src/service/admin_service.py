from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql import select, update

from src.service.crud_user import UserService
from src.service.crud_device import DeviceService
from src.service.crud_client import ClientService
from src.schemas.admin import DashboardStatsResponse
class AdminService:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def get_admin_dashboard_stats(self) -> DashboardStatsResponse:
        clients_count = await ClientService(self.db).get_clients_count()
        users_count = await UserService(self.db).get_active_users_count()
        devices_count = await DeviceService(self.db).get_devices_admin_stats()
        return DashboardStatsResponse(clients_data=clients_count, users_data=users_count, devices_data=devices_count)