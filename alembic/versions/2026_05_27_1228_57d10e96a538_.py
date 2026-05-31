"""create geofence tables

Revision ID: 57d10e96a538
Revises: b8c1e9d2a734
Create Date: 2026-05-27 12:28:07.180789
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql
import geoalchemy2


revision: str = "57d10e96a538"
down_revision: Union[str, Sequence[str], None] = "b8c1e9d2a734"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


fence_event_type_enum = postgresql.ENUM(
    "NEAR_LIMIT",
    "EXITED",
    "ENTERED",
    "RETURNED",
    "GPS_UNCERTAIN",
    name="fenceeventtype",
    create_type=False,
)


def upgrade() -> None:
    fence_event_type_enum.create(op.get_bind(), checkfirst=True)

    op.create_table(
        "geofences",
        sa.Column("id_geofence", sa.Integer(), nullable=False),
        sa.Column("client_id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("description", sa.String(), nullable=True),
        sa.Column(
            "shape",
            geoalchemy2.types.Geometry(
                geometry_type="MULTIPOLYGON",
                srid=4326,
                dimension=2,
                from_text="ST_GeomFromEWKT",
                name="geometry",
                spatial_index=False,
            ),
            nullable=False,
        ),
        sa.Column("active", sa.Boolean(), nullable=False),
        sa.Column("deleted", sa.String(length=1), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["client_id"], ["clients.id_client"]),
        sa.PrimaryKeyConstraint("id_geofence"),
    )

    op.create_index(
        "idx_geofences_shape",
        "geofences",
        ["shape"],
        unique=False,
        postgresql_using="gist",
    )
    op.create_index(
        "idx_geofences_client_id",
        "geofences",
        ["client_id"],
    )
    op.create_index(
        "uq_geofences_client_name_active",
        "geofences",
        ["client_id", "name"],
        unique=True,
        postgresql_where=sa.text("deleted = 'N'"),
    )

    op.create_table(
        "geofence_assignments",
        sa.Column("id_assignment", sa.Integer(), nullable=False),
        sa.Column("asset_id", sa.Integer(), nullable=False),
        sa.Column("fence_id", sa.Integer(), nullable=False),
        sa.Column("active", sa.Boolean(), nullable=False),
        sa.Column("deleted", sa.String(length=1), nullable=False),
        sa.Column("assigned_at", sa.DateTime(), nullable=False),
        sa.Column("unassigned_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["asset_id"], ["assets.id_asset"]),
        sa.ForeignKeyConstraint(["fence_id"], ["geofences.id_geofence"]),
        sa.PrimaryKeyConstraint("id_assignment"),
    )

    op.create_index(
        "idx_geofence_assignments_asset_id",
        "geofence_assignments",
        ["asset_id"],
    )

    op.create_index(
        "idx_geofence_assignments_fence_id",
        "geofence_assignments",
        ["fence_id"],
    )
    op.create_index(
        "uq_geofence_assignments_asset_fence_active",
        "geofence_assignments",
        ["asset_id", "fence_id"],
        unique=True,
        postgresql_where=sa.text("deleted = 'N' AND active = true"),
    )

    op.create_table(
        "geofence_events",
        sa.Column("id_event", sa.Integer(), nullable=False),
        sa.Column("fence_id", sa.Integer(), nullable=False),
        sa.Column("device_id", sa.Integer(), nullable=False),
        sa.Column("asset_id", sa.Integer(), nullable=True),
        sa.Column("location_id", sa.Integer(), nullable=False),
        sa.Column("event_type", fence_event_type_enum, nullable=False),
        sa.Column("distance_to_boundary_meters", sa.Float(), nullable=True),
        sa.Column("accuracy", sa.Float(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["asset_id"], ["assets.id_asset"]),
        sa.ForeignKeyConstraint(["device_id"], ["devices.id_device"]),
        sa.ForeignKeyConstraint(["fence_id"], ["geofences.id_geofence"]),
        sa.ForeignKeyConstraint(["location_id"], ["locations.id_location"]),
        sa.PrimaryKeyConstraint("id_event"),
    )

    op.create_index(
        "idx_geofence_events_device_id_created_at",
        "geofence_events",
        ["device_id", "created_at"],
    )

    op.create_index(
        "idx_geofence_events_location_id",
        "geofence_events",
        ["location_id"],
    )

    op.create_index(
        "idx_geofence_events_fence_id_created_at",
        "geofence_events",
        ["fence_id", "created_at"],
    )


def downgrade() -> None:
    op.drop_index("idx_geofence_events_fence_id_created_at", table_name="geofence_events")
    op.drop_index("idx_geofence_events_location_id", table_name="geofence_events")
    op.drop_index("idx_geofence_events_device_id_created_at", table_name="geofence_events")
    op.drop_table("geofence_events")

    op.drop_index("uq_geofence_assignments_asset_fence_active", table_name="geofence_assignments")
    op.drop_index("idx_geofence_assignments_fence_id", table_name="geofence_assignments")
    op.drop_index("idx_geofence_assignments_asset_id", table_name="geofence_assignments")
    op.drop_table("geofence_assignments")

    op.drop_index("uq_geofences_client_name_active", table_name="geofences")
    op.drop_index("idx_geofences_client_id", table_name="geofences")
    op.drop_index("idx_geofences_shape", table_name="geofences")
    op.drop_table("geofences")

    fence_event_type_enum.drop(op.get_bind(), checkfirst=True)
