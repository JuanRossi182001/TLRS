"""index device latest-location lookup

Revision ID: 5a1c8e3f7b42
Revises: 4d8a2f6c1b90
Create Date: 2026-11-19 13:00:00.000000
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "5a1c8e3f7b42"
down_revision: Union[str, Sequence[str], None] = "4d8a2f6c1b90"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_index(
        "ix_locations_device_latest_received",
        "locations",
        [
            "device_id",
            sa.text("received_at DESC"),
            sa.text("id_location DESC"),
        ],
        postgresql_where=sa.text("deleted = 'N'"),
    )


def downgrade() -> None:
    op.drop_index(
        "ix_locations_device_latest_received",
        table_name="locations",
    )
