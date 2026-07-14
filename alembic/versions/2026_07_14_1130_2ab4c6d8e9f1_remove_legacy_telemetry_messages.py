"""remove legacy telemetry messages

Revision ID: 2ab4c6d8e9f1
Revises: 5f2c1d8a7b44
Create Date: 2026-07-14 11:30:00.000000
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "2ab4c6d8e9f1"
down_revision: Union[str, Sequence[str], None] = "5f2c1d8a7b44"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


device_protocol_enum = postgresql.ENUM(
    "HTTP",
    "MQTT",
    "CHIRPSTACK",
    name="devicecommunicationprotocol",
    create_type=False,
)


def upgrade() -> None:
    op.drop_table("telemetry_messages")


def downgrade() -> None:
    op.create_table(
        "telemetry_messages",
        sa.Column("id_telemetry", sa.Integer(), nullable=False),
        sa.Column("device_id", sa.Integer(), nullable=False),
        sa.Column("received_at", sa.DateTime(), nullable=False),
        sa.Column("raw_payload", sa.Text(), nullable=False),
        sa.Column("protocol", device_protocol_enum, nullable=False),
        sa.Column(
            "processed",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
        sa.Column("error_message", sa.String(), nullable=True),
        sa.Column("source_ip", sa.String(), nullable=True),
        sa.Column(
            "deleted",
            sa.String(length=1),
            nullable=False,
            server_default="N",
        ),
        sa.ForeignKeyConstraint(["device_id"], ["devices.id_device"]),
        sa.PrimaryKeyConstraint("id_telemetry"),
    )
