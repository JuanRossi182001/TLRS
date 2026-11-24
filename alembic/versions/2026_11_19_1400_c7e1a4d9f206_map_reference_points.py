"""add client map reference points

Revision ID: c7e1a4d9f206
Revises: 5a1c8e3f7b42
Create Date: 2026-11-19 14:00:00.000000
"""

from typing import Sequence, Union

from alembic import op
import geoalchemy2
import sqlalchemy as sa


revision: str = "c7e1a4d9f206"
down_revision: Union[str, Sequence[str], None] = "5a1c8e3f7b42"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "map_reference_points",
        sa.Column("id_map_reference_point", sa.Integer(), nullable=False),
        sa.Column("client_id", sa.Integer(), nullable=False),
        sa.Column("category", sa.String(length=32), nullable=False),
        sa.Column("other_type", sa.String(length=100), nullable=True),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column(
            "point",
            geoalchemy2.types.Geography(
                geometry_type="POINT",
                srid=4326,
                nullable=False,
            ),
            nullable=False,
        ),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column(
            "deleted",
            sa.String(length=1),
            server_default="N",
            nullable=False,
        ),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.CheckConstraint(
            "category IN "
            "('WATER_TROUGH', 'CORRAL', 'SHED', 'FEEDING_POINT', 'OTHER')",
            name="ck_map_reference_points_category",
        ),
        sa.CheckConstraint(
            "(category = 'OTHER' AND other_type IS NOT NULL "
            "AND length(trim(other_type)) > 0) "
            "OR (category <> 'OTHER' AND other_type IS NULL)",
            name="ck_map_reference_points_other_type",
        ),
        sa.ForeignKeyConstraint(["client_id"], ["clients.id_client"]),
        sa.PrimaryKeyConstraint("id_map_reference_point"),
    )


def downgrade() -> None:
    op.drop_table("map_reference_points")
