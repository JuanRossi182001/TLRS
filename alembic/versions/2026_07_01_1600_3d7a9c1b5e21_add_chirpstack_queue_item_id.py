"""add chirpstack queue item id to device commands

Revision ID: 3d7a9c1b5e21
Revises: b91c2e7d4a10
Create Date: 2026-07-01 16:00:00.000000
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "3d7a9c1b5e21"
down_revision: Union[str, Sequence[str], None] = "b91c2e7d4a10"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "device_commands",
        sa.Column("chirpstack_queue_item_id", sa.String(), nullable=True),
    )
    op.create_index(
        "idx_device_commands_chirpstack_queue_item_id",
        "device_commands",
        ["chirpstack_queue_item_id"],
    )


def downgrade() -> None:
    op.drop_index(
        "idx_device_commands_chirpstack_queue_item_id",
        table_name="device_commands",
    )
    op.drop_column("device_commands", "chirpstack_queue_item_id")
