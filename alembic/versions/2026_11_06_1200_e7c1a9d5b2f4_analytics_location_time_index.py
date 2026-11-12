"""Index scoped historical location scans on their actual ordering expression.

Revision ID: e7c1a9d5b2f4
Revises: 9a7c4d2e6f10
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "e7c1a9d5b2f4"
down_revision: Union[str, Sequence[str], None] = "9a7c4d2e6f10"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_index(
        "ix_locations_analytics_device_observed",
        "locations",
        ["device_id", sa.text("COALESCE(device_timestamp, received_at)"), "id_location"],
        postgresql_where=sa.text("deleted = 'N'"),
    )


def downgrade() -> None:
    op.drop_index("ix_locations_analytics_device_observed", table_name="locations")
