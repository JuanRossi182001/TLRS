"""add device command and ack topics

Revision ID: 8c1f2a9b7d44
Revises: 3f4c8b9d2a11
Create Date: 2026-06-06 12:00:00.000000
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "8c1f2a9b7d44"
down_revision: Union[str, Sequence[str], None] = "3f4c8b9d2a11"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "device_credentials",
        sa.Column("commands_topic", sa.String(), nullable=True),
    )
    op.add_column(
        "device_credentials",
        sa.Column("acks_topic", sa.String(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("device_credentials", "acks_topic")
    op.drop_column("device_credentials", "commands_topic")
