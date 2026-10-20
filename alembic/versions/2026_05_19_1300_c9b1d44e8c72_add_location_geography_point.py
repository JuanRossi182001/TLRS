"""add location geography point

Revision ID: c9b1d44e8c72
Revises: a4f2c8d91b63
Create Date: 2026-05-19 13:00:00.000000

"""
from typing import Sequence, Union

from alembic import op


# revision identifiers, used by Alembic.
revision: str = "c9b1d44e8c72"
down_revision: Union[str, Sequence[str], None] = "a4f2c8d91b63"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.execute("CREATE EXTENSION IF NOT EXISTS postgis")
    op.execute(
        "ALTER TABLE locations "
        "ADD COLUMN point geography(Point, 4326)"
    )
    op.execute(
        "UPDATE locations "
        "SET point = ST_SetSRID(ST_MakePoint(longitude, latitude), 4326)::geography "
        "WHERE longitude IS NOT NULL "
        "AND latitude IS NOT NULL "
        "AND point IS NULL"
    )
    op.execute(
        "CREATE INDEX ix_locations_point_gist "
        "ON locations USING gist (point)"
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.execute("DROP INDEX IF EXISTS ix_locations_point_gist")
    op.execute("ALTER TABLE locations DROP COLUMN point")
