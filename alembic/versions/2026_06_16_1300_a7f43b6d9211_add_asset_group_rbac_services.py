"""add asset group rbac services

Revision ID: a7f43b6d9211
Revises: 5b4b3db4ef01
Create Date: 2026-06-16 13:00:00.000000
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "a7f43b6d9211"
down_revision: Union[str, Sequence[str], None] = "5b4b3db4ef01"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


SERVICE_NAMES = (
    "asset-group:create",
    "asset-group:get my asset groups",
    "asset-group:get",
    "asset-group:update",
    "asset-group:update activation",
    "asset-group:add members",
    "asset-group:remove members",
    "geofence:assign asset group",
    "geofence:remove asset group",
)
DEFAULT_ROLE_ID = 1


def upgrade() -> None:
    bind = op.get_bind()
    for service_name in SERVICE_NAMES:
        bind.execute(
            sa.text(
                """
                INSERT INTO services (name, deleted)
                VALUES (:name, 'N')
                ON CONFLICT (name)
                DO UPDATE SET deleted = 'N'
                """
            ),
            {"name": service_name},
        )

    for service_name in SERVICE_NAMES:
        bind.execute(
            sa.text(
                """
                INSERT INTO service_roles (service_id, role_id, deleted)
                SELECT id_service, :role_id, 'N'
                FROM services
                WHERE name = :name
                ON CONFLICT (service_id, role_id)
                DO UPDATE SET deleted = 'N'
                """
            ),
            {
                "name": service_name,
                "role_id": DEFAULT_ROLE_ID,
            },
        )


def downgrade() -> None:
    bind = op.get_bind()
    for service_name in SERVICE_NAMES:
        bind.execute(
            sa.text(
                """
                UPDATE service_roles
                SET deleted = 'Y'
                WHERE role_id = :role_id
                  AND service_id IN (
                      SELECT id_service
                      FROM services
                      WHERE name = :name
                  )
                """
            ),
            {
                "name": service_name,
                "role_id": DEFAULT_ROLE_ID,
            },
        )
        bind.execute(
            sa.text(
                """
                UPDATE services
                SET deleted = 'Y'
                WHERE name = :name
                """
            ),
            {"name": service_name},
        )
