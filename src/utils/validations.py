from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.models.service import Service, ServiceRoles
from src.models.user import UserRoles
from src.schemas.user import TokenData


async def validate_user_service_access(
    current_user: TokenData,
    service_name: str,
    db: AsyncSession,
) -> bool:
    if current_user.is_admin:
        return True

    result = await db.execute(
        select(ServiceRoles.id_service_role)
        .join(Service, Service.id_service == ServiceRoles.service_id)
        .join(UserRoles, UserRoles.role_id == ServiceRoles.role_id)
        .filter(
            UserRoles.user_id == current_user.user_id,
            UserRoles.deleted == "N",
            ServiceRoles.deleted == "N",
            Service.deleted == "N",
            Service.name == service_name,
        )
    )
    has_access = result.first() is not None

    if not has_access:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="User does not have access to this service.",
        )

    return True
