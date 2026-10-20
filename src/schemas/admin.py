from pydantic import BaseModel
from .device import DevicesStatsAdminResult


class DashboardStatsResponse(BaseModel):
    devices_data: DevicesStatsAdminResult
    clients_data: int
    users_data: int
