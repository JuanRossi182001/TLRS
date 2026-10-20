from sqlalchemy.exc import IntegrityError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.models.service import Service, ServiceRoles
from src.models.user import Role, User, UserRoles
from src.schemas.rbac import RoleCreate, ServiceCreate


class RbacNotFoundError(Exception):
    def __init__(self, detail: str):
        self.detail = detail


class RbacConflictError(Exception):
    def __init__(self, detail: str):
        self.detail = detail


class RbacService:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def create_service(self, payload: ServiceCreate) -> Service:
        service = Service(name=payload.name)
        self.db.add(service)

        try:
            await self.db.commit()
            await self.db.refresh(service)
            return service

        except IntegrityError:
            await self.db.rollback()
            raise RbacConflictError("Service already exists.")

    async def create_role(self, payload: RoleCreate) -> Role:
        role = Role(name=payload.name)
        self.db.add(role)

        try:
            await self.db.commit()
            await self.db.refresh(role)
            return role

        except IntegrityError:
            await self.db.rollback()
            raise RbacConflictError("Role already exists.")

    async def assign_service_to_role(
        self,
        role_id: int,
        service_id: int,
    ) -> ServiceRoles:
        role = await self.db.get(Role, role_id)
        if role is None or role.deleted == "Y":
            raise RbacNotFoundError("Role not found.")

        service = await self.db.get(Service, service_id)
        if service is None or service.deleted == "Y":
            raise RbacNotFoundError("Service not found.")

        result = await self.db.execute(select(ServiceRoles).filter(
            ServiceRoles.role_id == role_id,
            ServiceRoles.service_id == service_id,
        ))
        assignment = result.scalar_one_or_none()

        if assignment is not None:
            assignment.deleted = "N"
        else:
            assignment = ServiceRoles(role_id=role_id, service_id=service_id)

        self.db.add(assignment)

        try:
            await self.db.commit()
            await self.db.refresh(assignment)
            return assignment

        except IntegrityError:
            await self.db.rollback()
            raise RbacConflictError("Service is already assigned to role.")

    async def assign_role_to_user(
        self,
        user_id: int,
        role_id: int,
    ) -> UserRoles:
        user = await self.db.get(User, user_id)
        if user is None or user.deleted == "Y":
            raise RbacNotFoundError("User not found.")

        role = await self.db.get(Role, role_id)
        if role is None or role.deleted == "Y":
            raise RbacNotFoundError("Role not found.")

        result = await self.db.execute(select(UserRoles).filter(
            UserRoles.user_id == user_id,
            UserRoles.role_id == role_id,
        ))
        assignment = result.scalar_one_or_none()

        if assignment is not None:
            assignment.deleted = "N"
        else:
            assignment = UserRoles(user_id=user_id, role_id=role_id)

        self.db.add(assignment)

        try:
            await self.db.commit()
            await self.db.refresh(assignment)
            return assignment

        except IntegrityError:
            await self.db.rollback()
            raise RbacConflictError("Role is already assigned to user.")
