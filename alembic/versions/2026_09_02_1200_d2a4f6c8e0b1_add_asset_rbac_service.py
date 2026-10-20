"""add asset RBAC service

Revision ID: d2a4f6c8e0b1
Revises: b7c3d5e9f1a2
Create Date: 2026-09-02 12:00:00.000000
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "d2a4f6c8e0b1"
down_revision: Union[str, Sequence[str], None] = "b7c3d5e9f1a2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


SERVICE_NAME = "asset:get my assets"
DEFAULT_ROLE_ID = 1


def upgrade() -> None:
    bind = op.get_bind()
    bind.execute(
        sa.text(
            """
            INSERT INTO services (name, deleted)
            VALUES (:name, 'N')
            ON CONFLICT (name)
            DO UPDATE SET deleted = 'N'
            """
        ),
        {"name": SERVICE_NAME},
    )
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
        {"name": SERVICE_NAME, "role_id": DEFAULT_ROLE_ID},
    )


def downgrade() -> None:
    bind = op.get_bind()
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
        {"name": SERVICE_NAME, "role_id": DEFAULT_ROLE_ID},
    )
    bind.execute(
        sa.text(
            """
            UPDATE services
            SET deleted = 'Y'
            WHERE name = :name
            """
        ),
        {"name": SERVICE_NAME},
    )
