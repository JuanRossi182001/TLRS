"""add command seq for binary contract v1

Revision ID: 7e4f6a1c9b2d
Revises: 3d7a9c1b5e21
Create Date: 2026-07-13 12:00:00.000000
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "7e4f6a1c9b2d"
down_revision: Union[str, Sequence[str], None] = "3d7a9c1b5e21"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("ALTER TYPE devicecommandtype ADD VALUE IF NOT EXISTS 'REQUEST_STATUS'")

    op.add_column(
        "device_commands",
        sa.Column("command_seq", sa.Integer(), nullable=True),
    )
    op.create_index(
        "idx_device_commands_device_id_command_seq",
        "device_commands",
        ["device_id", "command_seq"],
    )
    op.create_unique_constraint(
        "uq_device_commands_device_id_command_seq",
        "device_commands",
        ["device_id", "command_seq"],
    )
    op.create_check_constraint(
        "ck_device_commands_command_seq_uint16",
        "device_commands",
        "command_seq IS NULL OR (command_seq >= 1 AND command_seq <= 65535)",
    )


def downgrade() -> None:
    op.drop_constraint(
        "ck_device_commands_command_seq_uint16",
        "device_commands",
        type_="check",
    )
    op.drop_constraint(
        "uq_device_commands_device_id_command_seq",
        "device_commands",
        type_="unique",
    )
    op.drop_index(
        "idx_device_commands_device_id_command_seq",
        table_name="device_commands",
    )
    op.drop_column("device_commands", "command_seq")
