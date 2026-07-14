"""add chirpstack command network ack fields

Revision ID: b91c2e7d4a10
Revises: d4c8e1f9b2a6
Create Date: 2026-06-30 19:30:00.000000
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "b91c2e7d4a10"
down_revision: Union[str, Sequence[str], None] = "d4c8e1f9b2a6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("device_commands", sa.Column("tx_acked_at", sa.DateTime(), nullable=True))
    op.add_column("device_commands", sa.Column("lorawan_ack_at", sa.DateTime(), nullable=True))


def downgrade() -> None:
    op.drop_column("device_commands", "lorawan_ack_at")
    op.drop_column("device_commands", "tx_acked_at")
