"""active device unique indexes

Revision ID: a4f2c8d91b63
Revises: 6f0d9d3a4b21
Create Date: 2026-05-19 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "a4f2c8d91b63"
down_revision: Union[str, Sequence[str], None] = "6f0d9d3a4b21"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.execute("ALTER TABLE devices DROP CONSTRAINT IF EXISTS devices_serial_key")
    op.execute(
        "ALTER TABLE device_credentials "
        "DROP CONSTRAINT IF EXISTS device_credentials_mqtt_username_key"
    )
    op.execute(
        "ALTER TABLE device_credentials "
        "DROP CONSTRAINT IF EXISTS uq_device_credentials_mqtt_password_hash"
    )
    op.execute(
        "ALTER TABLE device_credentials "
        "DROP CONSTRAINT IF EXISTS uq_device_credentials_mqtt_password_encrypted"
    )

    op.create_index(
        "uq_devices_serial_active",
        "devices",
        ["serial"],
        unique=True,
        postgresql_where=sa.text("deleted = 'N'"),
    )
    op.create_index(
        "uq_device_credentials_mqtt_username_active",
        "device_credentials",
        ["mqtt_username"],
        unique=True,
        postgresql_where=sa.text("deleted = 'N' AND mqtt_username IS NOT NULL"),
    )
    op.create_index(
        "uq_device_credentials_mqtt_password_hash_active",
        "device_credentials",
        ["mqtt_password_hash"],
        unique=True,
        postgresql_where=sa.text("deleted = 'N' AND mqtt_password_hash IS NOT NULL"),
    )
    op.create_index(
        "uq_device_credentials_mqtt_password_encrypted_active",
        "device_credentials",
        ["mqtt_password_encrypted"],
        unique=True,
        postgresql_where=sa.text(
            "deleted = 'N' AND mqtt_password_encrypted IS NOT NULL"
        ),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index("uq_device_credentials_mqtt_password_encrypted_active")
    op.drop_index("uq_device_credentials_mqtt_password_hash_active")
    op.drop_index("uq_device_credentials_mqtt_username_active")
    op.drop_index("uq_devices_serial_active")

    op.create_unique_constraint(
        "devices_serial_key",
        "devices",
        ["serial"],
    )
    op.create_unique_constraint(
        "device_credentials_mqtt_username_key",
        "device_credentials",
        ["mqtt_username"],
    )
    op.create_unique_constraint(
        "uq_device_credentials_mqtt_password_hash",
        "device_credentials",
        ["mqtt_password_hash"],
    )
    op.create_unique_constraint(
        "uq_device_credentials_mqtt_password_encrypted",
        "device_credentials",
        ["mqtt_password_encrypted"],
    )
