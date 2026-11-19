"""seed full-access client role

Revision ID: 4d8a2f6c1b90
Revises: 3c6d9f2a4b81
Create Date: 2026-11-19 12:00:00.000000
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "4d8a2f6c1b90"
down_revision: Union[str, Sequence[str], None] = "3c6d9f2a4b81"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


ROLE_NAME = "cliente_completo"
SERVICE_NAMES = (
    "asset:get my assets",
    "device:get my devices",
    "device:get latest locations",
    "geofence:create",
    "geofence:get my geofences",
    "geofence:get events",
    "geofence:get",
    "geofence:update",
    "geofence:delete",
    "geofence:assign asset",
    "geofence:get assignments",
    "geofence:assign asset group",
    "geofence:remove asset group",
    "geofence:deactivate assignment",
    "asset-group:create",
    "asset-group:get my asset groups",
    "asset-group:get",
    "asset-group:update",
    "asset-group:update activation",
    "asset-group:add members",
    "asset-group:remove members",
)


def upgrade() -> None:
    bind = op.get_bind()
    bind.execute(
        sa.text(
            """
            INSERT INTO roles (name, deleted)
            VALUES (:name, 'N')
            ON CONFLICT (name)
            DO UPDATE SET deleted = 'N'
            """
        ),
        {"name": ROLE_NAME},
    )

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
        bind.execute(
            sa.text(
                """
                INSERT INTO service_roles (service_id, role_id, deleted)
                SELECT service.id_service, role.id_role, 'N'
                FROM services AS service
                CROSS JOIN roles AS role
                WHERE service.name = :service_name
                  AND role.name = :role_name
                ON CONFLICT (service_id, role_id)
                DO UPDATE SET deleted = 'N'
                """
            ),
            {"service_name": service_name, "role_name": ROLE_NAME},
        )


def downgrade() -> None:
    bind = op.get_bind()
    bind.execute(
        sa.text(
            """
            UPDATE user_roles
            SET deleted = 'Y'
            WHERE role_id IN (SELECT id_role FROM roles WHERE name = :role_name)
            """
        ),
        {"role_name": ROLE_NAME},
    )
    bind.execute(
        sa.text(
            """
            UPDATE service_roles
            SET deleted = 'Y'
            WHERE role_id IN (SELECT id_role FROM roles WHERE name = :role_name)
            """
        ),
        {"role_name": ROLE_NAME},
    )
    bind.execute(
        sa.text("UPDATE roles SET deleted = 'Y' WHERE name = :role_name"),
        {"role_name": ROLE_NAME},
    )
