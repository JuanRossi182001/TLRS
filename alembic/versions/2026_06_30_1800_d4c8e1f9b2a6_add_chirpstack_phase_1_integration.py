"""add chirpstack phase 1 integration

Revision ID: d4c8e1f9b2a6
Revises: a7f43b6d9211
Create Date: 2026-06-30 18:00:00.000000
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "d4c8e1f9b2a6"
down_revision: Union[str, Sequence[str], None] = "a7f43b6d9211"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


device_protocol_enum = postgresql.ENUM(
    "HTTP",
    "MQTT",
    "CHIRPSTACK",
    name="devicecommunicationprotocol",
)
device_protocol_enum_without_chirpstack = postgresql.ENUM(
    "HTTP",
    "MQTT",
    name="devicecommunicationprotocol",
)


def upgrade() -> None:
    bind = op.get_bind()

    op.execute("ALTER TYPE devicecommunicationprotocol ADD VALUE IF NOT EXISTS 'CHIRPSTACK'")

    op.add_column("devices", sa.Column("chirpstack_dev_eui", sa.String(), nullable=True))
    op.add_column(
        "devices",
        sa.Column("chirpstack_application_id", sa.String(), nullable=True),
    )
    op.add_column("devices", sa.Column("lorawan_class", sa.String(), nullable=True))
    op.add_column(
        "devices",
        sa.Column("chirpstack_device_profile_id", sa.String(), nullable=True),
    )
    op.create_index(
        "uq_devices_chirpstack_dev_eui_active",
        "devices",
        ["chirpstack_dev_eui"],
        unique=True,
        postgresql_where=sa.text("deleted = 'N' AND chirpstack_dev_eui IS NOT NULL"),
    )

    op.create_table(
        "chirpstack_events",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("device_id", sa.Integer(), nullable=True),
        sa.Column("event_type", sa.String(), nullable=False),
        sa.Column("application_id", sa.String(), nullable=False),
        sa.Column("dev_eui", sa.String(), nullable=False),
        sa.Column("deduplication_id", sa.String(), nullable=True),
        sa.Column("topic", sa.String(), nullable=False),
        sa.Column("payload", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column(
            "processed",
            sa.Boolean(),
            server_default=sa.false(),
            nullable=False,
        ),
        sa.Column("error_message", sa.String(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("TIMEZONE('utc', NOW())"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["device_id"], ["devices.id_device"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("deduplication_id", name="uq_chirpstack_events_deduplication_id"),
    )
    op.create_index(
        "idx_chirpstack_events_device_id_created_at",
        "chirpstack_events",
        ["device_id", "created_at"],
    )
    op.create_index(
        "idx_chirpstack_events_dev_eui_created_at",
        "chirpstack_events",
        ["dev_eui", "created_at"],
    )

    device_protocol_enum.create(bind, checkfirst=True)


def downgrade() -> None:
    bind = op.get_bind()

    op.drop_index("idx_chirpstack_events_dev_eui_created_at", table_name="chirpstack_events")
    op.drop_index("idx_chirpstack_events_device_id_created_at", table_name="chirpstack_events")
    op.drop_table("chirpstack_events")

    op.drop_index("uq_devices_chirpstack_dev_eui_active", table_name="devices")
    op.drop_column("devices", "chirpstack_device_profile_id")
    op.drop_column("devices", "lorawan_class")
    op.drop_column("devices", "chirpstack_application_id")
    op.drop_column("devices", "chirpstack_dev_eui")

    op.execute(
        "UPDATE devices SET communication_protocol = 'MQTT' WHERE communication_protocol = 'CHIRPSTACK'"
    )
    op.execute(
        "UPDATE telemetry_messages SET protocol = 'MQTT' WHERE protocol = 'CHIRPSTACK'"
    )

    op.execute("ALTER TYPE devicecommunicationprotocol RENAME TO devicecommunicationprotocol_old")
    device_protocol_enum_without_chirpstack.create(bind, checkfirst=False)

    op.execute(
        """
        ALTER TABLE devices
        ALTER COLUMN communication_protocol TYPE devicecommunicationprotocol
        USING communication_protocol::text::devicecommunicationprotocol
        """
    )
    op.execute(
        """
        ALTER TABLE telemetry_messages
        ALTER COLUMN protocol TYPE devicecommunicationprotocol
        USING protocol::text::devicecommunicationprotocol
        """
    )

    postgresql.ENUM(
        "HTTP",
        "MQTT",
        "CHIRPSTACK",
        name="devicecommunicationprotocol_old",
    ).drop(bind, checkfirst=False)
