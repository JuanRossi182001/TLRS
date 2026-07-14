"""remove legacy device credentials

Revision ID: 5f2c1d8a7b44
Revises: 7e4f6a1c9b2d
Create Date: 2026-07-14 10:30:00.000000
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "5f2c1d8a7b44"
down_revision: Union[str, Sequence[str], None] = "7e4f6a1c9b2d"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


credential_status_enum = postgresql.ENUM(
    "ACTIVE",
    "REVOKED",
    name="credentialstatus",
)
mqtt_provider_enum = postgresql.ENUM(
    "EMQX_CLOUD",
    "MOSQUITTO",
    name="mqttprovider",
)


def upgrade() -> None:
    op.drop_table("device_credentials")
    credential_status_enum.drop(op.get_bind(), checkfirst=True)
    mqtt_provider_enum.drop(op.get_bind(), checkfirst=True)


def downgrade() -> None:
    credential_status_enum.create(op.get_bind(), checkfirst=True)
    mqtt_provider_enum.create(op.get_bind(), checkfirst=True)

    op.create_table(
        "device_credentials",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("device_id", sa.Integer(), nullable=False),
        sa.Column("secret", sa.String(), nullable=False),
        sa.Column("mqtt_username", sa.String(), nullable=True),
        sa.Column("mqtt_password_hash", sa.String(), nullable=True),
        sa.Column("mqtt_password_encrypted", sa.String(), nullable=True),
        sa.Column("mqtt_provider", mqtt_provider_enum, nullable=True),
        sa.Column("location_topic", sa.String(), nullable=True),
        sa.Column("status_topic", sa.String(), nullable=True),
        sa.Column("heartbeat_topic", sa.String(), nullable=True),
        sa.Column("commands_topic", sa.String(), nullable=True),
        sa.Column("acks_topic", sa.String(), nullable=True),
        sa.Column("deleted", sa.String(length=1), nullable=False, server_default="N"),
        sa.Column("status", credential_status_enum, nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("revoked_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["device_id"], ["devices.id_device"]),
        sa.PrimaryKeyConstraint("id"),
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
