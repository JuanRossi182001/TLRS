"""device commands

Revision ID: 3f4c8b9d2a11
Revises: 90492c6dd84e
Create Date: 2026-06-04 16:00:00.000000
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "3f4c8b9d2a11"
down_revision: Union[str, Sequence[str], None] = "90492c6dd84e"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


device_command_type_enum = postgresql.ENUM(
    "SET_REPORT_INTERVAL",
    "WARNING_SOUND",
    "VIBRATION",
    "STOP_CORRECTION",
    "EMERGENCY_DISABLE",
    name="devicecommandtype",
    create_type=False,
)

device_command_status_enum = postgresql.ENUM(
    "PENDING",
    "SENT",
    "ACKED",
    "FAILED",
    "EXPIRED",
    name="devicecommandstatus",
    create_type=False,
)


def upgrade() -> None:
    bind = op.get_bind()
    device_command_type_enum.create(bind, checkfirst=True)
    device_command_status_enum.create(bind, checkfirst=True)

    op.create_table(
        "device_commands",
        sa.Column("id_command", sa.Integer(), nullable=False),
        sa.Column("command_uuid", sa.String(), nullable=False),
        sa.Column("device_id", sa.Integer(), nullable=False),
        sa.Column("asset_id", sa.Integer(), nullable=True),
        sa.Column("geofence_event_id", sa.Integer(), nullable=True),
        sa.Column("command_type", device_command_type_enum, nullable=False),
        sa.Column("status", device_command_status_enum, nullable=False),
        sa.Column("topic", sa.String(), nullable=False),
        sa.Column("payload", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("qos", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("retain", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("sent_at", sa.DateTime(), nullable=True),
        sa.Column("ack_at", sa.DateTime(), nullable=True),
        sa.Column("failed_at", sa.DateTime(), nullable=True),
        sa.Column("expires_at", sa.DateTime(), nullable=True),
        sa.Column("error_message", sa.String(), nullable=True),
        sa.ForeignKeyConstraint(["asset_id"], ["assets.id_asset"]),
        sa.ForeignKeyConstraint(["device_id"], ["devices.id_device"]),
        sa.ForeignKeyConstraint(["geofence_event_id"], ["geofence_events.id_event"]),
        sa.PrimaryKeyConstraint("id_command"),
        sa.UniqueConstraint("command_uuid", name="uq_device_commands_command_uuid"),
    )

    op.create_index(
        "idx_device_commands_status_created_at",
        "device_commands",
        ["status", "created_at"],
    )
    op.create_index(
        "idx_device_commands_device_id_created_at",
        "device_commands",
        ["device_id", "created_at"],
    )
    op.create_index(
        "idx_device_commands_geofence_event_id",
        "device_commands",
        ["geofence_event_id"],
    )


def downgrade() -> None:
    op.drop_index(
        "idx_device_commands_geofence_event_id",
        table_name="device_commands",
    )
    op.drop_index(
        "idx_device_commands_device_id_created_at",
        table_name="device_commands",
    )
    op.drop_index(
        "idx_device_commands_status_created_at",
        table_name="device_commands",
    )
    op.drop_table("device_commands")

    bind = op.get_bind()
    device_command_status_enum.drop(bind, checkfirst=True)
    device_command_type_enum.drop(bind, checkfirst=True)
